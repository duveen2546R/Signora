import assert from 'node:assert/strict'
import test from 'node:test'
import { faceForward, facingReference } from './facing.js'

// A minimal pose: hips at y=0, shoulders at y=0.5, facing -z, with a raised right wrist.
function pose() {
  const points = Array.from({ length: 33 }, () => [0, 0.3, 0])
  points[11] = [-0.2, 0.5, 0]
  points[12] = [0.2, 0.5, 0]
  points[23] = [-0.1, 0, 0]
  points[24] = [0.1, 0, 0]
  points[16] = [0.3, 0.7, -0.2]
  return points
}

function turnY(points, degrees) {
  const a = degrees * Math.PI / 180
  return points.map(([x, y, z]) => [x * Math.cos(a) + z * Math.sin(a), y, -x * Math.sin(a) + z * Math.cos(a)])
}

const close = (a, b) => a.every((point, i) => point.every((value, k) => Math.abs(value - b[i][k]) < 1e-9))

test('a turned performer is rotated back to face like the calibration pose', () => {
  const reference = facingReference(pose())
  const hand = Array.from({ length: 21 }, (_, i) => [0.3, 0.7 + i * 0.01, -0.2])
  for (const degrees of [30, -75, 150]) {
    const turned = faceForward(reference, turnY(pose(), degrees), turnY(hand, degrees), turnY(hand, degrees))
    assert.ok(close(turned.pose, pose()), `pose after ${degrees} degrees`)
    assert.ok(close(turned.rightHand, hand), `hand after ${degrees} degrees`)
  }
})

test('a frame already facing forward is passed through untouched', () => {
  const frame = pose()
  const hand = Array.from({ length: 21 }, () => [0, 0.5, 0])
  const result = faceForward(facingReference(pose()), frame, hand, hand)
  assert.equal(result.pose, frame)
  assert.equal(result.leftHand, hand)
})

test('leaning is kept; only the turn about the vertical axis is removed', () => {
  const leaning = pose().map(([x, y, z]) => [x, y, z - 0.2 * y])
  const result = faceForward(facingReference(pose()), turnY(leaning, 40), [], [])
  assert.ok(close(result.pose, leaning))
})

test('an unusable reference or frame never throws', () => {
  assert.equal(facingReference([]), null)
  const frame = pose()
  assert.equal(faceForward(null, frame, [], []).pose, frame)
})
