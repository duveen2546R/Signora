import assert from 'node:assert/strict'
import test from 'node:test'
import { MockAvatarAdapter } from '../src/avatar/adapter.js'

/** 2 s of motion at 60 fps, with two named sign segments. */
function motion({ frameCount = 120, fps = 60 } = {}) {
  return {
    fps,
    frameCount,
    segments: [
      { kind: 'hold', gloss: '', startFrame: 0, endFrame: 10 },
      { kind: 'sign', gloss: 'HELLO', startFrame: 10, endFrame: 60, occurrenceIndex: 0 },
      { kind: 'transition', gloss: 'FATHER', startFrame: 60, endFrame: 70 },
      { kind: 'sign', gloss: 'FATHER', startFrame: 70, endFrame: 115, occurrenceIndex: 1 },
    ],
  }
}

function clock() {
  const state = { t: 0 }
  return { now: () => state.t, advance: (ms) => { state.t += ms }, state }
}

test('derives duration from the composed motion frameCount and fps', () => {
  const c = clock()
  const avatar = new MockAvatarAdapter({ now: c.now })
  avatar.play(motion({ frameCount: 450, fps: 60 }))
  assert.equal(avatar.durationMs, 7500)
})

test('rejects motion without a usable frameCount/fps rather than guessing', () => {
  const avatar = new MockAvatarAdapter()
  assert.throws(() => avatar.play({ fps: 60 }), /frameCount\/fps/)
  assert.throws(() => avatar.play({ fps: 0, frameCount: 10 }), /frameCount\/fps/)
})

test('isPlaying stays true for the motion duration and then goes false', () => {
  const c = clock()
  const avatar = new MockAvatarAdapter({ now: c.now })
  avatar.play(motion())              // 2000 ms
  assert.equal(avatar.isPlaying(), true)
  c.advance(1999)
  assert.equal(avatar.isPlaying(), true)
  c.advance(2)
  assert.equal(avatar.isPlaying(), false, 'motion must retire so the scheduler can advance')
})

test('pause freezes progress and resume continues from the same point', () => {
  const c = clock()
  const avatar = new MockAvatarAdapter({ now: c.now })
  avatar.play(motion())
  c.advance(500)
  avatar.pause()
  const frozen = avatar.snapshot().elapsedMs
  c.advance(10_000)
  assert.equal(avatar.isPlaying(), true, 'a paused avatar has not finished')
  assert.equal(avatar.snapshot().elapsedMs, frozen, 'no progress while paused')
  avatar.resume()
  c.advance(1500)
  assert.equal(avatar.isPlaying(), false)
})

test('playback rate scales how fast the motion is consumed', () => {
  const c = clock()
  const avatar = new MockAvatarAdapter({ now: c.now })
  avatar.play(motion())              // 2000 ms at 1x
  avatar.setPlaybackRate(2)
  c.advance(1000)                    // 1000 ms wall == 2000 ms motion
  assert.equal(avatar.isPlaying(), false, 'at 2x a 2 s sign finishes in 1 s')
})

test('a mid-sign rate change does not re-time the part already performed', () => {
  const c = clock()
  const avatar = new MockAvatarAdapter({ now: c.now })
  avatar.play(motion())
  c.advance(1000)                    // half of it at 1x
  avatar.setPlaybackRate(2)
  assert.equal(avatar.snapshot().elapsedMs, 1000)
  c.advance(500)                     // 500 ms wall at 2x == the remaining 1000 ms
  assert.equal(avatar.isPlaying(), false)
})

test('rate is clamped to a sane range', () => {
  const avatar = new MockAvatarAdapter()
  avatar.play(motion())
  avatar.setPlaybackRate(99)
  assert.equal(avatar.snapshot().rate, 4)
  avatar.setPlaybackRate(0.01)
  assert.equal(avatar.snapshot().rate, 0.25)
  avatar.setPlaybackRate(Number.NaN)
  assert.equal(avatar.snapshot().rate, 0.25, 'a non-finite rate is ignored')
})

test('reports the active sign gloss as the motion progresses', () => {
  const c = clock()
  const avatar = new MockAvatarAdapter({ now: c.now })
  avatar.play(motion())
  c.advance(500)                     // frame 30 -> inside HELLO (10..60)
  avatar.isPlaying()
  assert.equal(avatar.snapshot().activeGloss, 'HELLO')
  c.advance(1000)                    // frame 90 -> inside FATHER (70..115)
  avatar.isPlaying()
  assert.equal(avatar.snapshot().activeGloss, 'FATHER')
})

test('lists only sign segments as glosses, in order, keeping repeats', () => {
  const avatar = new MockAvatarAdapter()
  avatar.play({
    fps: 60,
    frameCount: 180,
    segments: [
      { kind: 'sign', gloss: 'AGAIN', startFrame: 0, endFrame: 60, occurrenceIndex: 0 },
      { kind: 'transition', gloss: 'AGAIN', startFrame: 60, endFrame: 70 },
      { kind: 'sign', gloss: 'AGAIN', startFrame: 70, endFrame: 130, occurrenceIndex: 1 },
    ],
  })
  assert.deepEqual(avatar.snapshot().glosses, ['AGAIN', 'AGAIN'])
})

test('seek moves within the motion and clamps to its bounds', () => {
  const c = clock()
  const avatar = new MockAvatarAdapter({ now: c.now })
  avatar.play(motion())
  avatar.seek(1500)
  assert.equal(avatar.snapshot().elapsedMs, 1500)
  avatar.seek(99_999)
  assert.equal(avatar.snapshot().elapsedMs, 2000)
  avatar.seek(-50)
  assert.equal(avatar.snapshot().elapsedMs, 0)
})

test('clear and resetToIdle stop playback', () => {
  const avatar = new MockAvatarAdapter()
  avatar.play(motion())
  avatar.clear()
  assert.equal(avatar.isPlaying(), false)
  avatar.play(motion())
  avatar.resetToIdle()
  assert.equal(avatar.isPlaying(), false)
  assert.equal(avatar.snapshot().activeGloss, null)
})

test('emits a finished state exactly once when motion completes', () => {
  const c = clock()
  const reasons = []
  const avatar = new MockAvatarAdapter({ now: c.now, onState: (s) => reasons.push(s.reason) })
  avatar.play(motion())
  c.advance(2500)
  avatar.isPlaying()
  avatar.isPlaying()
  assert.equal(reasons.filter((r) => r === 'finished').length, 1)
})

test('progress runs from 0 to 1', () => {
  const c = clock()
  const avatar = new MockAvatarAdapter({ now: c.now })
  avatar.play(motion())
  assert.equal(avatar.snapshot().progress, 0)
  c.advance(1000)
  avatar.isPlaying()
  assert.ok(Math.abs(avatar.snapshot().progress - 0.5) < 0.01)
  c.advance(1000)
  avatar.isPlaying()
  assert.equal(avatar.snapshot().progress, 1)
})
