import assert from 'node:assert/strict'
import test from 'node:test'
import {
  finishedEvent,
  handleCommand,
  isTrustedMessageEvent,
  readyEvent,
  resolveParentOrigin,
  signEvent,
} from '../src/unity/avatarHostBridge.js'

function fakeSignsure(overrides = {}) {
  return {
    play: (track) => ({ played: track }),
    pause: () => 'paused',
    resume: () => 'resumed',
    clear: () => 'cleared',
    resetToIdle: () => 'idle',
    isPlaying: () => true,
    isCalibrated: () => true,
    ...overrides,
  }
}

test('ignores anything that is not a signora command message', () => {
  assert.equal(handleCommand(null, fakeSignsure()), null)
  assert.equal(handleCommand({}, fakeSignsure()), null)
  assert.equal(handleCommand({ signora: 'ready' }, fakeSignsure()), null)
})

test('dispatches a known method and returns its value as an ack', () => {
  const reply = handleCommand(
    { signora: 'cmd', id: 7, method: 'play', args: [{ fps: 60, frameCount: 60 }] },
    fakeSignsure(),
  )
  assert.deepEqual(reply, { signora: 'ack', id: 7, value: { played: { fps: 60, frameCount: 60 } } })
})

test('dispatches zero-arg methods correctly', () => {
  const reply = handleCommand({ signora: 'cmd', id: 1, method: 'isCalibrated', args: [] }, fakeSignsure())
  assert.deepEqual(reply, { signora: 'ack', id: 1, value: true })
})

for (const method of ['setPlaybackRate', 'seek']) {
  test(`${method} is acknowledged as a harmless no-op - window.signsure has no such method`, () => {
    const reply = handleCommand({ signora: 'cmd', id: 2, method, args: [1.5] }, fakeSignsure())
    assert.deepEqual(reply, { signora: 'ack', id: 2, value: undefined })
  })
}

test('an unrecognised method name is also a safe no-op, never a throw across the frame', () => {
  assert.doesNotThrow(() => {
    const reply = handleCommand({ signora: 'cmd', id: 3, method: 'notAMethod', args: [] }, fakeSignsure())
    assert.deepEqual(reply, { signora: 'ack', id: 3, value: undefined })
  })
})

test('signsure not yet installed (avatar not loaded) is a safe no-op', () => {
  const reply = handleCommand({ signora: 'cmd', id: 4, method: 'play', args: [{}] }, null)
  assert.deepEqual(reply, { signora: 'ack', id: 4, value: undefined })
})

test('a method that throws is caught and reported on the ack rather than crashing the relay', () => {
  const signsure = fakeSignsure({ play: () => { throw new Error('calibration required') } })
  const reply = handleCommand({ signora: 'cmd', id: 5, method: 'play', args: [{}] }, signsure)
  assert.equal(reply.signora, 'ack')
  assert.equal(reply.id, 5)
  assert.equal(reply.value, undefined)
  assert.match(reply.error, /calibration required/)
})

test('event builders match the protocol the extension adapter expects', () => {
  assert.deepEqual(readyEvent(), { signora: 'ready' })
  assert.deepEqual(finishedEvent(), { signora: 'event', name: 'finished' })
  assert.deepEqual(signEvent('HELLO', 2), { signora: 'event', name: 'sign', gloss: 'HELLO', occurrenceIndex: 2 })
})

test('resolveParentOrigin prefers ancestorOrigins when the browser provides it', () => {
  const win = { location: { ancestorOrigins: ['https://www.youtube.com', 'https://example.com'] } }
  assert.equal(resolveParentOrigin(win), 'https://www.youtube.com')
})

test('resolveParentOrigin falls back when ancestorOrigins is unavailable', () => {
  assert.equal(resolveParentOrigin({ location: {} }), 'https://www.youtube.com')
  assert.equal(resolveParentOrigin({ location: { ancestorOrigins: [] } }), 'https://www.youtube.com')
})

test('resolveParentOrigin never throws even on a hostile location object', () => {
  const win = { get location() { throw new Error('blocked') } }
  assert.doesNotThrow(() => resolveParentOrigin(win))
})

test('isTrustedMessageEvent only accepts the resolved origin, never a wildcard', () => {
  assert.equal(isTrustedMessageEvent({ origin: 'https://www.youtube.com' }, 'https://www.youtube.com'), true)
  assert.equal(isTrustedMessageEvent({ origin: 'https://evil.example' }, 'https://www.youtube.com'), false)
  assert.equal(isTrustedMessageEvent(null, 'https://www.youtube.com'), false)
})
