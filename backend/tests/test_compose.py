"""Composing a sentence.

The two properties that matter: every frame is a possible pose, and the joins are not visible. The
second is measured against the recorded motion itself - a seam should be no rougher than the
footage it sits between.
"""
import itertools
from pathlib import Path

import numpy as np
import pytest

from app.ingest.compose import ALGORITHM_VERSION, BlendRejected, TARGET_FPS, compose, neutral_pose, prepare
from tests.test_blend import segment_errors

WRIST = 16


def sentences(prepared, limit=None):
    names = list(prepared)
    pairs = list(itertools.permutations(names, 2))
    return pairs[:limit] if limit else pairs


def wrist_speed_cm_s(track):
    return np.linalg.norm(np.diff(track.pose[:, WRIST], axis=0), axis=1) * track.fps * 100.0


def test_prepare_puts_clips_on_the_playback_timebase(library, skeleton):
    take = next(iter(library.values()))
    out = prepare(take, skeleton)
    assert out.fps == TARGET_FPS
    assert out.frame_count > take.frame_count      # 30 fps source, 60 fps target
    assert segment_errors(skeleton, out) < 5e-4    # resampling and smoothing must not stretch limbs


def test_resampling_preserves_last_csv_sample_interval(library, skeleton):
    from dataclasses import replace

    source = next(iter(library.values()))
    # Fixed source clock with intact rest bookends. The final row is an interval,
    # not an instantaneous clip end that can remove half a frame during upsampling.
    source = replace(source, timestamps=np.arange(source.frame_count) / 30.0)
    result = prepare(source, skeleton, fps=60.0, smooth=False)
    assert result.frame_count == 2 * source.frame_count
    assert result.duration == pytest.approx(source.duration)


def test_prepare_removes_the_corrupt_tail(library, skeleton):
    """Smoothing across a broken frame smears it; it has to be dropped first."""
    for name, take in library.items():
        out = prepare(take, skeleton)
        speed = wrist_speed_cm_s(out)
        assert speed.max() < 400, f"{name} still contains a {speed.max():.0f} cm/s lunge"


def test_every_composed_frame_is_a_possible_pose(prepared, skeleton):
    """The load-bearing test: rigidity through strokes, coasts and transitions alike."""
    for a, b in sentences(prepared):
        result = compose(skeleton, [(a, prepared[a]), (b, prepared[b])], fps=TARGET_FPS)
        assert segment_errors(skeleton, result.track) < 5e-4, f"{a} -> {b}"


def test_shared_joints_survive_composition(prepared, skeleton):
    a, b = list(prepared)[:2]
    track = compose(skeleton, [(a, prepared[a]), (b, prepared[b])]).track
    assert np.abs(track.right_hand[:, 0] - track.pose[:, WRIST]).max() < 1e-9
    assert np.abs(track.left_hand[:, 0] - track.pose[:, 15]).max() < 1e-9


def test_segments_tile_the_track(prepared, skeleton):
    a, b = list(prepared)[:2]
    result = compose(skeleton, [(a, prepared[a]), (b, prepared[b])])
    assert result.segments[0].start == 0
    assert result.segments[-1].end == result.track.frame_count
    for first, second in zip(result.segments, result.segments[1:]):
        assert first.end == second.start, "segments must not gap or overlap"


def test_every_sign_appears_once_in_order(prepared, skeleton):
    names = list(prepared)[:3]
    result = compose(skeleton, [(n, prepared[n]) for n in names])
    signs = [s.gloss for s in result.segments if s.kind == "sign"]
    assert signs == names


def test_seams_are_smoother_than_the_motion_they_join(prepared, skeleton):
    """A join must not be the roughest thing in the sentence."""
    worst_seam = worst_inside = 0.0
    for a, b in sentences(prepared):
        result = compose(skeleton, [(a, prepared[a]), (b, prepared[b])])
        accel = np.abs(np.diff(wrist_speed_cm_s(result.track)))
        mask = np.ones(len(accel), bool)
        for segment in result.segments[1:]:
            lo, hi = max(segment.start - 2, 0), min(segment.start + 1, len(accel))
            if hi > lo:
                worst_seam = max(worst_seam, float(accel[lo:hi].max()))
                mask[lo:hi] = False
        if mask.any():
            worst_inside = max(worst_inside, float(accel[mask].max()))

    assert worst_seam <= worst_inside + 1e-9, (
        f"seams accelerate at {worst_seam:.0f} cm/s per frame against "
        f"{worst_inside:.0f} inside the recorded motion"
    )


def test_no_impossible_hand_speed(prepared, skeleton):
    for a, b in sentences(prepared):
        track = compose(skeleton, [(a, prepared[a]), (b, prepared[b])]).track
        peak = wrist_speed_cm_s(track).max()
        assert peak < 400, f"{a} -> {b} peaks at {peak:.0f} cm/s"


def test_a_sentence_is_shorter_than_playing_the_clips_whole(prepared, skeleton):
    """Trimming preparation and retraction is the point; it should show up in the duration."""
    names = list(prepared)[:3]
    result = compose(skeleton, [(n, prepared[n]) for n in names])
    whole = sum(prepared[n].duration for n in names)
    assert result.track.duration < whole


def test_single_sign_sentence_still_leads_in_and_out(prepared, skeleton):
    name = next(iter(prepared))
    result = compose(skeleton, [(name, prepared[name])])
    kinds = [s.kind for s in result.segments]
    assert kinds[0] == "hold" and kinds[-1] == "hold"
    assert "transition" in kinds and "sign" in kinds


def test_empty_sentence_is_rejected(skeleton):
    with pytest.raises(ValueError, match="at least one sign"):
        compose(skeleton, [])


def test_neutral_pose_is_a_valid_resting_pose(prepared, skeleton):
    from app.ingest.blend import Pose
    rest = neutral_pose(skeleton, list(prepared.values()))
    assert np.abs(rest.right_hand[0] - rest.pose[WRIST]).max() < 1e-9
    # Hands down: the wrists sit below the shoulders.
    assert rest.pose[WRIST][1] < rest.pose[12][1]
    assert isinstance(rest, Pose)


def test_payload_carries_segments_and_neutral(prepared, skeleton):
    import json
    a, b = list(prepared)[:2]
    payload = compose(skeleton, [(a, prepared[a]), (b, prepared[b])]).to_payload()
    assert payload["frameCount"] == len(payload["pose"])
    assert len(payload["leftHand"]) == len(payload["rightHand"]) == payload["frameCount"]
    assert payload["segments"] and payload["neutral"]
    assert payload["blendQuality"]["algorithmVersion"] == ALGORITHM_VERSION
    assert payload["blendQuality"]["status"] == "direct"
    json.dumps(payload)


def test_reviewed_phases_follow_sentence_position(prepared, skeleton):
    from dataclasses import replace
    from app.ingest.segment import find_stroke

    names = list(prepared)[:3]
    reviewed = {}
    spans = {}
    for name in names:
        track = prepared[name]
        stroke = find_stroke(track)
        spans[name] = stroke
        reviewed[name] = replace(
            track,
            sign_start_s=stroke.start / track.fps,
            sign_end_s=stroke.end / track.fps,
            phase_source="authored-ui",
            phase_reviewed=True,
        )

    single = compose(skeleton, [(names[0], reviewed[names[0]])])
    assert [
        segment.kind for segment in single.segments
        if segment.kind in {"preparation", "sign", "retraction"}
    ] == ["preparation", "sign", "retraction"]

    sentence = compose(skeleton, [(name, reviewed[name]) for name in names])
    for segment in sentence.segments:
        if segment.kind == "sign":
            source = reviewed[segment.gloss]
            span = spans[segment.gloss]
            for channel in ("pose", "left_hand", "right_hand"):
                np.testing.assert_array_equal(
                    getattr(sentence.track, channel)[segment.start:segment.end],
                    getattr(source, channel)[span.start:span.end],
                )
    retained = [
        (segment.gloss, segment.kind, segment.end - segment.start)
        for segment in sentence.segments
        if segment.kind in {"preparation", "sign", "retraction"}
    ]
    assert retained == [
        (names[0], "preparation", spans[names[0]].start),
        (names[0], "sign", spans[names[0]].frame_count),
        (names[1], "sign", spans[names[1]].frame_count),
        (names[2], "sign", spans[names[2]].frame_count),
        (names[2], "retraction", reviewed[names[2]].frame_count - spans[names[2]].end),
    ]


def test_all_failed_seam_strategies_are_rejected_without_neutral(prepared, skeleton, monkeypatch):
    from dataclasses import replace

    from app.ingest import blend as blending

    actual = blending.plan_transition

    def reject_only_sign_to_sign(*args, **kwargs):
        result = actual(*args, **kwargs)
        a, b = args[1], args[3]
        if a.name != "neutral" and b.name != "neutral":
            result = replace(result, quality=blending.TransitionQuality(
                40.0, False, result.quality.metrics, ("forced direct rejection",),
            ))
        return result

    monkeypatch.setattr(blending, "plan_transition", reject_only_sign_to_sign)
    monkeypatch.setattr(blending, "plan_phase_overlap", reject_only_sign_to_sign)
    names = list(prepared)[:2]
    with pytest.raises(BlendRejected) as failure:
        compose(skeleton, [(name, prepared[name]) for name in names])
    quality = failure.value.blend_quality
    assert quality["status"] == "rejected"
    assert quality["seams"][-1]["fromGloss"] == names[0]
    assert "forced direct rejection" in quality["seams"][-1]["reasons"]


def test_authored_phases_automatically_blend_without_pair_configuration(
    prepared, skeleton, monkeypatch,
):
    from dataclasses import replace

    from app.ingest import blend as blending
    from app.ingest.segment import find_stroke

    names = list(prepared)[:2]
    reviewed = []
    for name in names:
        track = prepared[name]
        stroke = find_stroke(track)
        reviewed.append(replace(
            track,
            sign_start_s=stroke.start / track.fps,
            sign_end_s=stroke.end / track.fps,
            phase_source="authored-ui",
            phase_reviewed=True,
        ))

    actual = blending.plan_transition
    rejected_direct = False

    def reject_first_sign_to_sign(*args, **kwargs):
        nonlocal rejected_direct
        result = actual(*args, **kwargs)
        a, b = args[1], args[3]
        if not rejected_direct and a.name != "neutral" and b.name != "neutral":
            rejected_direct = True
            return replace(result, quality=blending.TransitionQuality(
                40.0, False, result.quality.metrics, ("forced direct rejection",),
            ))
        return result

    monkeypatch.setattr(blending, "plan_transition", reject_first_sign_to_sign)
    result = compose(skeleton, list(zip(names, reviewed, strict=True)))

    assert result.blend_quality["status"] == "direct"
    middle = result.blend_quality["seams"][1]
    assert middle["mode"] == "direct"
    assert middle["passed"] is True
    assert middle["strategy"] == "phase-overlap"
    sign_segments = [segment for segment in result.segments if segment.kind == "sign"]
    for source, segment in zip(reviewed, sign_segments, strict=True):
        span = find_stroke(source)
        for channel in ("pose", "left_hand", "right_hand"):
            np.testing.assert_array_equal(
                getattr(result.track, channel)[segment.start:segment.end],
                getattr(source, channel)[span.start:span.end],
            )
    between = result.segments[result.segments.index(sign_segments[0]) + 1:
                              result.segments.index(sign_segments[1])]
    assert between and all(segment.kind == "transition" for segment in between)
    assert all(segment.mode == "direct" for segment in between)


def test_failed_opening_bridge_blocks_the_entire_sentence(prepared, skeleton, monkeypatch):
    from dataclasses import replace

    from app.ingest import blend as blending

    actual = blending.plan_transition

    def reject_everything(*args, **kwargs):
        result = actual(*args, **kwargs)
        return replace(result, quality=blending.TransitionQuality(
            0.0, False, result.quality.metrics, ("forced hard failure",),
        ))

    monkeypatch.setattr(blending, "plan_transition", reject_everything)
    names = list(prepared)[:2]
    with pytest.raises(BlendRejected) as failure:
        compose(skeleton, [(name, prepared[name]) for name in names])
    assert failure.value.blend_quality["status"] == "rejected"
    seam = failure.value.blend_quality["seams"][-1]
    assert seam["fromGloss"] == ""
    assert "forced hard failure" in seam["reasons"]


def test_transitions_stay_within_the_avatar_rate_limit(prepared, skeleton):
    """Unity clamps arm bones to 720 deg/s; a faster transition is truncated, not played.

    On a 28 cm forearm that is roughly 350 cm/s at the wrist, so generated motion is stretched in
    time until it fits rather than being silently cut off on screen.
    """
    from app.ingest.blend import MAX_WRIST_SPEED_CM_S
    for a, b in sentences(prepared):
        result = compose(skeleton, [(a, prepared[a]), (b, prepared[b])])
        speed = wrist_speed_cm_s(result.track)
        for segment in result.segments:
            if segment.kind != "transition" or segment.end - segment.start < 2:
                continue
            peak = speed[segment.start:min(segment.end, len(speed))].max()
            assert peak <= MAX_WRIST_SPEED_CM_S * 1.02, \
                f"{a} -> {b} transition peaks at {peak:.0f} cm/s"


def test_a_bigger_gap_gets_a_longer_transition(prepared, skeleton):
    """Distance-driven timing is the whole reason a fixed transitionMs was wrong."""
    measured = []
    for a, b in sentences(prepared):
        result = compose(skeleton, [(a, prepared[a]), (b, prepared[b])])
        track = result.track
        for segment in result.segments:
            if segment.kind == "transition" and segment.gloss == b and segment.end - segment.start > 1:
                gap = np.linalg.norm(
                    track.pose[min(segment.end, track.frame_count - 1), WRIST]
                    - track.pose[max(segment.start - 1, 0), WRIST]
                )
                measured.append((gap, (segment.end - segment.start) / track.fps))
    assert len(measured) > 4
    measured.sort()
    shortest = np.mean([d for _, d in measured[:3]])
    longest = np.mean([d for _, d in measured[-3:]])
    assert longest > shortest, "transition duration does not grow with the distance covered"


def test_a_mismatched_skeleton_is_reported_not_absorbed(prepared, skeleton, tmp_path, monkeypatch):
    """A clip recorded with different proportions must not be silently reshaped.

    Composing everything against the first clip's skeleton puts 14 mm of error inside the second
    sign's own stroke, with nothing to say so.
    """
    import json

    from app.ingest.landmarks import LandmarkSkeleton, LandmarkTake
    from app.services import compose_service as svc

    names = list(prepared)[:2]
    normal, stretched = prepared[names[0]], prepared[names[1]]
    scaled = LandmarkTake(stretched.name, stretched.fps, stretched.pose * 1.05,
                          stretched.left_hand * 1.05, stretched.right_hand * 1.05)

    paths = {}
    for name, track in ((names[0], normal), (names[1], scaled)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(track.to_payload()))
        paths[name] = path

    class FakeClip:
        def __init__(self, path):
            self.clip_path = str(path)
            self.content_hash = path.stem

    monkeypatch.setattr(svc, "landmark_path", lambda clip: Path(clip.clip_path))
    svc._raw.cache_clear()

    _composition, warnings = svc.compose_clips(
        [(names[0], FakeClip(paths[names[0]])), (names[1], FakeClip(paths[names[1]]))]
    )
    assert warnings, "a 5% proportion difference must be reported"
    assert names[1] in warnings[0] or names[0] in warnings[0]

    gap, _where = LandmarkSkeleton.from_takes(scaled).deviation(
        LandmarkSkeleton.from_takes(normal)
    )
    assert gap > svc.SKELETON_TOLERANCE_M


def test_matched_skeletons_produce_no_warning(prepared, skeleton, tmp_path, monkeypatch):
    import json

    from app.services import compose_service as svc

    names = list(prepared)[:2]
    paths = {}
    for name in names:
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(prepared[name].to_payload()))
        paths[name] = path

    class FakeClip:
        def __init__(self, path):
            self.clip_path = str(path)
            self.content_hash = path.stem

    monkeypatch.setattr(svc, "landmark_path", lambda clip: Path(clip.clip_path))
    svc._raw.cache_clear()

    _composition, warnings = svc.compose_clips([(n, FakeClip(paths[n])) for n in names])
    assert len(warnings) == 1
    assert "safe full-motion fallback" in warnings[0]
    assert names[0] in warnings[0] and names[1] in warnings[0]
    assert "different proportions" not in warnings[0]


def test_occurrences_and_no_inter_sign_holds(prepared, skeleton):
    name, track = next(iter(prepared.items()))
    result = compose(skeleton, [(name, track), (name, track), (name, track)])
    signs = [s for s in result.segments if s.kind == "sign"]
    assert [s.occurrence_index for s in signs] == [0, 1, 2]
    interior = [s for s in result.segments if s.start >= signs[0].end and s.end <= signs[-1].start]
    assert all(s.kind != "hold" and s.mode in {None, "direct"} for s in interior)


def test_failed_closing_bridge_is_rejected(prepared, skeleton, monkeypatch):
    from dataclasses import replace
    from app.ingest import blend
    actual = blend.plan_transition
    def reject_closing(*args, **kwargs):
        result = actual(*args, **kwargs)
        if args[3].name == "neutral":
            return replace(result, quality=blend.TransitionQuality(0, False, {}, ("closing failed",)))
        return result
    monkeypatch.setattr(blend, "plan_transition", reject_closing)
    name, track = next(iter(prepared.items()))
    with pytest.raises(BlendRejected, match="closing failed"):
        compose(skeleton, [(name, track)])


def test_preparation_uses_csv_timebase_for_resampling(library, skeleton):
    from dataclasses import replace
    from app.ingest import compose as module
    from app.ingest import resample
    source = next(iter(library.values()))
    times = np.arange(source.frame_count) / source.fps
    times[30] += 0.004
    raw = replace(source, timestamps=times)
    seen = []
    original = resample.resample_positions
    def capture_times(input_times, values, target):
        seen.append(input_times.copy())
        return original(input_times, values, target)
    from unittest.mock import patch
    with patch.object(module.resample, "resample_positions", capture_times):
        prepare(raw, skeleton)
    assert seen and any(np.any(np.abs(np.diff(t) - 1 / source.fps) > 0.001) for t in seen)
