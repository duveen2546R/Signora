"""Frame-invariant 3D upper-body angles shared verbatim by FBX and triangulated video.

Every angle is the unsigned angle between two body-segment vectors. That makes each one
independent of the coordinate frame, of scale, and of handedness: the FBX is left-handed and the
two-view reconstruction has an arbitrary scale and orientation, with no gravity direction. Signed
anatomical decompositions (e.g. flexion vs. abduction planes) would need a shared, correctly
handed body frame and are deliberately avoided. Head, neck and fingers are not tracked.
"""

from __future__ import annotations

import numpy as np

from .fbx_motion import CASE_JOINTS
from .mixed_effects import ValidationError

# name -> ((from, to), (from, to)): degrees between the two vectors. "mid_shoulder"/"mid_hip" are
# the midpoints of the left/right joints.
ANGLES = {
    # Upper arm vs. forearm: 0 with a straight elbow.
    "left_elbow_flexion": (("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist")),
    "right_elbow_flexion": (("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist")),
    # Upper arm vs. the trunk's downward axis: 0 with the arm hanging, 90 when raised level.
    "left_shoulder_elevation": (("mid_shoulder", "mid_hip"), ("left_shoulder", "left_elbow")),
    "right_shoulder_elevation": (("mid_shoulder", "mid_hip"), ("right_shoulder", "right_elbow")),
    # Upper arm vs. the outward shoulder line: ~90 hanging or pointing forward, 0 when abducted
    # straight out to the side. With elevation it fixes the arm direction up to a front/back mirror.
    "left_shoulder_abduction": (("right_shoulder", "left_shoulder"), ("left_shoulder", "left_elbow")),
    "right_shoulder_abduction": (("left_shoulder", "right_shoulder"), ("right_shoulder", "right_elbow")),
    # Forearm vs. hand (wrist -> index knuckle): combined flexion and deviation.
    "left_wrist_deviation": (("left_elbow", "left_wrist"), ("left_wrist", "left_index")),
    "right_wrist_deviation": (("right_elbow", "right_wrist"), ("right_wrist", "right_index")),
    # Shoulder line vs. hip line: axial trunk rotation.
    "trunk_twist": (("left_shoulder", "right_shoulder"), ("left_hip", "right_hip")),
}
MIDPOINTS = {"mid_shoulder": ("left_shoulder", "right_shoulder"), "mid_hip": ("left_hip", "right_hip")}


def vector_angle(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    """Degrees between two vectors; NaN where either collapses."""
    norms = np.linalg.norm(first, axis=-1) * np.linalg.norm(second, axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cosine = np.einsum("...i,...i->...", first, second) / norms
    cosine = np.where(norms > 1e-9, np.clip(cosine, -1.0, 1.0), np.nan)
    return np.degrees(np.arccos(cosine))


def flexion(proximal: np.ndarray, vertex: np.ndarray, distal: np.ndarray) -> np.ndarray:
    """Degrees between proximal->vertex and vertex->distal; NaN where a segment collapses."""
    return vector_angle(vertex - proximal, distal - vertex)


def joint_angles(
    xyz: np.ndarray, joints: tuple[str, ...] = CASE_JOINTS, names: tuple[str, ...] | None = None
) -> dict[str, np.ndarray]:
    """Angle traces for (frames, joints, 3) positions in any right- or left-handed frame."""
    index = {name: position for position, name in enumerate(joints)}

    def point(name: str) -> np.ndarray:
        if name in MIDPOINTS:
            return (point(MIDPOINTS[name][0]) + point(MIDPOINTS[name][1])) / 2
        return xyz[:, index[name]]

    result = {}
    for name in names or tuple(ANGLES):
        try:
            (a, b), (c, d) = ANGLES[name]
            result[name] = vector_angle(point(b) - point(a), point(d) - point(c))
        except KeyError as exc:
            raise ValidationError(f"{name}: {exc} is not a tracked joint or a defined angle.") from exc
    return result
