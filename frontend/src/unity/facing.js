/**
 * Turns a landmark frame so the performer faces the same way as in the calibration pose.
 *
 * Recordings where the performer turned their body make the avatar turn too, and the runtime
 * retargets every bone relative to the calibration pose. Rotating the whole frame - pose and both
 * hands, about one pivot - around the calibration pose's vertical axis removes only that turn:
 * leaning, arm, hand and head motion relative to the shoulders are unchanged.
 */

const L_SHOULDER = 11
const R_SHOULDER = 12
const L_HIP = 23
const R_HIP = 24

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s]
const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2]

function unit(v) {
  const length = Math.hypot(v[0], v[1], v[2])
  return length > 1e-9 ? scale(v, 1 / length) : null
}

/** Shoulder line flattened onto the plane perpendicular to `up`, or null if degenerate. */
function flatShoulders(pose, up) {
  const across = sub(pose[R_SHOULDER], pose[L_SHOULDER])
  return unit(sub(across, scale(up, dot(across, up))))
}

/** The fixed reference a recording is turned towards; null if the pose cannot define one. */
export function facingReference(calibrationPose) {
  if (!Array.isArray(calibrationPose) || calibrationPose.length < 25) return null
  const up = unit(sub(
    mid(calibrationPose[L_SHOULDER], calibrationPose[R_SHOULDER]),
    mid(calibrationPose[L_HIP], calibrationPose[R_HIP]),
  ))
  if (!up) return null
  const shoulders = flatShoulders(calibrationPose, up)
  return shoulders ? { up, shoulders } : null
}

/** Rodrigues rotation of `point` by `angle` around the unit axis through `pivot`. */
function rotate(point, pivot, axis, cos, sin) {
  const v = sub(point, pivot)
  const k = cross(axis, v)
  const along = dot(axis, v) * (1 - cos)
  return [
    pivot[0] + v[0] * cos + k[0] * sin + axis[0] * along,
    pivot[1] + v[1] * cos + k[1] * sin + axis[1] * along,
    pivot[2] + v[2] * cos + k[2] * sin + axis[2] * along,
  ]
}

/**
 * Returns `{pose, leftHand, rightHand}` turned to face like the reference. Frames that are already
 * aligned, or that cannot define a facing, are returned unchanged.
 */
export function faceForward(reference, pose, leftHand, rightHand) {
  if (!reference || !Array.isArray(pose) || pose.length < 25) return { pose, leftHand, rightHand }
  const shoulders = flatShoulders(pose, reference.up)
  if (!shoulders) return { pose, leftHand, rightHand }
  const sin = dot(cross(shoulders, reference.shoulders), reference.up)
  const cos = dot(shoulders, reference.shoulders)
  if (Math.abs(sin) < 1e-6 && cos > 0) return { pose, leftHand, rightHand }
  const angle = Math.atan2(sin, cos)
  const c = Math.cos(angle)
  const s = Math.sin(angle)
  const pivot = mid(pose[L_HIP], pose[R_HIP])
  const turn = (points) => points.map((point) => rotate(point, pivot, reference.up, c, s))
  return { pose: turn(pose), leftHand: turn(leftHand), rightHand: turn(rightHand) }
}
