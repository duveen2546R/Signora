import assert from 'node:assert/strict'
import test from 'node:test'

import SignoraPlayer from '../src/unity/SignoraPlayer.js'

function payload() {
  const points = (count) => Array.from({ length: count }, () => [0, 0, 0])
  return {
    fps: 30,
    frameCount: 1,
    pose: [points(33)],
    leftHand: [points(21)],
    rightHand: [points(21)],
  }
}

function withBrowserStubs(run) {
  const previous = {
    document: globalThis.document,
    requestAnimationFrame: globalThis.requestAnimationFrame,
    cancelAnimationFrame: globalThis.cancelAnimationFrame,
  }
  globalThis.document = {
    hidden: false,
    addEventListener() {},
    removeEventListener() {},
  }
  globalThis.requestAnimationFrame = () => 1
  globalThis.cancelAnimationFrame = () => {}
  try {
    run()
  } finally {
    Object.assign(globalThis, previous)
  }
}

test('calibrating progress does not unlock CSV playback', () => {
  withBrowserStubs(() => {
    const messages = []
    const player = new SignoraPlayer((...args) => messages.push(args))
    player.setCalibrationPose(payload())
    player.calibrate()

    player.handleCalibrationState('calibrating')

    assert.equal(player.calibrated, false)
    assert.equal(player.awaitingResult, true)
    assert.deepEqual(messages[0].slice(0, 2), ['SignoraTrackingRuntime', 'BeginCalibration'])
    player.stop()
  })
})

test('only a terminal success state unlocks playback', () => {
  withBrowserStubs(() => {
    const player = new SignoraPlayer(() => {})
    player.setCalibrationPose(payload())
    player.calibrate()

    player.handleCalibrationState('complete')

    assert.equal(player.calibrated, true)
    assert.equal(player.awaitingResult, false)
    player.stop()
  })
})

test('playback cannot start while calibration is in progress', () => {
  withBrowserStubs(() => {
    const player = new SignoraPlayer(() => {})
    player.setCalibrationPose(payload())
    player.calibrate()

    assert.throws(() => player.play(payload()), /calibration must complete/i)
    player.stop()
  })
})

function simulatedBrowser(run) {
  const saved = Object.fromEntries(['performance', 'document', 'requestAnimationFrame', 'cancelAnimationFrame'].map((key) => [key, globalThis[key]]))
  let now = 0
  let callback
  let visibility
  globalThis.performance = { now: () => now }
  globalThis.document = { hidden: false, addEventListener: (_, fn) => { visibility = fn }, removeEventListener: () => {} }
  globalThis.requestAnimationFrame = (fn) => { callback = fn; return 1 }
  globalThis.cancelAnimationFrame = () => {}
  try {
    run({ tick: (ms) => { now = ms; callback() }, hide: (hidden, ms) => { now = ms; document.hidden = hidden; visibility() } })
  } finally { Object.assign(globalThis, saved) }
}
function sentence() {
  const single = payload()
  const repeat = (channel) => Array.from({ length: 60 }, (_, index) => single[channel][0].map(() => [index / 100, 0, 0]))
  return { fps: 30, frameCount: 60, pose: repeat('pose'), leftHand: repeat('leftHand'), rightHand: repeat('rightHand'),
    blendQuality: { status: 'direct' }, segments: [
      { kind: 'sign', gloss: 'HELLO', occurrenceIndex: 0, startFrame: 0, endFrame: 30 },
      { kind: 'sign', gloss: 'HELLO', occurrenceIndex: 1, startFrame: 30, endFrame: 60 },
    ] }
}
test('background time does not skip signing and repeated occurrences announce separately', () => {
  simulatedBrowser(({ tick, hide }) => {
    const messages = []
    const occurrences = []
    const player = new SignoraPlayer((...args) => messages.push(args))
    player.calibrated = true
    player.onSignStart = (gloss, index) => occurrences.push([gloss, index])
    player.play(sentence())
    tick(500)
    assert.equal(player.frameIndex, 15)
    hide(true, 500)
    tick(5500)
    assert.equal(player.frameIndex, 15)
    hide(false, 10500)
    tick(11000)
    assert.equal(player.frameIndex, 30)
    assert.deepEqual(occurrences, [['HELLO', 0], ['HELLO', 1]])
    tick(12500)
    assert.equal(player.track, null)
    assert.equal(player.lastPose.index, 59)
    const sequences = messages.filter((args) => args[1] === 'ReceiveFrame').map((args) => JSON.parse(args[2]).sequence)
    assert.ok(sequences.every((sequence, index) => index === 0 || sequence > sequences[index - 1]))
    player.play(sentence())
    tick(12500)
    assert.equal(player.frameIndex, 0)
    player.stop()
  })
})
test('a rejected track cannot reach the runtime', () => {
  withBrowserStubs(() => {
    const player = new SignoraPlayer(() => { throw new Error('should not emit') })
    player.calibrated = true
    assert.throws(() => player.play({ ...sentence(), blendQuality: { status: 'degraded' } }), /failed transition validation/)
  })
})

test('queued tracks hand off in the same animation frame without finishing early', () => {
  simulatedBrowser(({ tick }) => {
    const messages = []
    let finished = 0
    const player = new SignoraPlayer((...args) => messages.push(args))
    player.calibrated = true
    player.onFinished = () => { finished += 1 }
    const first = sentence()
    const second = sentence()
    for (const frame of second.pose) for (const point of frame) point[0] += 100
    player.enqueue(first, 0)
    player.enqueue(second, 1)
    tick(2000)
    const emitted = JSON.parse(messages.at(-1)[2])
    assert.equal(emitted.pose.landmarks[0].x, 100)
    assert.equal(player.queue.length, 0)
    assert.equal(finished, 0)
    tick(4000)
    assert.equal(finished, 1)
    player.stop()
  })
})

test('queued closures can be cancelled before they start', () => {
  simulatedBrowser(() => {
    const player = new SignoraPlayer(() => {})
    player.calibrated = true
    player.enqueue(sentence(), 0, 'live-motion')
    player.enqueue(sentence(), 1, 'live-closure')
    assert.equal(player.cancelQueued('live-closure'), 1)
    assert.equal(player.queue.length, 0)
    player.stop()
  })
})

test('live speed follows speech timing within the server cap; handoff preserves elapsed time', () => {
  simulatedBrowser(({ tick }) => {
    const player = new SignoraPlayer(() => {})
    player.calibrated = true
    const fast = { ...sentence(), maxPlaybackRate: 1.5, liveTiming: { targetDurationMs: 500 } }
    player.enqueue(fast, 0, 'live-motion')
    player.enqueue(sentence(), 1, 'live-motion')
    assert.equal(player.playbackRate, 1.5)
    tick(500)
    assert.equal(player.frameIndex, 22)
    tick(1500)
    assert.equal(player.currentSequence, 1)
    assert.equal(player.playbackRate, 1)
    assert.equal(player.frameIndex, 5)
    player.stop()
  })
})

test('live pacing cannot accelerate past source cap or accelerate manual previews', () => {
  simulatedBrowser(({ tick, hide }) => {
    const player = new SignoraPlayer(() => {})
    player.calibrated = true
    const limited = { ...sentence(), maxPlaybackRate: 1.2, liveTiming: { targetDurationMs: 100 } }
    player.enqueue(limited, 0, 'live-motion')
    assert.equal(player.playbackRate, 1.2)
    tick(500)
    hide(true, 500)
    const remaining = player.queuedDurationMs()
    tick(5500)
    assert.equal(player.queuedDurationMs(), remaining)
    hide(false, 5500)
    player.play(limited)
    assert.equal(player.playbackRate, 1)
    player.stop()
  })
})
