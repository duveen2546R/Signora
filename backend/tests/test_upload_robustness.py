"""Awkward captures either pass all motion gates or return diagnostic rejection."""
import itertools

import numpy as np
import pytest

from app.ingest import blend
from app.ingest.blend import Pose, decompose, rebuild
from app.ingest.compose import BlendRejected, compose as compose_strict
from app.ingest.landmarks import LandmarkTake
from tests.test_blend import segment_errors

def compose(*args, **kwargs):
    try:
        return compose_strict(*args, **kwargs)
    except BlendRejected as exc:
        quality = exc.blend_quality
        assert quality["status"] == "rejected"
        assert quality["seams"] and quality["seams"][-1]["reasons"]
        assert not quality["seams"][-1]["passed"]
        return None


WRIST = 16
PLAUSIBLE_PEAK_CM_S = 400.0


def _rebuild_with(skeleton, source, arm_dirs, frames):
    """A synthetic capture holding a fixed arm pose, built through the real skeleton."""
    base = decompose(skeleton, Pose.at(source, min(source.frame_count // 2, source.frame_count - 1)))
    direction = blend._unit(np.asarray(arm_dirs, dtype=np.float64))
    poses = [
        rebuild(skeleton, blend.GeneralisedPose(
            base.hip_axis, base.shoulders, base.head_rotation, base.head_centroid,
            base.legs, direction, base.left_dirs, base.right_dirs,
        ))
        for _ in range(frames)
    ]
    return LandmarkTake(
        "synthetic", source.fps,
        np.stack([p.pose for p in poses]),
        np.stack([p.left_hand for p in poses]),
        np.stack([p.right_hand for p in poses]),
    )


@pytest.fixture(scope="module")
def awkward(prepared, skeleton):
    """Captures a future upload might plausibly contain, none of them like the current library."""
    source = next(iter(prepared.values()))
    overhead = [[0.0, 1.0, 0.05]] * 4          # arms straight up
    behind = [[-0.2, -0.3, -1.0], [0.2, -0.3, -1.0]] * 2   # arms pressed back
    frozen = LandmarkTake(
        "frozen", source.fps,
        np.repeat(source.pose[:1], 90, axis=0),
        np.repeat(source.left_hand[:1], 90, axis=0),
        np.repeat(source.right_hand[:1], 90, axis=0),
    )
    scaled = LandmarkTake(
        "scaled", source.fps,
        source.pose * 1.08, source.left_hand * 1.08, source.right_hand * 1.08,
    )
    return {
        "overhead": _rebuild_with(skeleton, source, overhead, 90),
        "behind": _rebuild_with(skeleton, source, behind, 90),
        "frozen": frozen,
        "scaled": scaled,
        "tiny": LandmarkTake("tiny", source.fps, source.pose[:6],
                             source.left_hand[:6], source.right_hand[:6]),
    }


def assert_playable(skeleton, result, label):
    """Whatever route composition took, the output must be usable."""
    if result is None:
        return
    track = result.track
    assert track.frame_count > 0, f"{label}: produced no frames"
    assert np.all(np.isfinite(track.pose)), f"{label}: non-finite landmarks"
    assert segment_errors(skeleton, track) < 5e-4, f"{label}: broke the skeleton"

    # The two arrays must keep agreeing about the joints they share.
    assert np.abs(track.right_hand[:, 0] - track.pose[:, WRIST]).max() < 1e-9, label
    assert np.abs(track.left_hand[:, 0] - track.pose[:, 15]).max() < 1e-9, label

    assert result.segments[0].start == 0
    assert result.segments[-1].end == track.frame_count
    for first, second in zip(result.segments, result.segments[1:]):
        assert first.end == second.start, f"{label}: segments do not tile"

    assert result.blend_quality["status"] == "direct"


def test_awkward_capture_passes_or_rejects_on_its_own(awkward, prepared, skeleton):
    for label, clip in awkward.items():
        result = compose(skeleton, [(label.upper(), clip)])
        assert_playable(skeleton, result, label)


def test_awkward_pairs_pass_or_reject(awkward, prepared, skeleton):
    """Both orderings: the odd capture leading, and following."""
    real_name, real = next(iter(prepared.items()))
    for label, clip in awkward.items():
        for pair in (
            [(label.upper(), clip), (real_name, real)],
            [(real_name, real), (label.upper(), clip)],
        ):
            result = compose(skeleton, pair)
            assert_playable(skeleton, result, f"{pair[0][0]} -> {pair[1][0]}")


def test_extreme_pair_passes_or_rejects(awkward, skeleton):
    """Two unrelated extremes back to back - the hardest join the library could produce."""
    result = compose(skeleton, [
        ("OVERHEAD", awkward["overhead"]), ("BEHIND", awkward["behind"]),
    ])
    assert_playable(skeleton, result, "overhead -> behind")


def test_no_sentence_moves_the_hands_impossibly_fast(awkward, prepared, skeleton):
    """Degrading must not mean giving up on physical plausibility."""
    real_name, real = next(iter(prepared.items()))
    for label, clip in awkward.items():
        result = compose(skeleton, [(real_name, real), (label.upper(), clip)])
        if result is None:
            continue
        speed = np.linalg.norm(
            np.diff(result.track.pose[:, WRIST], axis=0), axis=1
        ) * result.track.fps * 100.0
        assert speed.max() < PLAUSIBLE_PEAK_CM_S, f"{label}: {speed.max():.0f} cm/s"


def test_every_real_sentence_composes(prepared, skeleton):
    """Exhaustive over the current library: no ordering may fail."""
    names = list(prepared)
    for combo in itertools.chain(
        itertools.permutations(names, 2), itertools.permutations(names, 3),
    ):
        result = compose(skeleton, [(name, prepared[name]) for name in combo])
        assert_playable(skeleton, result, " ".join(combo))
