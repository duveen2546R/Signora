"""Turn a resolved playlist into one continuous landmark track.

Composing here rather than in the browser keeps the geometry work next to the machinery that
already exists for it, and leaves the player with a single track to stream - no queue, and so no
gap at a sign boundary. The runtime starts pulling a channel back toward its bind pose as soon as
frames are more than 0.2s old, which is exactly what a stitching gap produces.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from app.ingest.compose import (
    ALGORITHM_VERSION,
    TARGET_FPS,
    BlendRejected,
    Composition,
    compose,
    prepare,
)
from app.ingest.landmarks import LandmarkSkeleton, LandmarkTake
from app.models import SignClip


class ComposeError(ValueError):
    pass


logger = logging.getLogger(__name__)


def _load(path: str) -> LandmarkTake:
    payload = json.loads(Path(path).read_text())
    return LandmarkTake.from_payload(payload)


# A clip whose measured proportions differ from the rest of the sentence by more than this is
# reported rather than silently reshaped. A 5% difference in forearm length shows up as 14 mm of
# error inside that sign's own stroke.
SKELETON_TOLERANCE_M = 0.004


@lru_cache(maxsize=64)
def _raw(clip_path: str) -> LandmarkTake:
    """Clip files are content-addressed, so this is safe to cache for the process lifetime."""
    return _load(clip_path)


def landmark_path(clip: SignClip) -> Path:
    return Path(clip.clip_path).parent / f"{clip.content_hash}.landmarks.json"


@lru_cache(maxsize=128)
def _compose_cached(
    key: tuple[tuple[str, str, str], ...],
    algorithm_version: int,
) -> tuple[Composition, tuple[str, ...]]:
    """Cache immutable compositions by ordered content hashes and algorithm version."""
    raw = [(gloss, _raw(path)) for gloss, path, _content_hash in key]
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

    prepared = [(gloss, prepare(track, shared, fps=TARGET_FPS)) for gloss, track in raw]
    try:
        composition = compose(
            shared, prepared, fps=TARGET_FPS, algorithm_version=algorithm_version,
        )
    except BlendRejected as exc:
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

    key: list[tuple[str, str, str]] = []
    for gloss, clip in clips:
        path = landmark_path(clip)
        if not path.exists():
            raise ComposeError(
                f"{gloss} has no landmark frames; re-ingest the capture for that sign"
            )
        key.append((gloss, str(path), clip.content_hash))

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
