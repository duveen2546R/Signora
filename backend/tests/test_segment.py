"""Finding the meaning-bearing part of a sign.

Preparation and retraction describe a journey to and from rest that is wrong once a sign has a
neighbour. These tests pin the boundaries against what the recordings actually contain.
"""
import numpy as np
import pytest

from app.ingest.landmarks import LandmarkTake
from app.ingest.segment import (
    CORRUPT_MEDIAN_STEP_CM,
    body_step_cm,
    find_stroke,
    usable_range,
    wrist_speed,
)


def test_stroke_is_inside_the_clip(library):
    for name, take in library.items():
        stroke = find_stroke(take)
        assert 0 <= stroke.start < stroke.end <= take.frame_count, name
        assert stroke.frame_count > 0


def test_seam_candidates_never_enter_the_protected_stroke(library):
    from app.ingest.segment import boundary_candidates

    for take in library.values():
        stroke = find_stroke(take)
        entries = list(boundary_candidates(take, stroke, "entry"))
        exits = list(boundary_candidates(take, stroke, "exit"))
        assert entries and exits
        assert max(entries) == stroke.start
        assert min(exits) == stroke.end - 1


def test_preparation_is_actually_trimmed(library):
    """The whole point: a mid-sentence sign must not replay its run-up from rest."""
    trimmed = {n: find_stroke(t) for n, t in library.items()}
    removed = [t.start + (library[n].frame_count - t.end) for n, t in trimmed.items()]
    assert sum(removed) > 0, "no clip had any preparation or retraction removed"
    assert not any(s.used_fallback for s in trimmed.values()), \
        {n: s.reason for n, s in trimmed.items() if s.used_fallback}


def test_stroke_spans_internal_holds(library):
    """Signs pause mid-way - Father holds at the forehead for about a second.

    Taking the longest *contiguous* burst of movement would keep only half the sign, so the stroke
    has to span from the first burst to the last.
    """
    take = library.get("Father")
    if take is None:
        pytest.skip("Father not recorded")
    stroke = find_stroke(take)
    speed = wrist_speed(take)[stroke.start:stroke.end]
    quiet = speed < 0.2 * speed.max()
    assert quiet.sum() > 5, "expected a hold inside the stroke"


def test_corrupt_final_frames_are_detected(library):
    """Two of the five recordings end with a frame where the whole skeleton teleports."""
    flagged = {n: usable_range(t)[1] < t.frame_count for n, t in library.items()}
    assert any(flagged.values()), "expected at least one take with a corrupt final frame"
    for name, take in library.items():
        start, end, _ = usable_range(take)
        step = body_step_cm(take)[start:max(end - 1, start)]
        if step.size:
            assert step.max() <= CORRUPT_MEDIAN_STEP_CM, f"{name} kept a corrupt frame"


def test_body_step_separates_glitches_from_signing(library):
    """Real signing moves a few landmarks; a broken sample moves all of them at once."""
    for name, take in library.items():
        start, end, _ = usable_range(take)
        clean = body_step_cm(take)[start:max(end - 1, start)]
        assert np.median(clean) < 1.0, f"{name} median body step is implausibly large"


def test_static_clip_falls_back_to_the_whole_take(library):
    """A sign that is mostly a held pose has no velocity peak; it must not be trimmed to nothing."""
    take = next(iter(library.values()))
    frozen = LandmarkTake(
        name="frozen", fps=take.fps,
        pose=np.repeat(take.pose[:1], 40, axis=0),
        left_hand=np.repeat(take.left_hand[:1], 40, axis=0),
        right_hand=np.repeat(take.right_hand[:1], 40, axis=0),
    )
    stroke = find_stroke(frozen)
    assert stroke.used_fallback
    assert stroke.start == 0 and stroke.end == frozen.frame_count


def test_very_short_clip_is_left_alone(library):
    take = next(iter(library.values()))
    tiny = LandmarkTake("tiny", take.fps, take.pose[:3], take.left_hand[:3], take.right_hand[:3])
    stroke = find_stroke(tiny)
    assert stroke.used_fallback and stroke.start == 0 and stroke.end == 3


def _fingers_only(library, skeleton):
    """A sign performed with the arm held still - the shape of a fingerspelled letter."""
    from app.ingest import blend
    from app.ingest.blend import Pose, decompose, rebuild

    source = next(iter(library.values()))
    frozen = decompose(skeleton, Pose.at(source, 0))
    frames = []
    for i in range(source.frame_count):
        live = decompose(skeleton, Pose.at(source, i))
        frames.append(rebuild(skeleton, blend.GeneralisedPose(
            hip_axis=frozen.hip_axis, shoulders=frozen.shoulders,
            head_rotation=frozen.head_rotation, head_centroid=frozen.head_centroid,
            legs=frozen.legs, arm_dirs=frozen.arm_dirs,
            left_dirs=live.left_dirs, right_dirs=live.right_dirs,
        )))
    return LandmarkTake(
        "fingers-only", source.fps,
        np.stack([f.pose for f in frames]),
        np.stack([f.left_hand for f in frames]),
        np.stack([f.right_hand for f in frames]),
    )


def test_a_sign_made_only_of_finger_motion_is_still_detected(library, skeleton):
    """Fingerspelling holds the hand still and moves the fingers.

    Segmenting on wrist translation alone measures 0.0 cm/s on such a clip and declares it
    motionless, so every letter would play untrimmed - including its run-up from rest, which is
    the one thing sentence composition exists to remove.
    """
    from app.ingest.segment import activity_speed
    clip = _fingers_only(library, skeleton)

    assert wrist_speed(clip).max() < 1.0, "the arm really is stationary in this fixture"
    assert activity_speed(clip).max() > 20.0, "the fingers are moving and must register"

    stroke = find_stroke(clip)
    assert not stroke.used_fallback, stroke.reason


def test_activity_counts_palm_rotation(library, skeleton):
    """A sign can be a twist of the wrist with no translation at all."""
    from app.ingest.segment import activity_speed
    clip = _fingers_only(library, skeleton)
    assert activity_speed(clip).max() > wrist_speed(clip).max()


def test_preparation_is_still_trimmed_with_the_wider_metric(library):
    """Broadening what counts as movement must not stop the run-up being removed."""
    trimmed = [find_stroke(t).start for t in library.values()]
    assert sum(trimmed) > 0
