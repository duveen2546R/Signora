"""Convert a Rokoko take into the landmark frames the Signora Unity runtime already consumes.

The Unity project in `SignoraAvatarTracking/` does its own retargeting: `WebGLTrackingReceiver`
accepts a `CanonicalTrackingFrameV1` carrying MediaPipe-style landmarks (33 pose points, 21 per
hand) and `BodyRetargeter`/`HandRetargeter` turn those into bone rotations against a calibration
reference. Emitting that format means the existing WebGL build drives the avatar with no Unity
changes at all.

The mapping is direct because both sides are 3D points: Rokoko's biomechanics export gives exact
joint centres, and MediaPipe landmarks are joint centres too. Only the fingertips have to be
synthesised - Rokoko's chain ends at the distal joint, while MediaPipe carries a tip point.

Coordinates are passed through in the source frame (metres, Y-up, left-handed), recentred on the hip
midpoint. The retargeters are calibration-relative - they only ever use normalised directions and
bases - so the origin is irrelevant, but the *handedness* is not: the source frame was verified to
match Unity's, so deltas computed here apply correctly to the avatar in world space.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .reconstruct import normalize
from .rokoko import Take

SCHEMA_VERSION = 1
POSE_LANDMARK_COUNT = 33
HAND_LANDMARK_COUNT = 21

# MediaPipe Pose indices this pipeline can source from the suit. The retargeters require
# 11-16 and 23-24; the rest are filled so the frame passes structural validation and the
# head retargeter has something to work with.
POSE_FROM_SEGMENT: dict[int, str] = {
    11: "LeftUpperArm",   12: "RightUpperArm",    # shoulders
    13: "LeftForeArm",    14: "RightForeArm",     # elbows
    15: "LeftHand",       16: "RightHand",        # wrists
    17: "LeftDigit5ProximalPhalangx",  18: "RightDigit5ProximalPhalangx",   # pinky knuckles
    19: "LeftDigit2ProximalPhalangx",  20: "RightDigit2ProximalPhalangx",   # index knuckles
    21: "LeftDigit1ProximalPhalangx",  22: "RightDigit1ProximalPhalangx",   # thumbs
    23: "LeftUpperLeg",   24: "RightUpperLeg",    # hips
    25: "LeftLowerLeg",   26: "RightLowerLeg",    # knees
    27: "LeftFoot",       28: "RightFoot",        # ankles
}

# Head landmarks are synthesised from the head position and the body's own axes, offset in metres
# as (forward, right, up). The suit carries no face capture, so these are anatomically plausible
# rather than measured - enough for the head retargeter's pose fallback, which is direction-based.
HEAD_OFFSETS: dict[int, tuple[float, float, float]] = {
    0:  (0.105, 0.000, -0.010),   # nose
    1:  (0.085, 0.015, 0.030),    # left eye inner
    2:  (0.085, 0.030, 0.030),    # left eye
    3:  (0.085, 0.045, 0.030),    # left eye outer
    4:  (0.085, -0.015, 0.030),   # right eye inner
    5:  (0.085, -0.030, 0.030),   # right eye
    6:  (0.085, -0.045, 0.030),   # right eye outer
    7:  (0.005, 0.075, 0.015),    # left ear
    8:  (0.005, -0.075, 0.015),   # right ear
    9:  (0.090, 0.025, -0.045),   # mouth left
    10: (0.090, -0.025, -0.045),  # mouth right
}

# Feet: (heel, foot index) offset along the body's backward/forward axis, in metres.
FOOT_OFFSETS: dict[int, tuple[str, float]] = {
    29: ("LeftFoot", -0.06), 30: ("RightFoot", -0.06),   # heels
    31: ("LeftFoot", 0.14),  32: ("RightFoot", 0.14),    # toes
}

# MediaPipe hand landmark -> the Rokoko digit segment at the same joint.
# Rokoko positions are each segment's proximal end, so ProximalPhalangx sits at the knuckle.
_FINGER_SEGMENTS = {
    "Thumb":  (1, "Digit1", ["MetaCarpal", "ProximalPhalangx", "DistalPhalanx"]),
    "Index":  (5, "Digit2", ["ProximalPhalangx", "IntermediatePhalanx", "DistalPhalanx"]),
    "Middle": (9, "Digit3", ["ProximalPhalangx", "IntermediatePhalanx", "DistalPhalanx"]),
    "Ring":   (13, "Digit4", ["ProximalPhalangx", "IntermediatePhalanx", "DistalPhalanx"]),
    "Pinky":  (17, "Digit5", ["ProximalPhalangx", "IntermediatePhalanx", "DistalPhalanx"]),
}

# Terminal joint whose flexion bends the fingertip away from the previous segment.
_TIP_FLEXION = {
    "Thumb": "Digit1Interphalangeal",
    "Index": "Digit2DistalInterphalangeal",
    "Middle": "Digit3DistalInterphalangeal",
    "Ring": "Digit4DistalInterphalangeal",
    "Pinky": "Digit5DistalInterphalangeal",
}

TIP_LENGTH_RATIO = 0.75


@dataclass(frozen=True)
class LandmarkTake:
    """Landmark tracks for one recording, ready to stream at `fps`."""

    name: str
    fps: float
    pose: np.ndarray        # (F, 33, 3)
    left_hand: np.ndarray   # (F, 21, 3)
    right_hand: np.ndarray  # (F, 21, 3)

    @property
    def frame_count(self) -> int:
        return len(self.pose)

    @property
    def duration(self) -> float:
        return self.frame_count / self.fps if self.fps else 0.0

    def to_payload(self, decimals: int = 4) -> dict:
        """Compact JSON for the browser, which assembles the per-frame Unity messages."""
        return {
            "name": self.name,
            "fps": self.fps,
            "frameCount": self.frame_count,
            "pose": np.round(self.pose, decimals).tolist(),
            "leftHand": np.round(self.left_hand, decimals).tolist(),
            "rightHand": np.round(self.right_hand, decimals).tolist(),
        }


def _body_axes(take: Take) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-frame right/up/forward unit axes of the torso, in the source frame."""
    right = normalize(take.pos("RightUpperArm") - take.pos("LeftUpperArm"))
    up = normalize(take.pos("Chest") - take.pos("Pelvis"))
    forward = normalize(np.cross(right, up))
    # Re-orthogonalise up against the two we trust most.
    up = normalize(np.cross(forward, right))
    return right, up, forward


def _rotate_about(vectors: np.ndarray, axis: np.ndarray, angle: np.ndarray) -> np.ndarray:
    """Rodrigues rotation of each row of `vectors` about the matching row of `axis`."""
    cos = np.cos(angle)[:, None]
    sin = np.sin(angle)[:, None]
    dot = np.sum(axis * vectors, axis=-1, keepdims=True)
    return vectors * cos + np.cross(axis, vectors) * sin + axis * dot * (1.0 - cos)


def _fingertip(
    take: Take, side: str, finger: str, near: np.ndarray, far: np.ndarray
) -> np.ndarray:
    """Extrapolate the tip beyond the distal joint, bent by the terminal joint's flexion.

    Rokoko's chain stops at the distal joint but MediaPipe carries a tip, and the Unity hand
    retargeter drives each finger's last bone from the distal-to-tip direction. Extrapolating
    straight would leave that bone permanently uncurled, so the measured flexion is applied about
    the finger's own bend axis - recovered from the curl it already has, which is exactly the axis
    the joint rotates about.
    """
    segment = far - near
    length = np.linalg.norm(segment, axis=1, keepdims=True) * TIP_LENGTH_RATIO
    direction = normalize(segment)

    angle = np.deg2rad(take.angles[f"{side}{_TIP_FLEXION[finger]}_flexion"])

    # The finger's existing curl gives its true flexion axis, with the correct sign.
    previous = far - near
    base = take.pos(f"{side}{_FINGER_SEGMENTS[finger][1]}{_FINGER_SEGMENTS[finger][2][0]}")
    curl = np.cross(near - base, previous)
    magnitude = np.linalg.norm(curl, axis=1, keepdims=True)

    # Nearly straight fingers give a degenerate axis; fall back to the knuckle line, which is what
    # the flexion axis approximates anyway.
    knuckle = np.cross(
        direction,
        normalize(
            take.pos(f"{side}Digit5ProximalPhalangx") - take.pos(f"{side}Digit2ProximalPhalangx")
        ),
    )
    axis = normalize(np.where(magnitude > 1e-7, curl, np.cross(knuckle, direction)))

    return far + _rotate_about(direction, axis, angle) * length


def hand_landmarks(take: Take, side: str) -> np.ndarray:
    """(F, 21, 3) MediaPipe hand landmarks for one side."""
    frames = take.frame_count
    out = np.zeros((frames, HAND_LANDMARK_COUNT, 3), dtype=np.float64)
    out[:, 0] = take.pos(f"{side}Hand")   # wrist

    for finger, (base_index, digit, parts) in _FINGER_SEGMENTS.items():
        points = [take.pos(f"{side}{digit}{part}") for part in parts]
        for offset, point in enumerate(points):
            out[:, base_index + offset] = point
        out[:, base_index + 3] = _fingertip(take, side, finger, points[-2], points[-1])

    return out


def pose_landmarks(take: Take) -> np.ndarray:
    """(F, 33, 3) MediaPipe pose landmarks."""
    frames = take.frame_count
    out = np.zeros((frames, POSE_LANDMARK_COUNT, 3), dtype=np.float64)

    for index, segment in POSE_FROM_SEGMENT.items():
        out[:, index] = take.pos(segment)

    right, up, forward = _body_axes(take)
    head = take.pos("Head")
    for index, (f, r, u) in HEAD_OFFSETS.items():
        out[:, index] = head + forward * f + right * r + up * u

    for index, (segment, along) in FOOT_OFFSETS.items():
        out[:, index] = take.pos(segment) + forward * along

    return out


def to_landmarks(take: Take) -> LandmarkTake:
    """Convert a parsed take into landmark tracks, recentred on the hip midpoint."""
    pose = pose_landmarks(take)
    left = hand_landmarks(take, "Left")
    right = hand_landmarks(take, "Right")

    origin = ((take.pos("LeftUpperLeg") + take.pos("RightUpperLeg")) / 2.0)[:, None, :]

    return LandmarkTake(
        name=take.name,
        fps=round(take.source_fps),
        pose=pose - origin,
        left_hand=left - origin,
        right_hand=right - origin,
    )
