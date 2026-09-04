import assert from 'node:assert/strict'
import test from 'node:test'
import { inspectCaptureDuration, phaseDurations, validatePhaseDraft } from './capturePhases.js'

test('capture duration uses the median jittered frame interval', async () => {
  const file = { text: async () => 'Timestamp,X\n1000,0\n1034,0\n1067,0\n1100,0\n' }
  assert.equal(await inspectCaptureDuration(file), 0.133)
})

test('validates reviewed sign boundaries against capture duration', () => {
  const draft = { duration: 4, signStart: '0.8', signEnd: '3.1' }
  assert.equal(validatePhaseDraft(draft), null)
  const durations = phaseDurations(draft)
  assert.equal(durations.start, 0.8)
  assert.equal(durations.sign, 2.3)
  assert.ok(Math.abs(durations.end - 0.9) < 1e-9)
})

test('rejects missing, reversed, and out-of-range boundaries', () => {
  assert.match(validatePhaseDraft({ duration: 4, signStart: '', signEnd: '' }), /both/)
  assert.match(validatePhaseDraft({ duration: 4, signStart: '3', signEnd: '2' }), /start < end/)
  assert.match(validatePhaseDraft({ duration: 4, signStart: '1', signEnd: '5' }), /4\.000/)
})

test('requires usable start, sign, and end sections for seamless fallback', () => {
  assert.match(validatePhaseDraft({ duration: 4, signStart: '0.05', signEnd: '3' }), /0\.120s of Start/)
  assert.match(validatePhaseDraft({ duration: 4, signStart: '1', signEnd: '1.2' }), /0\.300s of Sign/)
  assert.match(validatePhaseDraft({ duration: 4, signStart: '1', signEnd: '3.95' }), /0\.120s of End/)
})
