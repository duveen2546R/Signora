"""Reconstruct world bone orientations from Rokoko joint-center positions.

The biomechanics export has no rotations. What it does have is exact joint centers of a rigid
skeleton, so a bone's *direction* is recoverable exactly:

    axis_i(t) = normalize(tail_i(t) - head_i(t))

A direction leaves one degree of freedom undetermined - roll about the bone's own axis. Each bone
declares in skeleton.py how that roll is recovered:

  "frame"    A second independent axis is observable from geometry (hip spread, shoulder spread,
             metacarpal spread), giving a complete orthonormal basis with no clinical channel
             involved. Used for the hips, spine and both hands - palm orientation is a core
             phonological parameter of a sign, so it is worth taking from geometry.
  "channel"  Roll comes from an anatomical angle channel (degrees).
  "zero"     Roll is negligible and the channel is noisy (finger bones); left at the swing default.

Everything here is expressed in the *source* world frame, which the probe confirmed is already
left-handed Y-up metres - the same convention as Unity. Mapping onto the avatar happens in
retarget.py, which is the only module that needs the rig profile.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import skeleton as sk
from .rokoko import Take

_EPS = 1e-9


def normalize(v: np.ndarray) -> np.ndarray:
    """Row-wise normalise an (N, 3) array; zero-length rows become +Y rather than NaN."""
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    safe = np.where(n < _EPS, 1.0, n)
    out = v / safe
    out[np.broadcast_to(n < _EPS, out.shape)] = 0.0
    out[(n < _EPS)[..., 0]] = np.array([0.0, 1.0, 0.0])
    return out


def orthonormal_basis(primary: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Build (N, 3, 3) bases whose column 0 is `primary`, Gram-Schmidt'd against `reference`.

    Column 0 is the bone axis, column 1 the reference direction made perpendicular to it, and
    column 2 their cross product. Returned as rotation matrices (columns are the basis vectors).
    """
    x = normalize(primary)
    r = normalize(reference)
    # Remove the component of r along x, then renormalise.
    y = r - x * np.sum(r * x, axis=-1, keepdims=True)
    degenerate = np.linalg.norm(y, axis=-1) < 1e-6
    if np.any(degenerate):
        # `reference` is parallel to the bone axis: fall back to any perpendicular axis.
        fallback = np.tile(np.array([0.0, 1.0, 0.0]), (len(x), 1))
        alt = np.tile(np.array([1.0, 0.0, 0.0]), (len(x), 1))
        pick = np.where((np.abs(x[:, 1]) > 0.9)[:, None], alt, fallback)
        y = np.where(degenerate[:, None], pick - x * np.sum(pick * x, axis=-1, keepdims=True), y)
    y = normalize(y)
    z = np.cross(x, y)
    return np.stack([x, y, z], axis=-1)


@dataclass(frozen=True)
class BoneMotion:
    """Per-frame reconstruction for one bone, in the source world frame."""

    name: str
    unity: str
    axis: np.ndarray | None          # (F, 3) unit bone direction; None for terminal bones
    basis: np.ndarray | None         # (F, 3, 3) full orientation, only for twist="frame"
    roll: np.ndarray | None          # (F,) radians about `axis`, only for twist="channel"
    bend: np.ndarray | None          # (F,) radians, terminal bones only
    length: float                    # mean bone length in metres (0.0 for terminal bones)


def reconstruct(take: Take) -> dict[str, BoneMotion]:
    """Reconstruct every bone in skeleton.BONES for every frame of `take`."""
    out: dict[str, BoneMotion] = {}

    for bone in sk.BONES:
        axis = basis = roll = bend = None
        length = 0.0

        if bone.tail is not None:
            head = take.pos(bone.head)
            tail = take.pos(bone.tail)
            delta = tail - head
            length = float(np.linalg.norm(delta, axis=1).mean())
            axis = normalize(delta)

            if bone.twist == "frame":
                reference = take.pos(bone.ref_b) - take.pos(bone.ref_a)
                basis = orthonormal_basis(axis, reference)
            elif bone.twist == "channel":
                roll = np.deg2rad(take.angles[bone.twist_channel])

        if bone.terminal_channel is not None:
            bend = np.deg2rad(take.angles[bone.terminal_channel])

        out[bone.name] = BoneMotion(
            name=bone.name, unity=bone.unity,
            axis=axis, basis=basis, roll=roll, bend=bend, length=length,
        )

    return out


def hand_roll_from_geometry(take: Take, side: str) -> np.ndarray:
    """Roll of the hand about the forearm axis, measured from the metacarpal spread.

    Independent of any clinical channel, so comparing it against `{side}Wrist_pronation` is a real
    check on whether the angle channels mean what we assume. See tools/check_channels.py.
    """
    forearm_axis = normalize(take.pos(f"{side}Hand") - take.pos(f"{side}ForeArm"))
    spread = take.pos(f"{side}Digit5MetaCarpal") - take.pos(f"{side}Digit2MetaCarpal")
    perp = normalize(spread - forearm_axis * np.sum(spread * forearm_axis, axis=-1, keepdims=True))
    # Measure against a reference perpendicular that is stable across frames: world up, projected.
    up = np.tile(np.array([0.0, 1.0, 0.0]), (len(perp), 1))
    ref = normalize(up - forearm_axis * np.sum(up * forearm_axis, axis=-1, keepdims=True))
    cos = np.clip(np.sum(perp * ref, axis=-1), -1.0, 1.0)
    sin = np.sum(np.cross(ref, perp) * forearm_axis, axis=-1)
    return np.arctan2(sin, cos)
