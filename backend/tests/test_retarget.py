"""Retargeting correctness.

The load-bearing test is `test_identity_retarget`: when the avatar's rest pose is exactly the
performer's pose, retargeting must be a no-op. That exercises the whole chain - rest axes, frame
bases, shortest-arc swing, the driven-ancestor walk and the global-to-local conversion - against a
known answer, without needing a real Unity rig.
"""
import numpy as np
import pytest

from app.ingest import skeleton as sk
from app.ingest.reconstruct import reconstruct
from app.ingest.rigprofile import RigProfileError, from_dict
from app.ingest.retarget import compute_deltas, to_local_rotations

# Unity humanoid bone -> the source segment sitting at the same joint.
#
# Unity's trunk has more joints than Rokoko's (Hips/Spine/Chest/Neck/Head against Pelvis/Chest/Head),
# so the intermediate ones are placed along the Pelvis->Chest line. They only need to be distinct and
# collinear: distinct so each bone has a well-defined rest direction, collinear so the synthetic rig
# still matches the performer's pose and the identity test stays meaningful.
_SPINE_FRACTIONS = {"Spine": 0.34, "Chest": 0.67, "UpperChest": 0.84}

_REST_SOURCE = {
    "Hips": "Pelvis", "Neck": "Chest", "Head": "Head",
}
for _s in ("Left", "Right"):
    _REST_SOURCE.update({
        f"{_s}Shoulder": f"{_s}Shoulder", f"{_s}UpperArm": f"{_s}UpperArm",
        f"{_s}LowerArm": f"{_s}ForeArm", f"{_s}Hand": f"{_s}Hand",
        f"{_s}UpperLeg": f"{_s}UpperLeg", f"{_s}LowerLeg": f"{_s}LowerLeg",
        f"{_s}Foot": f"{_s}Foot",
    })
    for _n, _f in sk.DIGITS.items():
        base = "MetaCarpal" if _n == 1 else sk.PROXIMAL
        mid = sk.PROXIMAL if _n == 1 else sk.INTERMEDIATE
        _REST_SOURCE[f"{_s}{_f}Proximal"] = f"{_s}Digit{_n}{base}"
        _REST_SOURCE[f"{_s}{_f}Intermediate"] = f"{_s}Digit{_n}{mid}"
        _REST_SOURCE[f"{_s}{_f}Distal"] = f"{_s}Digit{_n}{sk.DISTAL}"


def rig_from_take(take, frame=0):
    """A synthetic rig profile whose rest pose *is* the performer's pose at `frame`."""
    def entry(position):
        return {
            "humanoidParent": None,
            "restRotation": [0.0, 0.0, 0.0, 1.0],
            "restPosition": list(position),
            "restParentRotation": [0.0, 0.0, 0.0, 1.0],
        }

    bones = {u: entry(take.pos(seg)[frame]) for u, seg in _REST_SOURCE.items()}

    pelvis, chest = take.pos("Pelvis")[frame], take.pos("Chest")[frame]
    for unity, fraction in _SPINE_FRACTIONS.items():
        bones[unity] = entry(pelvis + (chest - pelvis) * fraction)

    for unity in bones:
        bones[unity]["humanoidParent"] = sk.UNITY_PARENT.get(unity, "Spine")
    bones["Hips"]["humanoidParent"] = None

    return from_dict({"avatarName": "synthetic", "hipHeight": 1.0, "bones": bones})


@pytest.fixture(scope="module")
def zeroed_take(hello_take):
    """The take with all clinical angle channels zeroed, so roll contributes nothing."""
    import dataclasses
    angles = {k: np.zeros_like(v) for k, v in hello_take.angles.items()}
    return dataclasses.replace(hello_take, angles=angles)


def test_identity_retarget(zeroed_take):
    """Avatar rest pose == performer pose at frame 0 => frame 0 must retarget to the rest pose."""
    rig = rig_from_take(zeroed_take, frame=0)
    motion = reconstruct(zeroed_take)
    deltas = compute_deltas(motion, rig)

    for unity, delta in deltas.items():
        angle = np.degrees(delta[0].magnitude())
        assert angle < 1e-6, f"{unity} delta at frame 0 is {angle:.4f} deg, expected 0"


def test_identity_retarget_gives_rest_locals(zeroed_take):
    rig = rig_from_take(zeroed_take, frame=0)
    locals_ = to_local_rotations(reconstruct(zeroed_take), rig)

    for unity, rot in locals_.items():
        rb = rig.bones[unity]
        expected = rb.rest_parent_rotation.inv() * rb.rest_rotation
        err = np.degrees((expected.inv() * rot[0]).magnitude())
        assert err < 1e-6, f"{unity} local at frame 0 is off by {err:.4f} deg"


def test_moving_frames_actually_move(zeroed_take):
    """Guard against a retarget that silently collapses to the rest pose for every frame."""
    rig = rig_from_take(zeroed_take, frame=0)
    locals_ = to_local_rotations(reconstruct(zeroed_take), rig)
    moved = [
        u for u, r in locals_.items()
        if np.degrees((r[0].inv() * r).magnitude()).max() > 5.0
    ]
    assert len(moved) > 5, f"only {len(moved)} bones moved during the sign"


def test_all_output_rotations_are_finite_unit_quaternions(zeroed_take):
    rig = rig_from_take(zeroed_take, frame=0)
    for unity, rot in to_local_rotations(reconstruct(zeroed_take), rig).items():
        q = rot.as_quat()
        assert np.all(np.isfinite(q)), f"{unity} produced non-finite rotations"
        assert np.allclose(np.linalg.norm(q, axis=1), 1.0), f"{unity} quaternions not unit length"


def test_rig_profile_rejects_a_partial_hand():
    bones = {
        u: {"humanoidParent": None, "restRotation": [0, 0, 0, 1],
            "restPosition": [0, 0, 0], "restParentRotation": [0, 0, 0, 1]}
        for u in ("Hips", "Spine", "Neck", "Head")
    }
    with pytest.raises(RigProfileError, match="missing"):
        from_dict({"bones": bones})
