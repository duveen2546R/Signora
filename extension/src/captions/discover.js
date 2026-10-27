/**
 * Obtain English captions for the current watch page, as a WebVTT string.
 *
 * Strategy, in order, stopping at the first that yields real cues:
 *   1. If the page's player has already fetched timed text, use what the bridge captured.
 *   2. Ask the player to select the English track, then wait for the bridge to capture the
 *      response the player itself fetches. This is the path that works in practice, because
 *      YouTube requires a player-minted token on `/api/timedtext` (verified: a direct request
 *      for the published `baseUrl`, with cookies and correct Referer/Origin, returns HTTP 200
 *      and an empty body).
 *   3. Try a plain same-origin GET of the track's `baseUrl` with `&fmt=json3`. Cheap, and still
 *      works on some videos, so it is worth one attempt - but it is the fallback, not the plan.
 *
 * If all three fail the caller gets a `CaptionsUnavailableError` and the overlay offers the
 * manual subtitle-file path. No caption text is ever synthesised.
 */

import { timedTextToVtt } from './convert.js'
import { config, log } from '../config.js'

export class CaptionsUnavailableError extends Error {
  constructor(message, { tracks = [] } = {}) {
    super(message)
    this.name = 'CaptionsUnavailableError'
    this.tracks = tracks
  }
}

const PAGE = 'signora-page'
const CONTENT = 'signora-content'

/** Narrow postMessage client for the MAIN-world bridge in src/page/bridge.js. */
export class PageBridge {
  constructor() {
    this.nextId = 1
    this.pending = new Map()
    this.captured = []
    this.listeners = new Set()
    this.onMessage = this.onMessage.bind(this)
    window.addEventListener('message', this.onMessage)
  }

  onMessage(event) {
    if (event.source !== window) return
    const data = event.data
    if (!data || data.source !== PAGE) return
    const payload = data.payload || {}

    if (data.type === 'timedtext') {
      this.captured.push(payload)
      if (this.captured.length > 8) this.captured.shift()
      for (const listener of this.listeners) listener(payload)
      return
    }
    if (payload.requestId && this.pending.has(payload.requestId)) {
      const { resolve } = this.pending.get(payload.requestId)
      this.pending.delete(payload.requestId)
      resolve(payload.value)
    }
  }

  #request(type, payload = {}, timeoutMs = 4000) {
    const requestId = `r${this.nextId}`
    this.nextId += 1
    return new Promise((resolve) => {
      this.pending.set(requestId, { resolve })
      window.postMessage({ source: CONTENT, type, requestId, payload }, window.location.origin)
      setTimeout(() => {
        if (this.pending.delete(requestId)) resolve(undefined)
      }, timeoutMs)
    })
  }

  describe() { return this.#request('describe') }
  enableCaptions(languageCode) { return this.#request('enable-captions', { languageCode }) }
  flush() { window.postMessage({ source: CONTENT, type: 'flush' }, window.location.origin) }

  onTimedText(listener) {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  /** Resolve with the next captured payload that converts to at least one cue. */
  waitForTimedText(timeoutMs) {
    return new Promise((resolve) => {
      let settled = false
      const finish = (value) => {
        if (settled) return
        settled = true
        off()
        clearTimeout(timer)
        resolve(value)
      }
      const off = this.onTimedText((payload) => {
        try {
          finish({ ...timedTextToVtt(payload.body), url: payload.url })
        } catch {
          // Not usable (often an empty body); keep waiting for a better one.
        }
      })
      const timer = setTimeout(() => finish(null), timeoutMs)
    })
  }

  destroy() {
    window.removeEventListener('message', this.onMessage)
    this.listeners.clear()
  }
}

function pickEnglishTrack(tracks, preferred) {
  if (!Array.isArray(tracks) || !tracks.length) return null
  for (const language of preferred) {
    const exact = tracks.find((t) => (t.languageCode || '').toLowerCase() === language.toLowerCase())
    if (exact) return exact
  }
  // Any English variant, manual before auto-generated.
  const english = tracks.filter((t) => (t.languageCode || '').toLowerCase().startsWith('en'))
  if (!english.length) return null
  return english.find((t) => t.kind !== 'asr') || english[0]
}

/** Try the captured payloads already in hand. */
function fromCaptured(bridge) {
  for (let i = bridge.captured.length - 1; i >= 0; i -= 1) {
    const payload = bridge.captured[i]
    try {
      return { ...timedTextToVtt(payload.body), url: payload.url }
    } catch {
      // keep looking
    }
  }
  return null
}

/** Last-resort direct GET; same-origin so cookies ride along. */
async function fromBaseUrl(track) {
  if (!track?.baseUrl) return null
  const separator = track.baseUrl.includes('?') ? '&' : '?'
  for (const format of ['json3', '']) {
    const url = `${track.baseUrl}${format ? `${separator}fmt=${format}` : ''}`
    try {
      const response = await fetch(url, { credentials: 'include' })
      if (!response.ok) continue
      const body = await response.text()
      if (!body.trim()) continue
      return { ...timedTextToVtt(body), url }
    } catch {
      // Network or conversion failure; try the next format.
    }
  }
  return null
}

/**
 * @returns {Promise<{ vtt: string, cues: Array, format: string, track: object|null, via: string }>}
 */
export async function discoverCaptions(bridge, { onStatus = () => {} } = {}) {
  const settings = config()
  bridge.flush()

  const description = (await bridge.describe()) || { tracks: [] }
  const tracks = description.tracks || []
  const track = pickEnglishTrack(tracks, settings.captionLanguages)

  if (!tracks.length) {
    throw new CaptionsUnavailableError(
      'This video exposes no caption tracks at all.', { tracks },
    )
  }
  if (!track) {
    const languages = [...new Set(tracks.map((t) => t.languageCode).filter(Boolean))]
    throw new CaptionsUnavailableError(
      `No English captions available. This video offers: ${languages.join(', ') || 'unknown'}.`,
      { tracks },
    )
  }

  const already = fromCaptured(bridge)
  if (already) {
    log('captions from already-captured player request')
    return { ...already, track, via: 'player-capture' }
  }

  onStatus(track.kind === 'asr'
    ? 'Asking YouTube for its auto-generated English captions…'
    : 'Asking YouTube for its English captions…')

  // Start listening before asking, so a fast response cannot be missed.
  const waiting = bridge.waitForTimedText(settings.captionCaptureTimeoutMs)
  const enabled = await bridge.enableCaptions(track.languageCode)
  if (enabled && enabled.ok === false) log('enableCaptions declined:', enabled.reason)

  const captured = await waiting
  if (captured) {
    log('captions captured from the player request')
    return { ...captured, track, via: 'player-capture' }
  }

  onStatus('Trying the published caption URL directly…')
  const direct = await fromBaseUrl(track)
  if (direct) {
    log('captions fetched directly from baseUrl')
    return { ...direct, track, via: 'base-url' }
  }

  throw new CaptionsUnavailableError(
    'YouTube listed an English caption track but would not return its text. '
    + 'This is expected when the player refuses to serve timed text to anything but itself. '
    + 'Turn the CC button on and retry, or load a subtitle file manually.',
    { tracks },
  )
}
