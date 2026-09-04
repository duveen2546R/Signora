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

    @classmethod
    def from_payload(cls, payload: dict, name: str | None = None) -> "LandmarkTake":
        return cls(
            name=name or payload.get("name", "clip"),
            fps=float(payload["fps"]),
            pose=np.asarray(payload["pose"], dtype=np.float64),
            left_hand=np.asarray(payload["leftHand"], dtype=np.float64),
            right_hand=np.asarray(payload["rightHand"], dtype=np.float64),
        )

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


# --- Landmark-space skeleton -------------------------------------------------------------------
#
# Blending must not interpolate landmark positions directly. Blending two real takes shortens the
# forearm by up to 28% at the midpoint. Unity reads only normalised directions, so the avatar does
# not visibly stretch - but the joint sweeps a distorted arc at uneven angular velocity, which is
# the artefact blending exists to remove.
#
# What is constrained here is only what was *measured* to be constant across the library, and
# everything else is left free because it is a real degree of freedom:
#
#   hip width              0.00 mm spread   -> constrained
#   wrist -> each knuckle  0.00 mm          -> constrained (five independent spokes)
#   arm and finger bones   0.00 mm          -> constrained
#   head landmarks 0..10   0.07 mm residual -> rigid as a group
#   shoulder width        41.64 mm          -> FREE, this is shoulder-girdle motion
#   palm as a whole       32.48 mm residual -> FREE, the metacarpal arch genuinely flexes

# Articulated chains, rebuilt from blended directions at constant length.
POSE_CHAINS: tuple[tuple[int, ...], ...] = ((11, 13, 15), (12, 14, 16))
HAND_CHAINS: tuple[tuple[int, ...], ...] = (
    (1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20),
)

# Wrist -> metacarpal base. Each spoke has its own constant length; together they are not rigid,
# which is why they are five separate constraints rather than one rigid palm.
PALM_SPOKES: tuple[int, ...] = (1, 5, 9, 13, 17)

HIP_PAIR: tuple[int, int] = (23, 24)          # constant width, symmetric about the origin
POSE_HEAD_GROUP: tuple[int, ...] = tuple(range(0, 11))

# Genuine degrees of freedom, interpolated directly.
POSE_SOFT: tuple[int, ...] = (11, 12)         # shoulder girdle
POSE_FREE: tuple[int, ...] = tuple(range(25, 33))   # legs; drive no Unity binding

# The wrist appears in both arrays and must stay identical, or the palm detaches from the forearm.
WRIST_IN_POSE: dict[str, int] = {"left": 15, "right": 16}

# Six more pose landmarks are the same joints as entries in the hand arrays, so they are derived
# rather than interpolated - otherwise the two arrays can disagree about where a knuckle is.
# Note the thumb: hand index 1 is the metacarpal, so the proximal phalanx the pose array wants is 2.
POSE_FROM_HAND: dict[int, tuple[str, int]] = {
    17: ("left", 17), 18: ("right", 17),    # pinky knuckles
    19: ("left", 5), 20: ("right", 5),      # index knuckles
    21: ("left", 2), 22: ("right", 2),      # thumb proximal phalanx
}


def _pairs(chain: tuple[int, ...]) -> list[tuple[int, int]]:
    return [(chain[i], chain[i + 1]) for i in range(len(chain) - 1)]


POSE_BONES: tuple[tuple[int, int], ...] = tuple(
    pair for chain in POSE_CHAINS for pair in _pairs(chain)
)
HAND_BONES: tuple[tuple[int, int], ...] = tuple(
    pair for chain in HAND_CHAINS for pair in _pairs(chain)
)
HAND_SPOKES: tuple[tuple[int, int], ...] = tuple((0, k) for k in PALM_SPOKES)


@dataclass(frozen=True)
class LandmarkSkeleton:
    """Constant measurements of the performer, taken once from the library.

    Bone lengths are identical across takes (same performer, same suit), so these are properties of
    the library rather than of any single clip.
    """

    head_shape: np.ndarray                      # (11, 3) centroid-relative, rigid
    hip_half_width: float
    pose_lengths: dict[tuple[int, int], float]
    hand_lengths: dict[tuple[int, int], float]  # bones and spokes, shared by both hands

    @classmethod
    def from_takes(cls, takes: "list[LandmarkTake] | LandmarkTake") -> "LandmarkSkeleton":
        if isinstance(takes, LandmarkTake):
            takes = [takes]
        pose = np.concatenate([t.pose for t in takes], axis=0)
        hands = np.concatenate([t.left_hand for t in takes] + [t.right_hand for t in takes], axis=0)

        head = pose[:, POSE_HEAD_GROUP, :]
        head_shape = (head - head.mean(axis=1, keepdims=True)).mean(axis=0)

        def lengths(track: np.ndarray, pairs) -> dict[tuple[int, int], float]:
            return {
                pair: float(np.linalg.norm(track[:, pair[1]] - track[:, pair[0]], axis=1).mean())
                for pair in pairs
            }

        a, b = HIP_PAIR
        return cls(
            head_shape=head_shape,
            hip_half_width=float(np.linalg.norm(pose[:, b] - pose[:, a], axis=1).mean() / 2.0),
            pose_lengths=lengths(pose, POSE_BONES),
            hand_lengths={**lengths(hands, HAND_BONES), **lengths(hands, HAND_SPOKES)},
        )


    def deviation(self, other: "LandmarkSkeleton") -> tuple[float, str]:
        """Largest disagreement between two measured skeletons, in metres, and where."""
        worst, where = abs(self.hip_half_width - other.hip_half_width) * 2, "hip width"
        for label, mine, theirs in (
            ("arm", self.pose_lengths, other.pose_lengths),
            ("hand", self.hand_lengths, other.hand_lengths),
        ):
            for key, length in mine.items():
                gap = abs(length - theirs.get(key, length))
                if gap > worst:
                    worst, where = gap, f"{label} segment {key[0]}->{key[1]}"
        return worst, where


def slice_frames(take: LandmarkTake, start: int, end: int) -> LandmarkTake:
    """Half-open [start, end) slice, preserving name and frame rate."""
    return LandmarkTake(
        name=take.name, fps=take.fps,
        pose=take.pose[start:end],
        left_hand=take.left_hand[start:end],
        right_hand=take.right_hand[start:end],
    )


def concat(takes: list[LandmarkTake], name: str = "sentence") -> LandmarkTake:
    if not takes:
        raise ValueError("nothing to concatenate")
    fps = takes[0].fps
    if any(t.fps != fps for t in takes):
        raise ValueError("cannot concatenate tracks recorded at different frame rates")
    return LandmarkTake(
        name=name, fps=fps,
        pose=np.concatenate([t.pose for t in takes], axis=0),
        left_hand=np.concatenate([t.left_hand for t in takes], axis=0),
        right_hand=np.concatenate([t.right_hand for t in takes], axis=0),
    )
