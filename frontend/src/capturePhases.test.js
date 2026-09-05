import assert from 'node:assert/strict'
import test from 'node:test'
import { initialPhaseDraft, inspectCaptureDuration, phaseDurations, snapBoundary, snapPhaseDraft, validatePhaseDraft } from './capturePhases.js'

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

test('phase input rounds onto captured rows and may replace the CSV Phase boundaries', () => {
  const track = { timestampsSeconds: [0, 0.133, 0.301, 0.667, 1, 1.333, 1.667, 2], csvPhaseBounds: { signStartSeconds: 0.301, signEndSeconds: 1.667 } }
  const draft = { duration: 2.333, signStart: 0.301, signEnd: 1.667, track }
  assert.equal(validatePhaseDraft(draft), null)
  // An off-grid value is rounded to the nearest captured row rather than refused.
  assert.equal(validatePhaseDraft({ ...draft, signStart: 0.310 }), null)
  assert.equal(snapPhaseDraft({ ...draft, signStart: 0.310 }).signStart, 0.301)
  // Boundaries that disagree with the CSV Phase column are an override, not an error.
  assert.equal(validatePhaseDraft({ ...draft, signStart: 0.667 }), null)
  // Limits are applied to the rounded values, which are the ones that get saved: these two land
  // on the same captured row, so the sign would have no duration at all.
  assert.match(validatePhaseDraft({ ...draft, signStart: 1.6, signEnd: 1.7 }), /start < end/)
})

test('snapping leaves a draft alone when the capture has no timestamps', () => {
  assert.equal(snapBoundary({}, 0.31), 0.31)
})


test('the editor opens on a saved edit, not on the CSV Phase column it replaced', () => {
  // A take reviewed in the studio: the CSV still says 0.2, the saved boundary is 0.433.
  const edited = {
    signStartSeconds: 0.433, signEndSeconds: 2.033, phaseSource: 'authored-ui',
    csvPhaseBounds: { signStartSeconds: 0.2, signEndSeconds: 2.033 },
  }
  assert.deepEqual(initialPhaseDraft(edited), { signStart: 0.433, signEnd: 2.033 })
})

test('a take nobody has reviewed still opens on its CSV Phase boundaries', () => {
  const fresh = { csvPhaseBounds: { signStartSeconds: 0.2, signEndSeconds: 2.033 } }
  assert.deepEqual(initialPhaseDraft(fresh), { signStart: 0.2, signEnd: 2.033 })
})

test('a take with neither opens empty rather than at zero', () => {
  assert.deepEqual(initialPhaseDraft({}), { signStart: '', signEnd: '' })
})
