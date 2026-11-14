"""Turn a resolved playlist into one continuous landmark track.

Composing here rather than in the browser keeps the geometry work next to the machinery that
already exists for it, and leaves the player with a single track to stream - no queue, and so no
gap at a sign boundary. The runtime starts pulling a channel back toward its bind pose as soon as
frames are more than 0.2s old, which is exactly what a stitching gap produces.
"""

from __future__ import annotations

import json
import hashlib
import logging
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.ingest.resample import resample_positions
from app.ingest.compose import (
    ALGORITHM_VERSION,
    HOLD_SECONDS,
    TARGET_FPS,
    BlendRejected,
    Composition,
    Segment,
    compose,
    enforce_track,
    prepare,
)
from app.ingest.landmarks import LandmarkSkeleton, LandmarkTake, concat, slice_frames
from app.ingest.segment import find_phases
from app.models import SignClip
from app.services.artifact_paths import clip_file, source_file
from app.services.source_motion import load_source_motion


class ComposeError(ValueError):
    def __init__(self, message: str, blend_quality: dict | None = None):
        super().__init__(message)
        self.blend_quality = blend_quality or {
            "status": "rejected", "score": 0.0,
            "algorithmVersion": ALGORITHM_VERSION, "seams": [],
        }


logger = logging.getLogger(__name__)


def _load(path: str) -> LandmarkTake:
    payload = json.loads(Path(path).read_text())
    return LandmarkTake.from_payload(payload)


# A clip whose measured proportions differ from the rest of the sentence by more than this is
# reported rather than silently reshaped. A 5% difference in forearm length shows up as 14 mm of
# error inside that sign's own stroke.
SKELETON_TOLERANCE_M = 0.004


@lru_cache(maxsize=64)
def _raw(clip_path: str, source_capture: str = "", source_hash: str = "") -> LandmarkTake:
    """Clip files are content-addressed, so this is safe to cache for the process lifetime."""
    if source_capture:
        return load_source_motion(Path(clip_path), source_capture)[0]
    return _load(clip_path)


def landmark_path(clip: SignClip) -> Path:
    path = clip_file(clip.clip_path)
    if path.suffix == ".json":
        return path
    return path.parent / f"{clip.content_hash}.landmarks.json"


def _pace_reviewed(track: LandmarkTake, skeleton: LandmarkSkeleton) -> LandmarkTake:
    """Play at 80% speed without moving boundaries within the captured motion."""
    stretch = 1.25
    source_times = track.times
    target = np.arange(int(np.ceil(track.frame_count * stretch))) / track.fps / stretch
    return enforce_track(skeleton, replace(
        track,
        pose=resample_positions(source_times, track.pose, target),
        left_hand=resample_positions(source_times, track.left_hand, target),
        right_hand=resample_positions(source_times, track.right_hand, target),
        face_blendshapes=np.clip(
            resample_positions(source_times, track.face_blendshapes, target), 0.0, 1.0,
        ),
        sign_start_s=track.sign_start_s * stretch,
        sign_end_s=track.sign_end_s * stretch,
        timestamps=None,
    ))


# lru_cache only remembers successful compositions, so a sentence whose transitions are rejected
# reruns the whole (minutes-long) search on every request. Rejections are just as deterministic for
# the same key - editing phases or re-recording writes new content hashes - so remember them too.
_REJECTED_MAX = 128
_rejected: dict[tuple, tuple[str, dict]] = {}


@lru_cache(maxsize=128)
def _compose_cached(
    key: tuple[tuple[str, str, str, str, str], ...],
    algorithm_version: int,
    allow_neutral_fallback: bool = False,
    allow_reviewed_direct: bool = False,
) -> tuple[Composition, tuple[str, ...]]:
    """Cache immutable compositions by ordered content hashes and algorithm version."""
    raw = []
    for gloss, path, _content_hash, source_capture, source_hash in key:
        try:
            raw.append((gloss, _raw(path, source_capture, source_hash)))
        except (ValueError, OSError) as exc:
            raise ComposeError(f"{gloss}: {exc}") from exc
    shared = LandmarkSkeleton.from_takes([track for _, track in raw])

    warnings: list[str] = []
    unreviewed_glosses: list[str] = []
    for gloss, track in raw:
        if not track.phase_reviewed:
            # This is one sentence-level advisory, not one independent blend failure per clip.
            # Collect it here so the frontend does not look like it emitted the same error log for
            # every word in the sentence.
            if gloss not in unreviewed_glosses:
                unreviewed_glosses.append(gloss)
        gap, where = LandmarkSkeleton.from_takes(track).deviation(shared)
        if gap > SKELETON_TOLERANCE_M:
            warnings.append(
                f"{gloss} was recorded with different proportions to the rest of this sentence "
                f"({where} differs by {gap * 100:.1f} cm); it will be reshaped to match. "
                "Re-record it in the same session, or recalibrate the suit consistently."
            )

    if unreviewed_glosses:
        names = ", ".join(unreviewed_glosses)
        noun = "capture" if len(unreviewed_glosses) == 1 else "captures"
        warnings.insert(
            0,
            f"Using safe full-motion fallback for unreviewed {noun}: {names}. "
            "Add sign-start and sign-end timestamps to enable position-aware trimming.",
        )

    prepared = []
    for gloss, track in raw:
        try:
            prepared.append((gloss, prepare(track, shared, fps=TARGET_FPS)))
        except ValueError as exc:
            raise ComposeError(f"{gloss}: {exc}") from exc
    try:
        composition = compose(
            shared, prepared, fps=TARGET_FPS, algorithm_version=algorithm_version,
            allow_neutral_fallback=allow_neutral_fallback,
            allow_reviewed_direct=allow_reviewed_direct,
        )
    except BlendRejected as exc:
        # A reviewed boundary may lie in fast motion. Keep its source position
        # fixed and try a modest, uniform slowdown before declaring it unjoinable.
        # Every retry still passes the same geometry and motion-quality checks.
        if len(prepared) < 2 or not all(
            track.phase_reviewed and track.has_phase_bounds for _, track in prepared
        ):
            raise ComposeError(str(exc), exc.blend_quality) from exc
        try:
            composition = compose(
                shared, [(gloss, _pace_reviewed(track, shared)) for gloss, track in prepared],
                fps=TARGET_FPS, algorithm_version=algorithm_version,
                allow_neutral_fallback=allow_neutral_fallback,
                allow_reviewed_direct=allow_reviewed_direct,
            )
        except BlendRejected as paced_exc:
            raise ComposeError(str(paced_exc), paced_exc.blend_quality) from paced_exc
        except ValueError as paced_exc:
            raise ComposeError(str(paced_exc)) from paced_exc
        composition.blend_quality["playbackRate"] = 0.8
        warnings.append(
            "Playing at 80% speed to preserve saved Start, Sign and End boundaries "
            "through fast transitions."
        )
    except ValueError as exc:
        raise ComposeError(str(exc)) from exc
    return composition, tuple(warnings)


def compose_clips(
    clips: list[tuple[str, SignClip]],
    allow_neutral_fallback: bool = False,
    allow_reviewed_direct: bool = False,
) -> tuple[Composition, list[str]]:
    """Build the sentence track for `(gloss, clip)` pairs, in order.

    `allow_neutral_fallback` lets an unjoinable pair pass through the rest pose, and
    `allow_reviewed_direct` lets a reviewed take that was captured short settle to or from rest
    (see `compose`). Both are off by default: every caller opts in to exactly what it can label.

    Every clip is measured, reconciled onto one shared skeleton, and then composed. Using the first
    clip's proportions for the whole sentence would quietly reshape the others - a sign recorded in
    a differently calibrated session ends up with the wrong limb lengths inside its own stroke, and
    nothing says so.
    """
    if not clips:
        raise ComposeError("a sentence needs at least one sign with a recording")

    key: list[tuple[str, str, str, str, str]] = []
    for gloss, clip in clips:
        path = landmark_path(clip)
        if not path.exists():
            raise ComposeError(
                f"{gloss} has no landmark frames; re-ingest the capture for that sign"
            )
        stored_source = getattr(clip, "source_csv", "")
        source_capture = str(source_file(stored_source)) if stored_source else ""
        try:
            source_hash = hashlib.sha256(Path(source_capture).read_bytes()).hexdigest() if source_capture else ""
        except OSError as exc:
            raise ComposeError(f"{gloss}: source capture is missing; re-ingest it.") from exc
        key.append((gloss, str(path), clip.content_hash, source_capture, source_hash))

    cache_key = (tuple(key), ALGORITHM_VERSION, allow_neutral_fallback, allow_reviewed_direct)
    try:
        if cache_key in _rejected:
            message, blend_quality = _rejected[cache_key]
            raise ComposeError(message, blend_quality)
        try:
            composition, warnings = _compose_cached(*cache_key)
        except ComposeError as exc:
            if len(_rejected) >= _REJECTED_MAX:
                _rejected.pop(next(iter(_rejected)))
            _rejected[cache_key] = (str(exc), exc.blend_quality)
            raise
    except ComposeError:
        logger.warning(
            "avatar blend rejected",
            extra={
                "blend_status": "rejected",
                "blend_algorithm_version": ALGORITHM_VERSION,
                "blend_seam_count": max(len(key) - 1, 0),
            },
        )
        raise
    quality = composition.blend_quality
    seams = quality.get("seams", [])
    logger.info(
        "avatar blend completed",
        extra={
            "blend_status": quality.get("status"),
            "blend_score": quality.get("score"),
            "blend_algorithm_version": quality.get("algorithmVersion"),
            "blend_seam_count": len(seams),
            "blend_direct_count": sum(seam.get("mode") == "direct" for seam in seams),
            "blend_fallback_count": sum(
                seam.get("mode") == "neutral-fallback" for seam in seams
            ),
        },
    )
    return composition, list(warnings)


# Every status a playback surface may play. "rejected" is never among them.
PLAYABLE_STATUSES = frozenset({
    "direct", "neutral-fallback", "reviewed-direct", "caption-linear",
})


def _linear_transition(
    before: LandmarkTake, after: LandmarkTake, fps: float,
) -> LandmarkTake:
    """Create a short, deterministic bridge for caption playback.

    The full composer is deliberately exhaustive: it evaluates many candidate seams and rejects
    a bridge whose motion quality is not proven.  That work is right for authoring a reviewed
    sentence, but it made a subtitle plan with dozens of captions look permanently stuck.  Video
    playback instead needs a bounded operation.  The normalised captures share the avatar's
    playback coordinate system; interpolating a handful of frames avoids a one-frame pose jump while
    retaining the author-reviewed sign itself untouched.
    """
    frames = max(2, int(round(HOLD_SECONDS * fps)))
    weights = np.linspace(0.0, 1.0, frames + 2, dtype=np.float64)[1:-1]

    def between(left: np.ndarray, right: np.ndarray) -> np.ndarray:
        shape = (frames,) + (1,) * left.ndim
        values = weights.reshape(shape)
        return left[None] * (1.0 - values) + right[None] * values

    return LandmarkTake(
        name="caption-transition", fps=fps,
        pose=between(before.pose[-1], after.pose[0]),
        left_hand=between(before.left_hand[-1], after.left_hand[0]),
        right_hand=between(before.right_hand[-1], after.right_hand[0]),
        face_blendshapes=between(before.face_blendshapes[-1], after.face_blendshapes[0]),
    )


def compose_caption_sequence(clips: list[tuple[str, SignClip]]) -> tuple[Composition, list[str]]:
    """Build a prompt, timestamp-faithful track for one subtitle caption.

    This path is intentionally separate from :func:`compose_playable`.  It preserves each
    reviewer-selected **Sign** interval exactly and uses fixed-duration interpolation only between
    signs.  Unlike the authoring composer it never performs an unbounded seam search, which lets
    units become ready while the YouTube video is playing.  The payload is explicitly labelled
    ``caption-linear`` so it is never mistaken for a quality-optimised sentence blend.
    """
    if not clips:
        raise ComposeError("a caption needs at least one sign with a recording")

    raw: list[tuple[str, LandmarkTake]] = []
    for gloss, clip in clips:
        path = landmark_path(clip)
        if not path.exists():
            raise ComposeError(f"{gloss} has no landmark frames; re-ingest the capture for that sign")
        try:
            # Video plans consume immutable, normalised landmarks that were already checked
            # against their FBX at ingestion time.  Re-parsing an FBX for every caption costs
            # seconds per word and is what previously kept the first plan unit at 0/87.
            raw.append((gloss, _raw(str(path))))
        except (ValueError, OSError) as exc:
            raise ComposeError(f"{gloss}: {exc}") from exc

    signed: list[tuple[str, LandmarkTake]] = []
    expected_fps = raw[0][1].fps
    if expected_fps <= 0 or any(track.fps != expected_fps for _, track in raw):
        raise ComposeError("caption recordings must share the normalised 60 fps playback rate")
    for gloss, track in raw:
        phases = find_phases(track)
        # For reviewed takes this is exactly the hand-authored Sign range.  For a legacy take,
        # find_phases supplies the conservative detected span instead of silently dropping it.
        signed.append((gloss, slice_frames(track, phases.stroke_start, phases.stroke_end)))

    pieces: list[LandmarkTake] = []
    segments: list[Segment] = []
    seams: list[dict] = []
    cursor = 0
    for index, (gloss, track) in enumerate(signed):
        if index:
            transition = _linear_transition(signed[index - 1][1], track, expected_fps)
            pieces.append(transition)
            seams.append({
                "fromGloss": signed[index - 1][0], "toGloss": gloss,
                "fromFrame": cursor - 1, "toFrame": cursor + transition.frame_count,
                "mode": "caption-linear", "passed": True,
                "durationMs": int(round(transition.duration * 1000)),
            })
            segments.append(Segment("", cursor, cursor + transition.frame_count,
                                    "transition", "caption-linear"))
            cursor += transition.frame_count
        pieces.append(track)
        segments.append(Segment(gloss, cursor, cursor + track.frame_count, "sign",
                                "caption-linear", occurrence_index=index))
        cursor += track.frame_count

    composition = Composition(
        track=concat(pieces, name="caption-sequence"),
        segments=segments,
        blend_quality={
            "status": "caption-linear",
            "score": 0.0,
            "qualityAssessed": False,
            "algorithmVersion": ALGORITHM_VERSION,
            "seams": seams,
            "detail": "Reviewed sign spans joined by bounded linear caption transitions.",
        },
    )
    unreviewed = list(dict.fromkeys(gloss for gloss, track in raw if not track.phase_reviewed))
    source = (
        "saved Sign timestamps" if not unreviewed
        else "saved timestamps where available and automatically detected Sign intervals for: "
             + ", ".join(unreviewed)
    )
    return composition, [
        "Caption playback uses " + source
        + " with short deterministic transitions; use Sequence Review to create a fully "
          "quality-optimised sentence blend.",
    ]


def compose_playable(clips: list[tuple[str, SignClip]]) -> tuple[Composition, list[str]]:
    """The strictest composition that can play these reviewed recordings, escalating only on need.

    1. Direct - every join blended (including the uniform 80% retry in `_compose_cached`).
    2. Otherwise the same sentence with labelled fallbacks enabled: an unjoinable sign-to-sign pair
       passes through rest, and a take captured short settles to or from rest. Each seam still
       reports which strategy it used and which checks, if any, were waived.

    Corrupt or geometrically impossible motion is still refused: a settle is only accepted when
    every mandatory integrity check passes (see `blend.SETTLE_WAIVABLE_REASONS`).
    """
    try:
        return compose_clips(clips)
    except ComposeError:
        # If this also fails, its error carries the fallback attempts too - that is the answer.
        composition, warnings = compose_clips(
            clips, allow_neutral_fallback=True, allow_reviewed_direct=True,
        )
    status = composition.blend_quality.get("status")
    if status == "reviewed-direct":
        waived = sorted({
            reason for seam in composition.blend_quality.get("seams", [])
            for reason in seam.get("waivedChecks", [])
        })
        warnings = [
            *warnings,
            "Reviewed recording played with a settle to or from rest because the capture starts "
            "or ends in motion; waived boundary checks: " + "; ".join(waived) + ".",
        ]
    elif status == "neutral-fallback":
        warnings = [*warnings, "Unjoinable sign pair played through the rest pose."]
    return composition, warnings
