"""Frame-invariant 3D joint angles shared verbatim by FBX and triangulated video."""

from __future__ import annotations

import numpy as np

from .fbx_motion import CASE_JOINTS
from .mixed_effects import ValidationError

# (proximal, vertex, distal) joints. Flexion is 0 deg with a straight limb, so the value is the
# rotation of the distal segment away from the proximal segment's line, in any coordinate frame.
ANGLES = {
    "left_elbow_flexion": ("left_shoulder", "left_elbow", "left_wrist"),
    "right_elbow_flexion": ("right_shoulder", "right_elbow", "right_wrist"),
}


def flexion(proximal: np.ndarray, vertex: np.ndarray, distal: np.ndarray) -> np.ndarray:
    """Degrees between proximal->vertex and vertex->distal; NaN where a segment collapses."""
    upper = vertex - proximal
    lower = distal - vertex
    norms = np.linalg.norm(upper, axis=-1) * np.linalg.norm(lower, axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        cosine = np.einsum("...i,...i->...", upper, lower) / norms
    cosine = np.where(norms > 1e-9, np.clip(cosine, -1.0, 1.0), np.nan)
    return np.degrees(np.arccos(cosine))


def joint_angles(
    xyz: np.ndarray, joints: tuple[str, ...] = CASE_JOINTS, names: tuple[str, ...] | None = None
) -> dict[str, np.ndarray]:
    """Angle traces for (frames, joints, 3) positions in any right- or left-handed frame."""
    index = {name: position for position, name in enumerate(joints)}
    selected = names or tuple(ANGLES)
    result = {}
    for name in selected:
        try:
            a, b, c = (index[joint] for joint in ANGLES[name])
        except KeyError as exc:
            raise ValidationError(f"{name}: joint {exc} is not tracked.") from exc
        result[name] = flexion(xyz[:, a], xyz[:, b], xyz[:, c])
    return result
