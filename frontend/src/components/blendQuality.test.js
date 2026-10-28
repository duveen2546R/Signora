import assert from 'node:assert/strict'
import test from 'node:test'
import { blendNotices, playableTrack, seamPlayable } from './blendQuality.js'

function ready() {
  const frame = (n) => Array.from({ length: n }, () => [0, 0, 0])
  const blendQuality = { status: 'direct', seams: [{ mode: 'direct', passed: true }] }
  return { translationStatus: 'ready', blendQuality, track: {
    fps: 60, frameCount: 2, pose: [frame(33), frame(33)], leftHand: [frame(21), frame(21)],
    rightHand: [frame(21), frame(21)], blendQuality,
  } }
}
test('only a complete validated sentence is playable', () => {
  assert.ok(playableTrack(ready()))
  for (const status of ['missing-signs', 'unsupported', undefined]) {
    assert.equal(playableTrack({ ...ready(), translationStatus: status }), null)
  }
  for (const status of ['rejected', 'degraded']) {
    assert.equal(playableTrack({ ...ready(), blendQuality: { status } }), null)
  }
})
test('a validated rest-pose fallback is playable and labelled', () => {
  const result = ready()
  const blendQuality = { status: 'neutral-fallback', seams: [
    { mode: 'direct', passed: true },
    { mode: 'neutral-fallback', passed: true, fromGloss: 'GOOD_MORNING', toGloss: 'FATHER' },
  ] }
  result.blendQuality = blendQuality
  result.track.blendQuality = blendQuality
  assert.ok(playableTrack(result))
  assert.match(blendNotices(result)[0], /GOOD_MORNING → FATHER.*returns to rest/)
  assert.ok(!blendNotices(result).some((notice) => /Playback blocked/.test(notice)))
})
test('a fallback seam that failed its own checks still blocks playback', () => {
  const result = ready()
  const blendQuality = { status: 'neutral-fallback', seams: [{ mode: 'neutral-fallback', passed: false }] }
  result.blendQuality = blendQuality
  result.track.blendQuality = blendQuality
  assert.equal(playableTrack(result), null)
})
test('an explicitly labelled candidate preview is playable', () => {
  assert.ok(playableTrack({ ...ready(), translationStatus: 'preview' }))
})
test('a corrupt later frame blocks playback before streaming', () => {
  const result = ready()
  result.track.pose[1][0][0] = NaN
  assert.equal(playableTrack(result), null)
})
test('failed seam metadata blocks even a claimed direct track', () => {
  const result = ready()
  result.blendQuality.seams[0].passed = false
  assert.equal(playableTrack(result), null)
})
const JERK = 'seam jerk exceeds the adjacent-motion envelope'

test('a reviewed settle is playable and labelled, without claiming it passed', () => {
  const result = ready()
  const blendQuality = { status: 'reviewed-direct', seams: [
    { mode: 'direct', passed: true, fromGloss: '', toGloss: 'THANKYOU' },
    { mode: 'reviewed-direct', passed: false, fromGloss: 'THANKYOU', toGloss: '', waivedChecks: [JERK] },
  ] }
  result.blendQuality = blendQuality
  result.track.blendQuality = blendQuality
  assert.ok(playableTrack(result))
  assert.ok(blendNotices(result).some((notice) => /THANKYOU → rest/.test(notice)))
  assert.ok(!blendNotices(result).some((notice) => /Playback blocked/.test(notice)))
})
test('a settle seam must list what it waived to be playable', () => {
  assert.equal(seamPlayable({ mode: 'reviewed-direct', passed: false, waivedChecks: [JERK] }), true)
  assert.equal(seamPlayable({ mode: 'reviewed-direct', passed: false }), false)
  assert.equal(seamPlayable({ mode: 'rejected', passed: false, waivedChecks: [JERK] }), false)
})
test('a rest pass-through whose leg needed a settle is playable only with its waiver listed', () => {
  const settled = { mode: 'neutral-fallback', passed: false, legModes: ['direct', 'reviewed-direct'] }
  assert.equal(seamPlayable({ ...settled, waivedChecks: [JERK] }), true)
  assert.equal(seamPlayable(settled), false)
  assert.equal(seamPlayable({ mode: 'neutral-fallback', passed: false, waivedChecks: [] }), false)
})
test('rejected pairs and missing signs produce actionable notices', () => {
  const notices = blendNotices({ blendQuality: { status: 'rejected', seams: [
    { mode: 'rejected', fromGloss: 'HELLO', toGloss: 'FATHER', passed: false },
  ] }, issues: [{ message: 'Record D.' }], warnings: ['Check capture.'] })
  assert.match(notices[0], /Playback blocked.*HELLO → FATHER/)
  assert.ok(notices.includes('Record D.'))
})
