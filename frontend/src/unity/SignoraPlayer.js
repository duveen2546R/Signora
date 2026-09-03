import { assertPayloadShape, buildFrame } from './canonicalFrame.js'

const RUNTIME_OBJECT = 'SignoraTrackingRuntime'

// The driver blends a channel back to its bind pose once frames are older than 0.2s, so the stream
// must never pause mid-sentence - between signs we keep resending the current pose.
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
    this.queue = []
    this.current = null
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
    this.onQueueEmpty = null
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

  enqueue(payload, gloss) {
    assertPayloadShape(payload)
    this.queue.push({ payload, gloss })
    this.#ensureLoop()
  }

  clear() {
    this.queue = []
    this.current = null
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

  #tick = () => {
    this.raf = requestAnimationFrame(this.#tick)
    const now = performance.now()

    // Hold the reference pose steady until the runtime confirms it calibrated on it.
    if (!this.calibrated) {
      const { pose, leftHand, rightHand } = this.calibrationPose
      this.#emit(pose, leftHand, rightHand, 'calibrating')
      return
    }

    if (!this.current) {
      const next = this.queue.shift()
      if (next) {
        this.current = next
        this.startedAt = now
        this.frameIndex = 0
        this.onSignStart?.(next.gloss)
      } else if (KEEPALIVE) {
        // Nothing to play: keep the last pose alive so the avatar holds instead of snapping back.
        const { pose, leftHand, rightHand } = this.calibrationPose
        this.#emit(pose, leftHand, rightHand, 'idle')
        return
      } else {
        return
      }
    }

    const { payload, gloss } = this.current
    const index = Math.floor(((now - this.startedAt) / 1000) * payload.fps)

    if (index >= payload.frameCount) {
      this.current = null
      if (this.queue.length === 0) this.onQueueEmpty?.(gloss)
      return
    }

    this.frameIndex = index
    this.#emit(payload.pose[index], payload.leftHand[index], payload.rightHand[index], 'playing')
  }
}
