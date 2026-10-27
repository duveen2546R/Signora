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
export const FACE_BLENDSHAPE_COUNT = 52
export const ARKIT_BLENDSHAPES = [
  'browDownLeft', 'browDownRight', 'browInnerUp', 'browOuterUpLeft', 'browOuterUpRight',
  'cheekPuff', 'cheekSquintLeft', 'cheekSquintRight', 'eyeBlinkLeft', 'eyeBlinkRight',
  'eyeLookDownLeft', 'eyeLookDownRight', 'eyeLookInLeft', 'eyeLookInRight', 'eyeLookOutLeft',
  'eyeLookOutRight', 'eyeLookUpLeft', 'eyeLookUpRight', 'eyeSquintLeft', 'eyeSquintRight',
  'eyeWideLeft', 'eyeWideRight', 'jawForward', 'jawLeft', 'jawOpen', 'jawRight', 'mouthClose',
  'mouthDimpleLeft', 'mouthDimpleRight', 'mouthFrownLeft', 'mouthFrownRight', 'mouthFunnel',
  'mouthLeft', 'mouthLowerDownLeft', 'mouthLowerDownRight', 'mouthPressLeft', 'mouthPressRight',
  'mouthPucker', 'mouthRight', 'mouthRollLower', 'mouthRollUpper', 'mouthShrugLower',
  'mouthShrugUpper', 'mouthSmileLeft', 'mouthSmileRight', 'mouthStretchLeft',
  'mouthStretchRight', 'mouthUpperUpLeft', 'mouthUpperUpRight', 'noseSneerLeft',
  'noseSneerRight', 'tongueOut',
]

// FBX supplies expression coefficients, while head orientation continues to come from pose
// landmarks. Unity still requires a 16-float face transform, so identity is the correct transform.
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

export function buildFrame({
  sequence, timeMs, pose, leftHand, rightHand, faceBlendshapeNames = [], faceBlendshapes = null,
  state = 'playing', signMarker = -1,
}) {
  const hasFace = Array.isArray(faceBlendshapes) && faceBlendshapes.length === FACE_BLENDSHAPE_COUNT
    && faceBlendshapeNames.length === FACE_BLENDSHAPE_COUNT
  return JSON.stringify({
    schemaVersion: SCHEMA_VERSION,
    sequence,
    signMarker,
    captureTimeMs: timeMs,
    inferenceEndTimeMs: timeMs,
    source: 'rokoko-fbx',
    state,
    pose: { present: true, confidence: CONFIDENCE, landmarks: landmarks(pose) },
    leftHand: {
      present: true, confidence: CONFIDENCE, handedness: 'Left', landmarks: landmarks(leftHand),
    },
    rightHand: {
      present: true, confidence: CONFIDENCE, handedness: 'Right', landmarks: landmarks(rightHand),
    },
    face: {
      present: hasFace,
      confidence: hasFace ? CONFIDENCE : 0,
      transform: IDENTITY_4X4,
      blendshapes: hasFace
        ? faceBlendshapeNames.map((name, index) => ({ name, score: faceBlendshapes[index] }))
        : [],
    },
  })
}

/** Validates a landmark payload before we start streaming it, so failures name themselves. */
export function assertPayloadShape(payload) {
  const problems = []
  if (!payload || !Array.isArray(payload.pose)) problems.push('missing pose track')
  const counts = ['pose', 'leftHand', 'rightHand'].map((k) => payload?.[k]?.length)
  if (new Set(counts).size > 1) {
    problems.push(`tracks disagree on length: pose ${counts[0]}, left ${counts[1]}, right ${counts[2]}`)
  }
  if (payload?.frameCount !== undefined && payload.frameCount !== counts[0]) {
    problems.push(`frameCount ${payload.frameCount} does not match ${counts[0]} frames`)
  }
  if (!Number.isFinite(payload?.fps) || !(payload.fps > 0)) problems.push(`invalid fps ${payload?.fps}`)
  if (payload?.pose?.[0]?.length !== POSE_LANDMARK_COUNT) {
    problems.push(`pose has ${payload?.pose?.[0]?.length} landmarks, expected ${POSE_LANDMARK_COUNT}`)
  }
  for (const side of ['leftHand', 'rightHand']) {
    if (payload?.[side]?.[0]?.length !== HAND_LANDMARK_COUNT) {
      problems.push(`${side} has ${payload?.[side]?.[0]?.length} landmarks, expected ${HAND_LANDMARK_COUNT}`)
    }
  }
  const face = payload?.faceBlendshapes
  const faceNames = payload?.faceBlendshapeNames
  if (face !== undefined || faceNames !== undefined) {
    if (!Array.isArray(faceNames) || faceNames.length !== FACE_BLENDSHAPE_COUNT
        || faceNames.some((name, index) => name !== ARKIT_BLENDSHAPES[index])) {
      problems.push(`faceBlendshapeNames must use the canonical ${FACE_BLENDSHAPE_COUNT}-channel ARKit order`)
    }
    if (!Array.isArray(face) || face.length !== counts[0] || face.some((frame) =>
      !Array.isArray(frame) || frame.length !== FACE_BLENDSHAPE_COUNT
      || frame.some((value) => !Number.isFinite(value) || value < 0 || value > 1))) {
      problems.push(`faceBlendshapes must contain ${counts[0]} frames of ${FACE_BLENDSHAPE_COUNT} normalized scores`)
    }
  }
  if (!Number.isInteger(payload?.frameCount) || payload.frameCount < 1) problems.push('invalid frameCount')
  for (const [channel, count] of [['pose', 33], ['leftHand', 21], ['rightHand', 21]]) {
    if (!Array.isArray(payload?.[channel]) || payload[channel].some((frame) =>
      !Array.isArray(frame) || frame.length !== count || frame.some((point) =>
        !Array.isArray(point) || point.length !== 3 || point.some((value) => !Number.isFinite(value))))) {
      problems.push(`${channel} contains invalid frames or coordinates`)
    }
  }
  if (payload?.segments) {
    let cursor = 0
    for (const segment of payload.segments) {
      if (!Number.isInteger(segment.startFrame) || !Number.isInteger(segment.endFrame)
          || segment.startFrame !== cursor || segment.endFrame <= segment.startFrame) problems.push('invalid segment coverage')
      cursor = segment.endFrame
    }
    if (cursor !== payload.frameCount) problems.push('segments do not cover the full track')
  }
  if (problems.length) throw new Error(`Landmark payload is unusable: ${problems.join('; ')}`)
}
