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
    TARGET_FPS,
    BlendRejected,
    Composition,
    compose,
    enforce_track,
    prepare,
)
from app.ingest.landmarks import LandmarkSkeleton, LandmarkTake
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
def _raw(clip_path: str, source_csv: str = "", source_hash: str = "") -> LandmarkTake:
    """Clip files are content-addressed, so this is safe to cache for the process lifetime."""
    if source_csv:
        return load_source_motion(Path(clip_path), source_csv)[0]
    return _load(clip_path)


def landmark_path(clip: SignClip) -> Path:
    return clip_file(clip.clip_path).parent / f"{clip.content_hash}.landmarks.json"


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
        sign_start_s=track.sign_start_s * stretch,
        sign_end_s=track.sign_end_s * stretch,
        timestamps=None,
    ))


@lru_cache(maxsize=128)
def _compose_cached(
    key: tuple[tuple[str, str, str, str, str], ...],
    algorithm_version: int,
) -> tuple[Composition, tuple[str, ...]]:
    """Cache immutable compositions by ordered content hashes and algorithm version."""
    raw = []
    for gloss, path, _content_hash, source_csv, source_hash in key:
        try:
            raw.append((gloss, _raw(path, source_csv, source_hash)))
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


def compose_clips(clips: list[tuple[str, SignClip]]) -> tuple[Composition, list[str]]:
    """Build the sentence track for `(gloss, clip)` pairs, in order.

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
        stored_csv = getattr(clip, "source_csv", "")
        source_csv = str(source_file(stored_csv)) if stored_csv else ""
        try:
            source_hash = hashlib.sha256(Path(source_csv).read_bytes()).hexdigest() if source_csv else ""
        except OSError as exc:
            raise ComposeError(f"{gloss}: source CSV is missing; re-ingest the capture.") from exc
        key.append((gloss, str(path), clip.content_hash, source_csv, source_hash))

    try:
        composition, warnings = _compose_cached(tuple(key), ALGORITHM_VERSION)
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
