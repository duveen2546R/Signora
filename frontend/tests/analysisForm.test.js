import test from 'node:test'
import assert from 'node:assert/strict'
import { buildAnalysisOptions } from '../src/analysisForm.js'

function input() {
  return {
    files: { suit: { name: 'capture.fbx', size: 200 }, non_suit: { name: 'old.FBX', size: 200 }, video: { name: 'action.mp4', size: 300 } },
    action: ' Wave ', pairing: true, relationship: 'same_performance',
    windows: Object.fromEntries(['suit', 'non_suit', 'video'].map((key) => [key, { start: '', end: '' }])),
    calibration: { start: '0', end: '15' }, verifiedTiming: false, timing: {},
  }
}

test('full clip comparison leaves source clocks unverified and calibration provisional', () => {
  const result = buildAnalysisOptions(input())
  assert.deepEqual(result, { action: 'Wave', pairing_confirmed: true, recording_relationship: 'same_performance', reference_view: 'automatic', windows: {}, calibration_phase: [0, 0.15], synchronization: {} })
})

test('separate repetitions preserve their relationship and cannot claim synchronized accuracy', () => {
  const values = input()
  values.relationship = 'separate_repetitions'
  assert.equal(buildAnalysisOptions(values).recording_relationship, 'separate_repetitions')
  values.verifiedTiming = true
  assert.throws(() => buildAnalysisOptions(values), /exact same performance/)
  delete values.relationship
  values.verifiedTiming = false
  assert.equal(buildAnalysisOptions(values).recording_relationship, 'unknown')
})

test('uploads, pairing, partial windows and invalid calibration are rejected', () => {
  for (const change of [
    (i) => { i.files.suit = null },
    (i) => { i.files.video.name = 'data.csv' },
    (i) => { i.files.video.size = 251 * 1024 * 1024 },
    (i) => { i.pairing = false },
    (i) => { i.windows.video.start = '2' },
    (i) => { i.windows.suit = { start: '3', end: '2' } },
    (i) => { i.calibration.end = '101' },
  ]) {
    const values = input(); change(values)
    assert.throws(() => buildAnalysisOptions(values))
  }
})

test('documented event offsets and playback rate reach the analysis unchanged', () => {
  const values = input()
  values.windows.video = { start: '0.63', end: '5.38' }
  values.verifiedTiming = true
  values.timing = Object.fromEntries(['suit', 'non_suit'].map((key) => [key, {
    video: '1', fbx: '0.5', rate: '2', description: 'First movement', evidence: 'Capture metadata', rateEvidence: 'Video exported at half speed',
  }]))
  const result = buildAnalysisOptions(values)
  assert.deepEqual(result.windows.video, [0.63, 5.38])
  assert.equal(result.synchronization.suit.event.fbx_seconds, 0.5)
  assert.equal(result.synchronization.suit.video_seconds_per_fbx_second, 2)
  values.timing.suit.rateEvidence = ''
  assert.throws(() => buildAnalysisOptions(values), /documented/)
})

test('declared frontal reference is passed to backend and invalid views are rejected', () => {
  const values = input()
  values.referenceView = 'front'
  assert.equal(buildAnalysisOptions(values).reference_view, 'front')
  values.referenceView = 'sideways'
  assert.throws(() => buildAnalysisOptions(values), /camera view/)
})
