"""Map reconstructed source bone orientations onto the avatar's Humanoid rig.

Produces, per frame, a local rotation for every driven Unity bone - which is all the Unity runtime
needs. The core operation is a world-space delta:

    D_b(t) = (orientation the source bone has at time t) . (orientation the avatar's bone has at rest)^-1
    G_b(t) = D_b(t) . restGlobal_b                     # where the avatar's bone should now point
    L_b(t) = (D_anc(t) . restGlobal_parentTransform)^-1 . G_b(t)

The last line deserves a note. A bone's local rotation must be relative to its *actual* Transform
parent, which on a real rig is often an undriven bone (Chest, UpperChest, a helper node) sitting
between two bones we do drive. An undriven bone just carries its nearest driven ancestor's delta,
so its runtime global rotation is `D_anc(t) . restGlobal_itself` - which is what the formula uses.
That keeps the pipeline correct on rigs with extra spine joints without needing to drive them.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation

from . import skeleton as sk
from .reconstruct import BoneMotion, orthonormal_basis
from .rigprofile import RigProfile


def _shortest_arc(a: np.ndarray, b: np.ndarray) -> Rotation:
    """Rotations taking each unit vector in `a` to the matching one in `b`.

    `a` may be a single (3,) vector or an (N, 3) array; `b` is (N, 3).
    """
    a = np.asarray(a, dtype=np.float64)
    if a.ndim == 1:
        a = np.broadcast_to(a, b.shape)

    axis = np.cross(a, b)
    dot = np.clip(np.sum(a * b, axis=-1), -1.0, 1.0)
    axis_len = np.linalg.norm(axis, axis=-1)

    quat = np.empty((len(b), 4), dtype=np.float64)
    quat[:, :3] = axis
    quat[:, 3] = 1.0 + dot

    # Antiparallel: the rotation is 180 degrees about *any* perpendicular axis, so pick one
    # deterministically rather than letting the degenerate quaternion normalise to noise.
    flipped = (axis_len < 1e-8) & (dot < 0)
    if np.any(flipped):
        ref = np.where(
            np.abs(a[:, 0:1]) < 0.9, np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
        )
        perp = np.cross(a, ref)
        perp /= np.linalg.norm(perp, axis=-1, keepdims=True)
        quat[flipped, :3] = perp[flipped]
        quat[flipped, 3] = 0.0

    quat /= np.linalg.norm(quat, axis=-1, keepdims=True)
    return Rotation.from_quat(quat)


def _axis_angle(axis: np.ndarray, angle: np.ndarray) -> Rotation:
    return Rotation.from_rotvec(axis * angle[:, None])


def compute_deltas(
    motion: dict[str, BoneMotion],
    rig: RigProfile,
    twist_offsets: dict[str, float] | None = None,
) -> dict[str, Rotation]:
    """World-space delta rotation per driven Unity bone, per frame.

    Swing is measured against the bone's rest direction *carried by its parent's current rotation*,
    not against the avatar's static rest pose. This matters: a finger that points down at rest and up
    at the forehead is a ~180 degree world-space arc, and shortest-arc rotations are numerically
    undefined near 180 degrees - the roll component swings wildly frame to frame and visibly spins
    the bone. Measured against the parent, the same motion is just the joint's actual flexion, which
    is small and stable, and roll is inherited from the parent the way anatomy does it.

    Bones whose full orientation is observable from geometry ("frame") skip this entirely and are
    matched basis to basis. `skeleton.BONES` is ordered parents-first so each parent's delta is ready
    before its children need it.
    """
    twist_offsets = twist_offsets or {}
    deltas: dict[str, Rotation] = {}

    for bone in sk.BONES:
        bm = motion[bone.name]
        if bm.axis is None:
            continue  # terminal bones are handled as local bends, below

        rest_axis = rig.rest_axis(bone.unity)

        if bm.basis is not None:
            # Full orientation is observable on both sides: compare bases directly.
            rest_basis = orthonormal_basis(
                rest_axis[None, :], rig.frame_reference(bone.unity)[None, :]
            )[0]
            delta = Rotation.from_matrix(bm.basis @ rest_basis.T)
        else:
            ancestor = rig.nearest_driven_ancestor(bone.unity)
            parent = deltas.get(ancestor) if ancestor else None

            if parent is None:
                delta = _shortest_arc(rest_axis, bm.axis)
            else:
                # Where the bone would point if it only followed its parent, then the small
                # correction that lands it on the direction actually observed.
                predicted = parent.apply(rest_axis)
                delta = _shortest_arc(predicted, bm.axis) * parent

            if bm.roll is not None:
                offset = twist_offsets.get(bone.unity, 0.0)
                delta = _axis_angle(bm.axis, bm.roll + offset) * delta

        deltas[bone.unity] = delta

    return deltas


def to_local_rotations(
    motion: dict[str, BoneMotion],
    rig: RigProfile,
    twist_offsets: dict[str, float] | None = None,
) -> dict[str, Rotation]:
    """Local rotation per driven Unity bone, per frame - the values Unity writes to the transforms."""
    deltas = compute_deltas(motion, rig, twist_offsets)
    frames = len(next(iter(deltas.values())))
    identity = Rotation.identity(frames)
    locals_: dict[str, Rotation] = {}

    for bone in sk.BONES:
        rb = rig.bones[bone.unity]
        bm = motion[bone.name]

        if bm.axis is None:
            # Terminal bone: keep the avatar's rest local rotation and add the measured bend.
            rest_local = rb.rest_parent_rotation.inv() * rb.rest_rotation
            if bm.bend is not None:
                axis = np.tile(
                    np.asarray(sk.TERMINAL_BEND_AXIS.get(bone.unity, (1.0, 0.0, 0.0))), (frames, 1)
                )
                locals_[bone.unity] = rest_local * _axis_angle(axis, bm.bend)
            else:
                locals_[bone.unity] = Rotation.concatenate([rest_local] * frames)
            continue

        ancestor = rig.nearest_driven_ancestor(bone.unity)
        d_anc = deltas.get(ancestor, identity) if ancestor else identity

        parent_global = d_anc * rb.rest_parent_rotation
        global_ = deltas[bone.unity] * rb.rest_rotation
        locals_[bone.unity] = parent_global.inv() * global_

    return locals_


def hip_track(motion_positions: np.ndarray, rig: RigProfile, source_hip_height: float) -> np.ndarray:
    """Hip translation in avatar units: scaled by height ratio, relative to the take's first frame."""
    scale = rig.hip_height / source_hip_height if source_hip_height > 1e-6 else 1.0
    return (motion_positions - motion_positions[0]) * scale
