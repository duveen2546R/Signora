/**
 * Unity WebGL avatar adapter, driven through an iframe + postMessage.
 *
 * STATUS: written against the existing runtime's public surface, but NOT verified end to end in
 * this repository. It is off by default (`config.avatarAdapter === 'mock'`). Do not treat it as
 * working until the checklist in extension/README.md has actually been run in a browser.
 *
 * Why an iframe rather than loading Unity into the YouTube page: youtube.com ships a strict
 * Content-Security-Policy, and the Unity loader needs `wasm-unsafe-eval` plus a ~60 MB
 * script/wasm/data fetch from another origin. A content script cannot relax the host page's CSP,
 * so the runtime is hosted on its own origin (the Signora frontend) and addressed across the
 * frame boundary. That also keeps `window.signsure` exactly where the existing
 * `SignoraStage.jsx` already installs it.
 *
 * The missing piece is one host page on the frontend origin that mounts `<SignoraStage />` and
 * relays the message protocol below onto `window.signsure`. See README "Unity handoff".
 *
 * Protocol, extension -> host page:
 *   { signora: 'cmd', id, method: 'play'|'pause'|'resume'|'clear'|'resetToIdle'
 *                            |'setPlaybackRate'|'seek'|'isPlaying'|'ping', args: [...] }
 * Host page -> extension:
 *   { signora: 'ready' }                       once window.signsure is calibrated
 *   { signora: 'ack', id, value }              result of a command
 *   { signora: 'event', name: 'finished' }     playback drained (SignoraPlayer.onFinished)
 *   { signora: 'event', name: 'sign', gloss, occurrenceIndex }
 */

import { AvatarAdapter } from './adapter.js'
import { log, warn } from '../config.js'

const READY_TIMEOUT_MS = 60000

export class UnityIframeAvatarAdapter extends AvatarAdapter {
  constructor({ hostUrl, mount, onState = null }) {
    super()
    this.hostUrl = hostUrl
    this.mount = mount
    this.onState = onState

    this.frame = null
    this.origin = null
    this.ready = false
    this.readyPromise = null
    this.nextId = 1
    this.pending = new Map()

    // Mirrored locally because `isPlaying()` is called synchronously every scheduler tick and
    // cannot wait for a round trip across the frame.
    this.playing = false
    this.paused = false
    this.rate = 1
    this.activeGloss = null

    this.onMessage = this.onMessage.bind(this)
  }

  /** Create the iframe and resolve once the host page reports a calibrated avatar. */
  async loadPlan(plan) {
    this.plan = plan
    if (this.readyPromise) return this.readyPromise

    try {
      this.origin = new URL(this.hostUrl).origin
    } catch {
      throw new Error(`Invalid unityHostUrl: ${this.hostUrl}`)
    }

    const frame = document.createElement('iframe')
    frame.src = this.hostUrl
    frame.title = 'Signora avatar'
    frame.allow = 'autoplay'
    frame.setAttribute('aria-label', 'Signora signing avatar')
    Object.assign(frame.style, {
      width: '100%', height: '100%', border: '0', display: 'block', background: '#000',
    })
    this.frame = frame

    window.addEventListener('message', this.onMessage)
    this.readyPromise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(
          'The Unity avatar host page did not report readiness. Confirm it is served at '
          + `${this.hostUrl} and that the WebGL build exists.`,
        ))
      }, READY_TIMEOUT_MS)
      this.resolveReady = () => { clearTimeout(timer); this.ready = true; resolve(this) }
      this.rejectReady = (error) => { clearTimeout(timer); reject(error) }
    })

    this.mount.appendChild(frame)
    return this.readyPromise
  }

  onMessage(event) {
    if (event.origin !== this.origin || !event.data || event.data.signora === undefined) return
    const data = event.data

    if (data.signora === 'ready') {
      log('unity host ready')
      this.resolveReady?.()
      return
    }
    if (data.signora === 'ack') {
      const entry = this.pending.get(data.id)
      if (entry) {
        this.pending.delete(data.id)
        entry.resolve(data.value)
      }
      return
    }
    if (data.signora === 'event') {
      if (data.name === 'finished') {
        this.playing = false
        this.activeGloss = null
        this.#emit('finished')
      } else if (data.name === 'sign') {
        this.activeGloss = data.gloss ?? null
        this.#emit('sign')
      }
    }
  }

  #emit(reason) {
    this.onState?.({
      reason,
      playing: this.playing,
      paused: this.paused,
      rate: this.rate,
      activeGloss: this.activeGloss,
      // Unity is authoritative about progress; the overlay shows the gloss instead of a bar.
      progress: null,
      durationMs: null,
      elapsedMs: null,
      glosses: [],
    })
  }

  #send(method, args = [], { expectAck = false } = {}) {
    if (!this.frame?.contentWindow) {
      warn('unity frame is not mounted; dropping', method)
      return expectAck ? Promise.resolve(undefined) : undefined
    }
    const id = this.nextId
    this.nextId += 1
    const message = { signora: 'cmd', id, method, args }
    if (!expectAck) {
      this.frame.contentWindow.postMessage(message, this.origin)
      return undefined
    }
    return new Promise((resolve) => {
      this.pending.set(id, { resolve })
      this.frame.contentWindow.postMessage(message, this.origin)
      setTimeout(() => {
        if (this.pending.delete(id)) resolve(undefined)
      }, 2000)
    })
  }

  play(motion) {
    this.playing = true
    this.paused = false
    this.activeGloss = null
    this.#send('play', [motion])
    this.#emit('play')
  }

  pause() {
    if (!this.playing || this.paused) return
    this.paused = true
    this.#send('pause')
    this.#emit('pause')
  }

  resume() {
    if (!this.playing || !this.paused) return
    this.paused = false
    this.#send('resume')
    this.#emit('resume')
  }

  seek(relativeMs) {
    this.#send('seek', [Number(relativeMs) || 0])
  }

  setPlaybackRate(rate) {
    const value = Number(rate)
    if (!Number.isFinite(value)) return
    this.rate = value
    this.#send('setPlaybackRate', [value])
    this.#emit('rate')
  }

  clear() {
    this.playing = false
    this.paused = false
    this.activeGloss = null
    this.#send('clear')
    this.#emit('clear')
  }

  resetToIdle() {
    this.playing = false
    this.paused = false
    this.activeGloss = null
    this.#send('resetToIdle')
    this.#emit('clear')
  }

  /**
   * Synchronous by necessity. The authoritative transition to false arrives as the host page's
   * `finished` event, which `SignoraPlayer.onFinished` already fires when its queue drains.
   */
  isPlaying() {
    return this.playing
  }

  snapshot() {
    return {
      playing: this.playing,
      paused: this.paused,
      rate: this.rate,
      activeGloss: this.activeGloss,
      progress: null,
      durationMs: null,
      elapsedMs: null,
      glosses: [],
    }
  }

  destroy() {
    window.removeEventListener('message', this.onMessage)
    this.frame?.remove()
    this.frame = null
  }
}
