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
