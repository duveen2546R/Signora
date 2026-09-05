import assert from 'node:assert/strict'
import test from 'node:test'
import { blendNotices, playableTrack } from './blendQuality.js'

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
  for (const status of ['rejected', 'neutral-fallback', 'degraded']) {
    assert.equal(playableTrack({ ...ready(), blendQuality: { status } }), null)
  }
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
test('rejected pairs and missing signs produce actionable notices', () => {
  const notices = blendNotices({ blendQuality: { status: 'rejected', seams: [
    { mode: 'rejected', fromGloss: 'HELLO', toGloss: 'FATHER', passed: false },
  ] }, issues: [{ message: 'Record D.' }], warnings: ['Check capture.'] })
  assert.match(notices[0], /Playback blocked.*HELLO → FATHER/)
  assert.ok(notices.includes('Record D.'))
})
