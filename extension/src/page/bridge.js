/**
 * Page-world (MAIN) bridge. Runs at document_start on youtube.com.
 *
 * Why this exists: YouTube's `/api/timedtext` endpoint no longer serves a caption body just
 * because you hold the `baseUrl` from `ytInitialPlayerResponse`. Verified from this repository,
 * a direct request for that URL - with session cookies, Referer and Origin all correct - returns
 * HTTP 200 with a zero-byte body, because the real player attaches a proof-of-origin token that
 * only its own runtime can mint.
 *
 * So the extension does not try to out-argue YouTube for the bytes. It asks the page's own player
 * to turn the English caption track on, then reads the timed-text response that the player
 * legitimately fetched for itself. Nothing is scraped from third parties and no caption text is
 * invented; this is the same data YouTube is already rendering.
 *
 * `fetch`/`XMLHttpRequest` can only be observed from the page world, hence `world: "MAIN"`. The
 * isolated content script cannot see them. Communication is a narrow `window.postMessage`
 * protocol: this file only ever emits the message types below and only accepts two commands.
 */
(() => {
  const SOURCE = 'signora-page'
  const SINK = 'signora-content'
  const TIMEDTEXT = '/api/timedtext'

  if (window.__signoraBridgeInstalled) return
  window.__signoraBridgeInstalled = true

  /** Latest captured timed-text payloads, newest last, capped so a long session cannot grow. */
  const captured = []

  function post(type, payload) {
    try {
      window.postMessage({ source: SOURCE, type, payload }, window.location.origin)
    } catch {
      // A payload that cannot be structured-cloned is not worth breaking the page over.
    }
  }

  function remember(url, body) {
    if (typeof body !== 'string' || !body.trim()) return
    captured.push({ url: String(url), body, at: Date.now() })
    if (captured.length > 8) captured.shift()
    post('timedtext', { url: String(url), body })
  }

  function isTimedText(url) {
    return typeof url === 'string' && url.includes(TIMEDTEXT)
  }

  // --- Observe fetch -----------------------------------------------------------------------
  const nativeFetch = window.fetch
  if (typeof nativeFetch === 'function') {
    window.fetch = function signoraFetch(input, init) {
      const url = typeof input === 'string' ? input : (input && input.url) || ''
      const promise = nativeFetch.apply(this, arguments)
      if (isTimedText(url)) {
        promise.then((response) => {
          // Never consume the body the player is about to read.
          try { response.clone().text().then((body) => remember(url, body), () => {}) } catch { /* ignore */ }
          return response
        }, () => {})
      }
      return promise
    }
  }

  // --- Observe XMLHttpRequest --------------------------------------------------------------
  const NativeXhr = window.XMLHttpRequest
  if (typeof NativeXhr === 'function') {
    const open = NativeXhr.prototype.open
    NativeXhr.prototype.open = function signoraOpen(method, url) {
      if (isTimedText(url)) {
        this.addEventListener('load', () => {
          try {
            if (typeof this.responseText === 'string') remember(url, this.responseText)
          } catch { /* responseType not text; ignore */ }
        })
      }
      return open.apply(this, arguments)
    }
  }

  // --- Player interrogation ----------------------------------------------------------------
  function player() {
    const element = document.getElementById('movie_player')
    return element && typeof element.getPlayerResponse === 'function' ? element : null
  }

  function playerResponse() {
    const live = player()
    if (live) {
      try {
        const response = live.getPlayerResponse()
        if (response) return response
      } catch { /* fall through to the bootstrap copy */ }
    }
    return window.ytInitialPlayerResponse || null
  }

  function captionTracks() {
    const response = playerResponse()
    const list = response
      && response.captions
      && response.captions.playerCaptionsTracklistRenderer
      && response.captions.playerCaptionsTracklistRenderer.captionTracks
    if (!Array.isArray(list)) return []
    return list.map((track) => ({
      languageCode: track.languageCode || '',
      kind: track.kind || 'manual',
      vssId: track.vssId || '',
      name: (track.name && (track.name.simpleText
        || (Array.isArray(track.name.runs) ? track.name.runs.map((r) => r.text).join('') : ''))) || '',
      baseUrl: track.baseUrl || '',
      isTranslatable: Boolean(track.isTranslatable),
    }))
  }

  function videoId() {
    const response = playerResponse()
    const fromResponse = response && response.videoDetails && response.videoDetails.videoId
    if (fromResponse) return fromResponse
    try { return new URL(window.location.href).searchParams.get('v') || '' } catch { return '' }
  }

  function describe() {
    const response = playerResponse()
    return {
      videoId: videoId(),
      title: (response && response.videoDetails && response.videoDetails.title) || '',
      lengthSeconds: Number((response && response.videoDetails && response.videoDetails.lengthSeconds) || 0),
      tracks: captionTracks(),
      captured: captured.map((entry) => ({ url: entry.url, at: entry.at })),
    }
  }

  /**
   * Ask the player to load and select a caption track so it fetches the timed text itself.
   *
   * `setOption` alone is not reliable: the captions module loads asynchronously, and on a paused
   * video that has never shown captions the player may not request timed text at all until the
   * subtitles button is actually toggled. So this escalates - load the module, select the track,
   * retry once the module has had time to initialise, and finally press the real CC button -
   * stopping as soon as a timed-text response has been captured.
   */
  function enableCaptions(languageCode) {
    const live = player()
    if (!live) return { ok: false, reason: 'The YouTube player element is not ready yet.' }

    const tracks = captionTracks()
    const wanted = tracks.find((t) => t.languageCode === languageCode)
      || tracks.find((t) => (t.languageCode || '').toLowerCase().startsWith('en'))
      || tracks[0]
    if (!wanted) return { ok: false, reason: 'This video exposes no caption tracks.' }

    const before = captured.length
    const attempts = []

    const selectTrack = () => {
      try {
        if (typeof live.loadModule === 'function') live.loadModule('captions')
        if (typeof live.setOption === 'function') {
          live.setOption('captions', 'track', { languageCode: wanted.languageCode })
          return 'setOption'
        }
      } catch (error) {
        return `setOption failed: ${String((error && error.message) || error)}`
      }
      return 'setOption unavailable'
    }

    const pressCaptionButton = () => {
      const button = document.querySelector('.ytp-subtitles-button, .ytp-closed-captions-button')
      if (!button) return 'cc button not found'
      // aria-pressed tells us whether captions are already on; only turn them on.
      if (button.getAttribute('aria-pressed') === 'true') return 'cc already on'
      button.click()
      return 'cc button clicked'
    }

    attempts.push(selectTrack())

    // Escalate on a timer; each step is skipped once something has been captured.
    setTimeout(() => {
      if (captured.length > before) return
      attempts.push(selectTrack())
    }, 600)
    setTimeout(() => {
      if (captured.length > before) return
      attempts.push(pressCaptionButton())
      post('capture-progress', { attempts })
    }, 1600)

    return { ok: true, selected: wanted.languageCode, kind: wanted.kind, attempts }
  }

  /** Replay anything already captured, for a content script that attached late. */
  function flush() {
    for (const entry of captured) post('timedtext', { url: entry.url, body: entry.body })
  }

  window.addEventListener('message', (event) => {
    if (event.source !== window) return
    const data = event.data
    if (!data || data.source !== SINK) return

    if (data.type === 'describe') {
      post('described', { requestId: data.requestId, value: describe() })
    } else if (data.type === 'enable-captions') {
      post('captions-enabled', {
        requestId: data.requestId,
        value: enableCaptions((data.payload && data.payload.languageCode) || 'en'),
      })
    } else if (data.type === 'flush') {
      flush()
    }
  })

  post('ready', { at: Date.now() })
})()
