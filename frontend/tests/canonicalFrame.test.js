import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ARKIT_BLENDSHAPES, assertPayloadShape, buildFrame, FACE_BLENDSHAPE_COUNT,
} from '../src/unity/canonicalFrame.js'

const points = (count) => Array.from({ length: count }, () => [0, 0, 0])
const names = ARKIT_BLENDSHAPES

test('facial coefficients are emitted as named Unity blendshapes', () => {
  const scores = Array.from({ length: FACE_BLENDSHAPE_COUNT }, (_, index) => index / 100)
  const frame = JSON.parse(buildFrame({
    sequence: 1, timeMs: 10, pose: points(33), leftHand: points(21), rightHand: points(21),
    faceBlendshapeNames: names, faceBlendshapes: scores,
  }))

  assert.equal(frame.source, 'rokoko-fbx')
  assert.equal(frame.face.present, true)
  assert.deepEqual(frame.face.blendshapes[24], { name: 'jawOpen', score: 0.24 })
})

test('motion payload validation rejects malformed facial animation', () => {
  const payload = {
    fps: 60, frameCount: 1, pose: [points(33)], leftHand: [points(21)], rightHand: [points(21)],
    faceBlendshapeNames: names, faceBlendshapes: [[...Array(51).fill(0)]],
  }
  assert.throws(() => assertPayloadShape(payload), /52 normalized scores/)
})
