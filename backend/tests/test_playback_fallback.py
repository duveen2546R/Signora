"""Reviewed recordings that cannot blend with rest directly: what may play, and what never may.

Two real failure modes made valid, reviewed signs unplayable:

1. Every combined Rokoko FBX opens with the reference T-pose for one frame. The whole-body median
   test could not see it (only the arms move), so on some takes it survived and became the rest
   pose, and every rest join began with a 43 m/s snap.
2. A few takes were captured slightly short - starting in motion or stopping before the hands are
   back at rest - so no direct bridge to the neutral pose passes every check.

These tests use only the checked-in fixture, so they run in CI. The library-dependent regression
for the 27 real recordings lives in test_recorded_library_playback.py.
"""
from dataclasses import replace

import numpy as np
import pytest

from app.ingest import blend
from app.ingest.compose import TARGET_FPS, BlendRejected, compose, neutral_pose, prepare
from app.ingest.landmarks import LandmarkSkeleton, LandmarkTake, slice_frames, to_landmarks
from app.ingest.segment import (
    CORRUPT_MEDIAN_STEP_CM,
    CORRUPT_WRIST_SPEED_CM_S,
    body_step_cm,
    usable_range,
    wrist_step_speed,
)

ARM_LANDMARKS = list(range(13, 23))  # elbows, wrists and the coarse hand points


@pytest.fixture(scope="module")
def base(hello_take):
    return to_landmarks(hello_take)


@pytest.fixture(scope="module")
def skel(base):
    return LandmarkSkeleton.from_takes(base)


def with_reference_t_pose(take: LandmarkTake) -> LandmarkTake:
    """Prepend the frame Rokoko exports at time zero: arms out at shoulder height, legs unmoved."""
    first = take.pose[0].copy()
    for side, shoulder in ((-1.0, 11), (1.0, 12)):
        out = np.array([side * 0.55, 0.0, 0.0])
        for index in ARM_LANDMARKS[(0 if side < 0 else 1)::2]:
            first[index] = take.pose[0, shoulder] + out * (1.0 if index >= 15 else 0.5)
    shift_left = first[15] - take.pose[0, 15]
    shift_right = first[16] - take.pose[0, 16]
    return LandmarkTake(
        name=take.name, fps=take.fps,
        pose=np.concatenate([first[None], take.pose]),
        left_hand=np.concatenate([take.left_hand[:1] + shift_left, take.left_hand]),
        right_hand=np.concatenate([take.right_hand[:1] + shift_right, take.right_hand]),
    )


def reviewed(take: LandmarkTake, start: float, end: float) -> LandmarkTake:
    return replace(take, sign_start_s=start, sign_end_s=end,
                   phase_source="authored-ui", phase_reviewed=True)


def starts_in_motion(base: LandmarkTake, cut: int = 6) -> LandmarkTake:
    """The checked-in Hello, trimmed so the take opens with the hands moving at ~60 cm/s."""
    take = slice_frames(base, cut, base.frame_count)
    return reviewed(take, 0.15, 0.75)


# --- 1. The reference T-pose frame -----------------------------------------------------------

def test_reference_t_pose_is_invisible_to_the_median_test(base):
    """The exact blind spot: the snap moves only the arms, so the whole-body median stays low."""
    take = with_reference_t_pose(base)
    assert body_step_cm(take)[0] <= CORRUPT_MEDIAN_STEP_CM
    assert wrist_step_speed(take)[0] > CORRUPT_WRIST_SPEED_CM_S


def test_reference_t_pose_frame_is_trimmed(base):
    start, end, _ = usable_range(with_reference_t_pose(base))
    assert start == 1, "the T-pose frame must not survive into the usable range"
    assert end == base.frame_count + 1


def test_rest_pose_is_no_longer_built_from_the_t_pose(base, skel):
    take = with_reference_t_pose(base)
    prepared = prepare(take, skel, fps=TARGET_FPS)
    rest = neutral_pose(skel, [prepared])
    clean_rest = neutral_pose(skel, [prepare(base, skel, fps=TARGET_FPS)])
    gap = max(np.linalg.norm(rest.pose[w] - clean_rest.pose[w]) for w in (15, 16))
    assert gap < 0.01, f"rest pose moved {gap * 100:.1f} cm towards the T-pose"


def test_real_signing_stays_well_under_the_wrist_teleport_threshold(library):
    for name, take in library.items():
        start, end, _ = usable_range(take)
        speed = wrist_step_speed(take)[start:max(end - 1, start)]
        assert speed.max() < CORRUPT_WRIST_SPEED_CM_S / 2, name


# --- 2. Settles for reviewed takes captured short --------------------------------------------

def test_strict_composition_still_rejects_a_take_that_starts_in_motion(base, skel):
    prepared = prepare(starts_in_motion(base), skel, fps=TARGET_FPS)
    with pytest.raises(BlendRejected, match="rest to HELLO"):
        compose(skel, [("HELLO", prepared)])


def test_reviewed_take_that_starts_in_motion_plays_through_a_labelled_settle(base, skel):
    prepared = prepare(starts_in_motion(base), skel, fps=TARGET_FPS)
    composition = compose(skel, [("HELLO", prepared)], allow_reviewed_direct=True)
    quality = composition.blend_quality
    assert quality["status"] == "reviewed-direct"
    settle = next(seam for seam in quality["seams"] if seam["mode"] == "reviewed-direct")
    assert settle["fromGloss"] == "" and settle["toGloss"] == "HELLO"
    # Honest reporting: the strict gate is not claimed, and what was waived is listed.
    assert settle["passed"] is False
    assert settle["waivedChecks"]
    assert set(settle["waivedChecks"]) <= blend.SETTLE_WAIVABLE_REASONS
    assert settle["directAttempt"]["passed"] is False
    # The sign itself is untouched and the track ends at rest, never stuck mid-sign.
    signs = [segment for segment in composition.segments if segment.kind == "sign"]
    assert len(signs) == 1
    final = composition.track.pose[-1]
    assert max(np.linalg.norm(final[w] - composition.neutral.pose[w]) for w in (15, 16)) < 0.01


def test_an_unreviewed_take_never_gets_a_settle(base, skel):
    take = replace(starts_in_motion(base), phase_reviewed=False, phase_source="detected")
    prepared = prepare(take, skel, fps=TARGET_FPS)
    with pytest.raises(BlendRejected):
        compose(skel, [("HELLO", prepared)], allow_reviewed_direct=True)


@pytest.mark.parametrize("cut", [12, 21])
def test_a_settle_that_breaks_a_mandatory_check_is_still_rejected(base, skel, cut):
    """Not a whitelist: here the settle itself would exceed the avatar's speed limits."""
    prepared = prepare(starts_in_motion(base, cut), skel, fps=TARGET_FPS)
    with pytest.raises(BlendRejected):
        compose(skel, [("HELLO", prepared)], allow_reviewed_direct=True)


@pytest.mark.parametrize("reason, acceptable", [
    ("seam jerk exceeds the adjacent-motion envelope", True),
    ("seam acceleration exceeds the adjacent-motion envelope", True),
    ("direct transition requires more than 600 ms", True),
    ("transition contains non-finite landmark values", False),
    ("transition violates measured bone lengths", False),
    ("wrist speed exceeds the avatar limit", False),
    ("joint speed exceeds the avatar limit", False),
    ("transition intersects the torso or head", False),
    ("contact handshape is not ready at the required boundary", False),
    ("transition swings wide of the path between the signs", False),
])
def test_only_boundary_envelope_checks_may_be_waived(reason, acceptable):
    quality = blend.TransitionQuality(50.0, False, {}, (reason,))
    assert blend.settle_is_acceptable(quality) is acceptable


def test_status_precedence_names_the_least_strict_seam(base, skel):
    """A strict caller must be able to refuse a settle it never asked for by status alone."""
    prepared = prepare(starts_in_motion(base), skel, fps=TARGET_FPS)
    composition = compose(
        skel, [("HELLO", prepared)], allow_neutral_fallback=True, allow_reviewed_direct=True,
    )
    assert composition.blend_quality["status"] == "reviewed-direct"
