/**
 * Builds the JSON that `WebGLTrackingReceiver.ReceiveFrame` expects.
 *
 * The shape is fixed by CanonicalTrackingFrameV1 in the Unity project and validated on arrival:
 * exactly 33 pose landmarks, exactly 21 per hand, a 16-float face transform, a schema version of 1,
 * and a sequence number strictly greater than the last accepted one. Anything else is counted as a
 * rejected frame and dropped, so this module is the single place that shape is written down.
 */

export const SCHEMA_VERSION = 1
export const POSE_LANDMARK_COUNT = 33
export const HAND_LANDMARK_COUNT = 21

// The suit carries no face capture. The transform still has to be 16 floats or the frame is
// rejected outright, so send identity and mark the channel absent; HeadRetargeter then falls back
// to its pose-derived rotation.
const IDENTITY_4X4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]

// Mocap, not inference: every point is exact. Must clear the runtime's 0.45 minimum.
const CONFIDENCE = 1

function landmarks(points) {
  const out = new Array(points.length)
  for (let i = 0; i < points.length; i += 1) {
    const p = points[i]
    out[i] = { x: p[0], y: p[1], z: p[2], confidence: CONFIDENCE }
  }
  return out
}

export function buildFrame({ sequence, timeMs, pose, leftHand, rightHand, state = 'playing' }) {
  return JSON.stringify({
    schemaVersion: SCHEMA_VERSION,
    sequence,
    captureTimeMs: timeMs,
    inferenceEndTimeMs: timeMs,
    source: 'rokoko',
    state,
    pose: { present: true, confidence: CONFIDENCE, landmarks: landmarks(pose) },
    leftHand: {
      present: true, confidence: CONFIDENCE, handedness: 'Left', landmarks: landmarks(leftHand),
    },
    rightHand: {
      present: true, confidence: CONFIDENCE, handedness: 'Right', landmarks: landmarks(rightHand),
    },
    face: { present: false, confidence: 0, transform: IDENTITY_4X4, blendshapes: [] },
  })
}

/** Validates a landmark payload before we start streaming it, so failures name themselves. */
export function assertPayloadShape(payload) {
  const problems = []
  if (!payload || !Array.isArray(payload.pose)) problems.push('missing pose track')
  if (payload?.pose?.[0]?.length !== POSE_LANDMARK_COUNT) {
    problems.push(`pose has ${payload?.pose?.[0]?.length} landmarks, expected ${POSE_LANDMARK_COUNT}`)
  }
  for (const side of ['leftHand', 'rightHand']) {
    if (payload?.[side]?.[0]?.length !== HAND_LANDMARK_COUNT) {
      problems.push(`${side} has ${payload?.[side]?.[0]?.length} landmarks, expected ${HAND_LANDMARK_COUNT}`)
    }
  }
  if (problems.length) throw new Error(`Landmark payload is unusable: ${problems.join('; ')}`)
}
