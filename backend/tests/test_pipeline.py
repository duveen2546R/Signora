"""The whole ingest chain, against a real recording."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app.ingest import clipfmt
from app.ingest.pipeline import ingest_take
from app.ingest.resample import TARGET_FPS
from tests.test_retarget import rig_from_take


@pytest.fixture(scope="module")
def ingested(hello_take):
    rig = rig_from_take(hello_take, frame=0)
    return ingest_take(hello_take, rig)


def test_output_is_uniform_sixty_fps(ingested, hello_take):
    clip, qc = ingested
    assert clip.fps == TARGET_FPS
    # Duration is preserved; frame count roughly doubles from the 30 fps source.
    assert clip.duration == pytest.approx(hello_take.duration, abs=0.05)
    assert clip.frame_count > hello_take.frame_count * 1.8


def test_every_driven_bone_is_present(ingested):
    from app.ingest import skeleton as sk
    clip, _ = ingested
    assert set(clip.bone_names) == set(sk.UNITY_BONES)


def test_clip_survives_a_round_trip_through_the_binary(ingested):
    clip, _ = ingested
    out = clipfmt.decode(clipfmt.encode(clip))
    a = Rotation.from_quat(clip.rotations.reshape(-1, 4))
    b = Rotation.from_quat(out.rotations.reshape(-1, 4))
    assert np.degrees((a.inv() * b).magnitude()).max() < 0.02


def test_qc_identifies_the_dominant_hand(ingested):
    _, qc = ingested
    assert qc.dominant_hand in ("Left", "Right")
    assert qc.hand_travel_cm[qc.dominant_hand] >= qc.hand_travel_cm[
        "Left" if qc.dominant_hand == "Right" else "Right"
    ]


def test_a_clean_take_produces_no_warnings(ingested):
    _, qc = ingested
    assert qc.warnings == [], qc.warnings
    assert qc.max_bone_length_spread_mm < 5.0


def test_smoothing_reduces_frame_to_frame_jitter(hello_take):
    rig = rig_from_take(hello_take, frame=0)
    rough, _ = ingest_take(hello_take, rig, smooth=False)
    smooth, _ = ingest_take(hello_take, rig, smooth=True)

    def jitter(clip):
        # Second difference: how much the per-frame step changes, i.e. how shaky the motion is.
        q = Rotation.from_quat(clip.rotations[:, 0, :])
        step = np.degrees((q[:-1].inv() * q[1:]).magnitude())
        return float(np.abs(np.diff(step)).mean())

    assert jitter(smooth) <= jitter(rough)


def test_clip_size_is_reasonable(ingested):
    clip, _ = ingested
    blob = clipfmt.encode(clip)
    per_second = len(blob) / clip.duration
    assert per_second < 40_000, f"{per_second:.0f} bytes/second is larger than expected"


# Fast fingerspelling reaches a few hundred deg/s. Anything approaching a full revolution per second
# is a reconstruction artefact, not motion a hand can make.
PLAUSIBLE_PEAK_DEG_S = 1500.0


def test_no_impossible_rotation_speeds(ingested):
    """Regression guard for shortest-arc roll instability.

    Measuring a bone's swing against the avatar's static rest pose makes a finger that rests pointing
    down and signs pointing up a ~180 degree arc, where the roll component is numerically undefined
    and flips frame to frame. That produced 10,000+ deg/s spikes on real takes. Swing is now measured
    against the parent's current frame; this test fails if that regresses.
    """
    _, qc = ingested
    assert qc.peak_angular_velocity_deg_s < PLAUSIBLE_PEAK_DEG_S, (
        f"{qc.fastest_bone} reaches {qc.peak_angular_velocity_deg_s:.0f} deg/s"
    )


def test_rotations_are_continuous_between_frames(ingested):
    """No single frame step may jump implausibly far, anywhere in the clip."""
    clip, _ = ingested
    limit = PLAUSIBLE_PEAK_DEG_S / clip.fps
    worst_bone, worst = "", 0.0
    for i, name in enumerate(clip.bone_names):
        q = Rotation.from_quat(clip.rotations[:, i, :])
        step = np.degrees((q[:-1].inv() * q[1:]).magnitude()).max()
        if step > worst:
            worst_bone, worst = name, float(step)
    assert worst < limit, f"{worst_bone} jumps {worst:.1f} deg in one frame (limit {limit:.1f})"


def test_swing_is_measured_hierarchically(hello_take):
    """The parent-relative swing must beat the naive rest-relative one on real data."""
    from app.ingest.reconstruct import reconstruct
    from app.ingest.retarget import _shortest_arc, compute_deltas

    rig = rig_from_take(hello_take, frame=0)
    motion = reconstruct(hello_take)
    hierarchical = compute_deltas(motion, rig)

    def peak(rotations):
        step = np.degrees((rotations[:-1].inv() * rotations[1:]).magnitude())
        return float(step.max()) if step.size else 0.0

    # The naive formulation, for comparison only.
    bone = next(b for b in __import__("app.ingest.skeleton", fromlist=["x"]).BONES
                if b.unity == "RightRingProximal")
    naive = _shortest_arc(rig.rest_axis(bone.unity), motion[bone.name].axis)

    assert peak(hierarchical["RightRingProximal"]) < peak(naive)
