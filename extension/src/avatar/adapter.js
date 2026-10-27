/**
 * The avatar contract, and a mock implementation that is honest about what it does.
 *
 * `AvatarAdapter` is the only surface the scheduler and orchestrator touch, so replacing the
 * mock with the Unity WebGL runtime is a constructor swap and nothing else.
 *
 * The scheduler's correctness depends on exactly one thing from an adapter: `isPlaying()` must
 * become false when - and not before - the composed motion has actually finished. That is what
 * drives the catch-up pause and the resume afterwards. So `MockAvatarAdapter` does not guess a
 * duration or use a fixed timeout: it reads `frameCount / fps` off the real motion payload the
 * backend composed, and advances against wall-clock time scaled by the current playback rate.
 * Every timing-sensitive behaviour the task asks for is therefore exercised without Unity.
 */

/* eslint-disable no-unused-vars */

/** Interface documentation. Subclasses must implement every method. */
export class AvatarAdapter {
  /** Called once with the backend's plan, before any playback. */
  async loadPlan(plan) { throw new Error('not implemented') }
  /** Begin playing one composed motion payload (a video-plan unit's motion). */
  play(motion) { throw new Error('not implemented') }
  /** Freeze playback, keeping position. */
  pause() { throw new Error('not implemented') }
  /** Continue from a pause. */
  resume() { throw new Error('not implemented') }
  /** Jump within the current motion, in milliseconds relative to its own start. */
  seek(relativeMs) { throw new Error('not implemented') }
  /** Match the video's playback speed. */
  setPlaybackRate(rate) { throw new Error('not implemented') }
  /** Drop current motion and return to a neutral resting state. */
  clear() { throw new Error('not implemented') }
  /** True while composed motion is still being performed. */
  isPlaying() { throw new Error('not implemented') }
}

const MIN_RATE = 0.25
const MAX_RATE = 4

/** Read the segment list the backend emits so the overlay can name the sign on screen. */
function signSegments(motion) {
  const segments = Array.isArray(motion?.segments) ? motion.segments : []
  return segments
    .filter((segment) => segment && segment.kind === 'sign' && segment.gloss)
    .map((segment) => ({
      gloss: String(segment.gloss),
      startFrame: Number(segment.startFrame) || 0,
      endFrame: Number(segment.endFrame) || 0,
      occurrenceIndex: Number.isFinite(segment.occurrenceIndex) ? segment.occurrenceIndex : null,
    }))
    .sort((a, b) => a.startFrame - b.startFrame)
}

/**
 * A visible, frame-accurate stand-in for the Unity avatar.
 *
 * It renders nothing itself; it reports state through `onState` and the overlay draws it. That
 * keeps the adapter free of DOM assumptions and unit testable with an injected clock.
 */
export class MockAvatarAdapter extends AvatarAdapter {
  constructor({ onState = null, now = () => Date.now() } = {}) {
    super()
    this.onState = onState
    this.now = now
    this.plan = null

    this.motion = null
    this.durationMs = 0
    this.segments = []
    this.fps = 60

    this.elapsedMs = 0
    this.rate = 1
    this.mediaRate = 1
    this.motionRate = 1
    this.playing = false
    this.paused = false
    this.lastTickAt = 0
    this.activeGloss = null
  }

  async loadPlan(plan) {
    this.plan = plan
    this.clear()
  }

  /** Fold wall-clock progress into `elapsedMs`, and retire the motion once it is complete. */
  #advance() {
    if (!this.playing) return
    const at = this.now()
    if (!this.paused) {
      const delta = Math.max(0, at - this.lastTickAt)
      this.elapsedMs += delta * this.rate
    }
    this.lastTickAt = at

    if (this.elapsedMs >= this.durationMs) {
      this.elapsedMs = this.durationMs
      this.playing = false
      this.activeGloss = null
      this.#emit('finished')
      return
    }
    const frame = (this.elapsedMs / 1000) * this.fps
    const current = this.segments.find((s) => frame >= s.startFrame && frame < s.endFrame) || null
    const gloss = current ? current.gloss : null
    if (gloss !== this.activeGloss) {
      this.activeGloss = gloss
      this.#emit('sign')
    }
  }

  #emit(reason) {
    this.onState?.({
      reason,
      playing: this.playing,
      paused: this.paused,
      rate: this.rate,
      elapsedMs: Math.round(this.elapsedMs),
      durationMs: Math.round(this.durationMs),
      progress: this.durationMs > 0 ? Math.min(1, this.elapsedMs / this.durationMs) : 0,
      activeGloss: this.activeGloss,
      glosses: this.segments.map((s) => s.gloss),
    })
  }

  play(motion) {
    const fps = Number(motion?.fps)
    const frames = Number(motion?.frameCount)
    if (!Number.isFinite(fps) || fps <= 0 || !Number.isFinite(frames) || frames <= 0) {
      throw new Error('Composed motion is missing a usable frameCount/fps.')
    }
    this.motion = motion
    this.fps = fps
    this.durationMs = (frames / fps) * 1000
    const targetMs = Number(motion?.playbackTiming?.targetDurationMs)
    this.motionRate = Number.isFinite(targetMs) && targetMs > 0
      ? Math.min(Math.max(this.durationMs / Math.max(targetMs, 250), MIN_RATE), MAX_RATE)
      : 1
    this.rate = Math.min(Math.max(this.motionRate * this.mediaRate, MIN_RATE), MAX_RATE)
    this.segments = signSegments(motion)
    this.elapsedMs = 0
    this.playing = true
    this.paused = false
    this.lastTickAt = this.now()
    this.activeGloss = null
    this.#emit('play')
  }

  pause() {
    if (!this.playing || this.paused) return
    this.#advance()
    this.paused = true
    this.#emit('pause')
  }

  resume() {
    if (!this.playing || !this.paused) return
    this.paused = false
    this.lastTickAt = this.now()
    this.#emit('resume')
  }

  seek(relativeMs) {
    if (!this.playing) return
    this.elapsedMs = Math.min(Math.max(0, Number(relativeMs) || 0), this.durationMs)
    this.lastTickAt = this.now()
    this.#emit('seek')
  }

  setPlaybackRate(rate) {
    const value = Number(rate)
    if (!Number.isFinite(value)) return
    // Settle progress at the old rate before switching, so a mid-sign speed change does not
    // retroactively re-time the part already performed.
    this.#advance()
    this.mediaRate = Math.min(Math.max(value, MIN_RATE), MAX_RATE)
    this.rate = Math.min(Math.max(this.motionRate * this.mediaRate, MIN_RATE), MAX_RATE)
    this.#emit('rate')
  }

  clear() {
    this.motion = null
    this.segments = []
    this.durationMs = 0
    this.elapsedMs = 0
    this.playing = false
    this.paused = false
    this.activeGloss = null
    this.#emit('clear')
  }

  /** Also the scheduler's `resetToIdle` hook. */
  resetToIdle() {
    this.clear()
  }

  isPlaying() {
    this.#advance()
    return this.playing
  }

  /** Current UI state without mutating the clock, for overlay repaints. */
  snapshot() {
    return {
      playing: this.playing,
      paused: this.paused,
      rate: this.rate,
      elapsedMs: Math.round(this.elapsedMs),
      durationMs: Math.round(this.durationMs),
      progress: this.durationMs > 0 ? Math.min(1, this.elapsedMs / this.durationMs) : 0,
      activeGloss: this.activeGloss,
      glosses: this.segments.map((s) => s.gloss),
    }
  }
}
