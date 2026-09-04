import { assertPayloadShape, buildFrame } from './canonicalFrame.js'

const RUNTIME_OBJECT = 'SignoraTrackingRuntime'

// The driver blends a channel back to its bind pose once frames are older than 0.2s, so the stream
// must never pause - when nothing is playing we keep resending the last pose.
const KEEPALIVE = true

// The runtime reports 'failed-body' when it could not sample enough frames; retry rather than
// leaving the avatar frozen in its bind pose.
const MAX_CALIBRATION_ATTEMPTS = 5
const RETRY_DELAY_MS = 700
const CALIBRATION_SUCCESS_STATES = new Set(['complete', 'partial-hand', 'body-only'])

/**
 * Streams landmark frames to the Signora Unity runtime.
 *
 * The runtime retargets in-engine from a calibration reference, so the contract is: send a steady
 * stream of frames, hold a single reference pose while it calibrates, then play. Sequence numbers
 * increase monotonically for the life of the page - the runtime rejects anything that goes
 * backwards, and it never resets except on reload.
 */
export default class SignoraPlayer {
  constructor(sendMessage) {
    this.send = sendMessage
    this.sequence = 0
    this.track = null
    this.segments = []
    this.segmentIndex = -1
    this.idlePose = null
    this.lastPose = null
    this.frameIndex = 0
    this.startedAt = 0
    this.raf = null
    this.calibrated = false
    this.awaitingResult = false
    this.attempts = 0
    this.retryTimer = null
    this.visibilityBound = false
    this.calibrationPose = null
    this.onSignStart = null
    this.onFinished = null
    this.onCalibrated = null
    this.onCalibrationFailed = null
  }

  /** A single pose held during calibration; becomes the avatar's zero. */
  setCalibrationPose(payload) {
    assertPayloadShape(payload)
    this.calibrationPose = {
      pose: payload.pose[0], leftHand: payload.leftHand[0], rightHand: payload.rightHand[0],
    }
  }

  /**
   * Start calibration and keep at it until the runtime reports success.
   *
   * The driver measures its 2s window against wall-clock time but only samples on frames it
   * renders, so anything that stalls rendering - a backgrounded tab, a slow first paint - makes it
   * calibrate from a starved sample set and fail every binding. Rather than guess at that from
   * `document.hidden`, which lies in embedded panes, this reacts to the result the runtime actually
   * reports back and tries again.
   */
  calibrate() {
    if (!this.calibrationPose) throw new Error('No calibration pose has been set.')
    if (this.retryTimer !== null) clearTimeout(this.retryTimer)
    this.retryTimer = null
    this.calibrated = false
    this.attempts = 0
    this.#watchVisibility()
    this.#beginCalibration()
  }

  #beginCalibration() {
    this.attempts += 1
    this.awaitingResult = true
    this.send(RUNTIME_OBJECT, 'BeginCalibration')
    this.#ensureLoop()
  }

  /** Wired to the runtime's SignoraCalibrationState callback. */
  handleCalibrationState(state) {
    if (!this.awaitingResult) return

    // BeginCalibration reports this synchronously. It is a progress event, not a successful
    // result. Treating it as success lets queued motion replace the bind pose during Unity's
    // calibration window, after which the avatar either calibrates against a moving sign or never
    // leaves calibration at all.
    if (state === 'calibrating') return

    this.awaitingResult = false

    if (CALIBRATION_SUCCESS_STATES.has(state)) {
      this.calibrated = true
      this.onCalibrated?.(state)
      return
    }

    if (state !== 'failed-body') {
      this.onCalibrationFailed?.(`Unity reported an unknown calibration state: ${state}`)
      return
    }

    if (this.attempts >= MAX_CALIBRATION_ATTEMPTS) {
      this.onCalibrationFailed?.(
        `Calibration failed after ${this.attempts} attempts. The avatar view must be visible and ` +
        'rendering for the runtime to sample enough frames.',
      )
      return
    }
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null
      this.#beginCalibration()
    }, RETRY_DELAY_MS)
  }

  #watchVisibility() {
    if (this.visibilityBound) return
    this.visibilityBound = true
    this.onVisibilityChange = () => {
      // Coming back into view is the moment a starved calibration can finally succeed.
      if (!document.hidden && !this.calibrated && !this.awaitingResult) {
        this.attempts = 0
        this.#beginCalibration()
      }
    }
    document.addEventListener('visibilitychange', this.onVisibilityChange)
  }

  /**
   * Play a composed sentence - one continuous track, not a queue of clips.
   *
   * The backend already stitched the signs together and generated the movement between them, so
   * there is nothing to schedule here and, more importantly, no boundary at which the stream could
   * pause. Segments only say which sign is on screen.
   */
  play(payload) {
    assertPayloadShape(payload)
    if (!this.calibrated) {
      throw new Error('Avatar calibration must complete before playback starts.')
    }
    this.track = payload
    this.segments = payload.segments ?? []
    this.segmentIndex = -1
    this.startedAt = performance.now()
    this.frameIndex = 0
    if (payload.neutral) this.setIdlePose(payload.neutral)
    this.#ensureLoop()
  }

  /** Where the avatar rests between sentences, in the performer's proportions. */
  setIdlePose(frame) {
    this.idlePose = {
      pose: frame.pose, leftHand: frame.leftHand, rightHand: frame.rightHand,
    }
  }

  clear() {
    this.track = null
    this.segments = []
    this.segmentIndex = -1
  }

  stop() {
    this.clear()
    if (this.retryTimer !== null) clearTimeout(this.retryTimer)
    this.retryTimer = null
    if (this.raf !== null) cancelAnimationFrame(this.raf)
    this.raf = null
    if (this.onVisibilityChange) {
      document.removeEventListener('visibilitychange', this.onVisibilityChange)
      this.visibilityBound = false
    }
  }

  #ensureLoop() {
    if (this.raf === null) this.raf = requestAnimationFrame(this.#tick)
  }

  #emit(pose, leftHand, rightHand, state) {
    this.sequence += 1
    const now = performance.now()
    this.send(RUNTIME_OBJECT, 'ReceiveFrame', buildFrame({
      sequence: this.sequence, timeMs: now, pose, leftHand, rightHand, state,
    }))
  }

  /** Linear blend between the two frames bracketing a time, so playback is not quantised to rAF. */
  #sample(time) {
    const { pose, leftHand, rightHand, frameCount, fps } = this.track
    const exact = Math.max(time * fps, 0)
    const i = Math.min(Math.floor(exact), frameCount - 1)
    const j = Math.min(i + 1, frameCount - 1)
    const f = exact - i

    // Neighbouring frames are 1/60s apart, so this cannot meaningfully bend the skeleton the way
    // interpolating between two *different* signs would; the composed track already did that work.
    const mix = (a, b) => (f <= 0 || i === j ? a : a.map((p, k) => [
      p[0] + (b[k][0] - p[0]) * f,
      p[1] + (b[k][1] - p[1]) * f,
      p[2] + (b[k][2] - p[2]) * f,
    ]))

    return {
      index: i,
      pose: mix(pose[i], pose[j]),
      leftHand: mix(leftHand[i], leftHand[j]),
      rightHand: mix(rightHand[i], rightHand[j]),
    }
  }

  #announce(index) {
    const at = this.segments.findIndex((s) => index >= s.startFrame && index < s.endFrame)
    if (at === this.segmentIndex) return
    this.segmentIndex = at
    const segment = this.segments[at]
    if (segment?.kind === 'sign') this.onSignStart?.(segment.gloss)
  }

  #tick = () => {
    this.raf = requestAnimationFrame(this.#tick)
    const now = performance.now()

    // Hold the reference pose steady until the runtime confirms it calibrated on it.
    if (!this.calibrated) {
      const { pose, leftHand, rightHand } = this.calibrationPose
      this.#emit(pose, leftHand, rightHand, 'calibrating')
      return
    }

    if (this.track) {
      const elapsed = (now - this.startedAt) / 1000
      if (elapsed * this.track.fps < this.track.frameCount) {
        const frame = this.#sample(elapsed)
        this.frameIndex = frame.index
        this.#announce(frame.index)
        this.lastPose = frame
        this.#emit(frame.pose, frame.leftHand, frame.rightHand, 'playing')
        return
      }
      this.track = null
      this.segments = []
      this.segmentIndex = -1
      this.onFinished?.()
    }

    if (!KEEPALIVE) return

    // Nothing playing. Hold the pose the avatar actually reached - resending the calibration pose
    // here would snap it back to the avatar's T-pose the moment a sentence ended.
    const resting = this.lastPose ?? this.idlePose ?? this.calibrationPose
    this.#emit(resting.pose, resting.leftHand, resting.rightHand, 'idle')
  }
}
