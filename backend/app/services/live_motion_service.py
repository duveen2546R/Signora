"""Persistent motion artifacts and appendable live-track assembly."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
from functools import lru_cache
from pathlib import Path

import numpy as np

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingest.compose import ALGORITHM_VERSION
from app.ingest import landmarks as lm
from app.models import Gloss, LiveMotionArtifact, SignClip
from app.services.compose_service import ComposeError, compose_clips
from app.services.translate_service import PlaylistItem

CORE_GLOSSES = (
    "HELLO", "GOOD_MORNING", "NAMASTE", "THANKYOU", "FATHER", "MOTHER", "YES", "NO",
    "PLEASE", "SORRY", "HELP", "WANT", "NEED", "WATER", "FOOD", "HOME", "WORK", "SCHOOL",
    "DOCTOR", "HOSPITAL", "WHERE", "WHAT", "WHO", "WHEN", "HOW",
)
ALPHABET_GLOSSES = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
PUBLISHED_GLOSSES = CORE_GLOSSES + ALPHABET_GLOSSES


def canonical_clips(session: Session) -> list[SignClip]:
    return session.scalars(
        select(SignClip).join(Gloss).where(SignClip.is_canonical.is_(True)).order_by(Gloss.name)
    ).all()


def library_version(session: Session) -> str:
    rows = []
    for clip in canonical_clips(session):
        phases = (clip.qc or {}).get("phases", {})
        rows.append((clip.id, clip.gloss.name, clip.content_hash, phases, ALGORITHM_VERSION))
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:24]


def _artifact_key(version: str, clips: list[SignClip]) -> str:
    value = [version, ALGORITHM_VERSION, *[clip.content_hash for clip in clips]]
    return hashlib.sha256("|".join(map(str, value)).encode()).hexdigest()


def _artifact_path(key: str) -> Path:
    return settings.transition_dir / f"{key}.json.gz"


def playback_rate_limit(payload: dict) -> float:
    """Bound optional live speedup using measured wrist/limb speeds at the source fps.

    This is a mechanical cap, not a linguistic intelligibility certification.
    """
    fps = payload["fps"]
    pose = np.asarray(payload["pose"])
    if len(pose) < 2:
        return 1.0
    wrist_speed = np.max(np.linalg.norm(np.diff(pose[:, [15, 16]], axis=0), axis=-1)) * fps * 100
    peak_angle = 0.0
    for points, edges in [(pose, lm.POSE_BONES),
                          (np.asarray(payload["leftHand"]), lm.HAND_SPOKES + lm.HAND_BONES),
                          (np.asarray(payload["rightHand"]), lm.HAND_SPOKES + lm.HAND_BONES)]:
        vectors = np.stack([points[:, end] - points[:, start] for start, end in edges], axis=1)
        lengths = np.linalg.norm(vectors, axis=-1, keepdims=True)
        unit = vectors / np.maximum(lengths, 1e-8)
        dot = np.sum(unit[1:] * unit[:-1], axis=-1)
        valid = (lengths[1:, :, 0] > 1e-8) & (lengths[:-1, :, 0] > 1e-8)
        angles = np.degrees(np.arccos(np.clip(dot[valid], -1, 1))) * fps
        if angles.size:
            peak_angle = max(peak_angle, float(angles.max()))
    return round(max(1.0, min(1.5, 237.5 / max(float(wrist_speed), 1e-8),
                             684.0 / max(peak_angle, 1e-8))), 3)


@lru_cache(maxsize=64)
def _read_compiled(path: str, modified: int, size: int) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        payload = json.load(source)
    payload["maxPlaybackRate"] = playback_rate_limit(payload)
    return payload


def cached_composition(
    session: Session, clips: list[SignClip], version: str | None = None,
    retry_failed: bool = False,
    allow_compile: bool = False,
) -> tuple[dict, bool]:
    """Return a validated composition payload and whether it was already persisted."""
    version = version or library_version(session)
    key = _artifact_key(version, clips)
    path = _artifact_path(key)
    if path.exists():
        stat = path.stat()
        return _read_compiled(str(path), stat.st_mtime_ns, stat.st_size), True
    existing = session.get(LiveMotionArtifact, key)
    if existing is not None and existing.status == "failed" and not retry_failed:
        raise ComposeError(existing.error, existing.quality)
    if not allow_compile:
        raise ComposeError("Live motion is not compiled for " + " → ".join(c.gloss.name for c in clips)
                           + ". Prepare these recordings with compile_live_library.py before listening.")

    try:
        composition, warnings = compose_clips([(clip.gloss.name, clip) for clip in clips])
        payload = composition.to_payload()
        payload["warnings"] = warnings
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as target:
            json.dump(payload, target, separators=(",", ":"))
        os.replace(temporary, path)
        row = LiveMotionArtifact(
            key=key, library_version=version,
            from_clip_hash=clips[0].content_hash if len(clips) > 1 else "",
            to_clip_hash=clips[-1].content_hash,
            algorithm_version=ALGORITHM_VERSION, status="ready",
            artifact_path=str(path), quality=composition.blend_quality, error="",
        )
        session.merge(row)
        session.commit()
        return payload, False
    except ComposeError as exc:
        session.merge(LiveMotionArtifact(
            key=key, library_version=version,
            from_clip_hash=clips[0].content_hash if len(clips) > 1 else "",
            to_clip_hash=clips[-1].content_hash,
            algorithm_version=ALGORITHM_VERSION, status="failed", artifact_path="",
            quality=exc.blend_quality, error=str(exc),
        ))
        session.commit()
        raise


def _sign_segments(payload: dict) -> list[dict]:
    return [segment for segment in payload.get("segments", []) if segment.get("kind") == "sign"]


def _slice_payload(payload: dict, start: int, end: int, occurrence: int | str | None) -> dict:
    if end <= start:
        raise ComposeError("compiled live motion contains an empty range")
    result = {
        "fps": payload["fps"], "frameCount": end - start,
        "pose": payload["pose"][start:end],
        "leftHand": payload["leftHand"][start:end],
        "rightHand": payload["rightHand"][start:end],
        "segments": [], "blendQuality": payload.get("blendQuality", {}),
        "maxPlaybackRate": payload.get("maxPlaybackRate", 1.0),
    }
    if payload.get("neutral") is not None:
        result["neutral"] = payload["neutral"]
    for segment in payload.get("segments", []):
        lo, hi = max(segment["startFrame"], start), min(segment["endFrame"], end)
        if hi <= lo:
            continue
        item = {**segment, "startFrame": lo - start, "endFrame": hi - start}
        if occurrence == "preserve":
            pass
        elif occurrence is not None and item.get("gloss"):
            item["occurrenceIndex"] = occurrence
        else:
            item.pop("occurrenceIndex", None)
        result["segments"].append(item)
    return result


def _join_payloads(parts: list[dict], seams: list[dict]) -> dict:
    if not parts:
        raise ComposeError("live motion needs at least one part")
    result = {
        "fps": parts[0]["fps"], "frameCount": 0,
        "pose": [], "leftHand": [], "rightHand": [], "segments": [],
        "neutral": parts[0].get("neutral"),
        "maxPlaybackRate": min(part.get("maxPlaybackRate", 1.0) for part in parts),
    }
    cursor = 0
    for part in parts:
        if part["fps"] != result["fps"]:
            raise ComposeError("compiled live motion uses inconsistent frame rates")
        for channel in ("pose", "leftHand", "rightHand"):
            result[channel].extend(part[channel])
        for segment in part["segments"]:
            result["segments"].append({
                **segment,
                "startFrame": segment["startFrame"] + cursor,
                "endFrame": segment["endFrame"] + cursor,
            })
        cursor += part["frameCount"]
    result["frameCount"] = cursor
    result["blendQuality"] = {
        "status": "direct",
        "score": min((float(seam.get("score", 100)) for seam in seams), default=100.0),
        "algorithmVersion": ALGORITHM_VERSION,
        "seams": seams,
    }
    return result


def _matching_seam(payload: dict, from_gloss: str, to_gloss: str) -> dict:
    seam = next((item for item in payload.get("blendQuality", {}).get("seams", [])
                 if item.get("fromGloss", "") == from_gloss
                 and item.get("toGloss", "") == to_gloss), None)
    if seam is None or seam.get("passed") is not True or seam.get("mode") != "direct":
        raise ComposeError(f"No validated live transition from {from_gloss or 'rest'} to {to_gloss or 'rest'}.")
    return seam


def assemble_live_motion(
    session: Session,
    items: list[PlaylistItem],
    from_clip_id: int | None,
    version: str,
) -> tuple[dict, int | None, bool]:
    by_id = {clip.id: clip for clip in canonical_clips(session)}
    clips = []
    for item in items:
        clip = by_id.get(item.clip_id)
        if clip is None:
            raise ComposeError(f"Recording for {item.gloss} is no longer canonical.")
        clips.append(clip)
    previous = by_id.get(from_clip_id) if from_clip_id is not None else None
    if from_clip_id is not None and previous is None:
        raise ComposeError("The live stream tail recording is stale.")

    # The existing quality fallback slows a complete composition uniformly. A paced directed edge
    # cannot safely be appended after a normal-speed sign because its measured boundary velocity
    # would no longer match. Use one uniformly paced phrase when opening from rest; if a stream is
    # already open, close it visibly and reopen from rest rather than emitting an unvalidated seam.
    chain = ([previous] if previous is not None else []) + clips
    edge_payloads: list[tuple[dict, bool]] = []
    rejected_edge: ComposeError | None = None
    for left, right in zip(chain, chain[1:]):
        try:
            edge_payloads.append(cached_composition(session, [left, right], version))
        except ComposeError as exc:
            rejected_edge = exc
            break
    if rejected_edge is not None:
        parts: list[dict] = []
        seams: list[dict] = []
        all_cached = True
        if previous is not None:
            closure, hit = assemble_live_close(session, previous.id, version)
            parts.append(closure)
            seams.extend(closure["blendQuality"]["seams"])
            all_cached = all_cached and hit
        for occurrence, clip in enumerate(clips):
            payload, hit = cached_composition(session, [clip], version)
            parts.append(_slice_payload(payload, 0, payload["frameCount"], occurrence))
            seams.extend([
                _matching_seam(payload, "", clip.gloss.name),
                _matching_seam(payload, clip.gloss.name, ""),
            ])
            all_cached = all_cached and hit
        result = _join_payloads(parts, seams)
        result["warnings"] = [
            "Used explicit neutral rests because a directed transition was rejected: "
            + str(rejected_edge),
        ]
        return result, None, all_cached
    if any(payload.get("blendQuality", {}).get("playbackRate") == 0.8
           for payload, _hit in edge_payloads):
        if previous is not None:
            closure, close_hit = assemble_live_close(session, previous.id, version)
            opening, tail, open_hit = assemble_live_motion(session, items, None, version)
            seams = closure["blendQuality"]["seams"] + opening["blendQuality"]["seams"]
            result = _join_payloads([closure, opening], seams)
            result["warnings"] = [
                f"Used a safe neutral split before {clips[0].gloss.name}; the direct live edge "
                "requires phrase-wide 80% playback.",
            ]
            return result, tail, close_hit and open_hit
        try:
            payload, hit = cached_composition(session, clips, version)
        except ComposeError:
            # Publishing prepares singles/pairs, not every possible long sentence. Avoid an
            # exponential compilation requirement: use complete cached singles with explicit
            # rest boundaries when a uniformly paced long phrase has not been compiled.
            parts = []
            seams = []
            all_cached = True
            for occurrence, clip in enumerate(clips):
                single, hit = cached_composition(session, [clip], version)
                parts.append(_slice_payload(single, 0, single["frameCount"], occurrence))
                seams.extend([_matching_seam(single, "", clip.gloss.name),
                              _matching_seam(single, clip.gloss.name, "")])
                all_cached = all_cached and hit
            result = _join_payloads(parts, seams)
            result["warnings"] = ["This phrase needs a slower transition; using cached signs with rests between them."]
            return result, None, all_cached
        signs = _sign_segments(payload)
        if len(signs) != len(clips):
            raise ComposeError("compiled paced phrase has invalid sign segmentation")
        part = _slice_payload(payload, 0, signs[-1]["endFrame"], "preserve")
        seams = [
            _matching_seam(payload, "" if index == 0 else clips[index - 1].gloss.name,
                           clip.gloss.name)
            for index, clip in enumerate(clips)
        ]
        part["blendQuality"] = {
            "status": "direct", "score": min(float(seam.get("score", 100)) for seam in seams),
            "algorithmVersion": ALGORITHM_VERSION, "seams": seams, "playbackRate": 0.8,
        }
        return part, clips[-1].id, hit and all(edge_hit for _edge, edge_hit in edge_payloads)

    parts: list[dict] = []
    seams: list[dict] = []
    all_cached = True
    for occurrence, clip in enumerate(clips):
        if previous is None:
            payload, hit = cached_composition(session, [clip], version)
            signs = _sign_segments(payload)
            if len(signs) != 1:
                raise ComposeError("compiled opening has invalid sign segmentation")
            parts.append(_slice_payload(payload, 0, signs[0]["endFrame"], occurrence))
            seams.append(_matching_seam(payload, "", clip.gloss.name))
        else:
            payload, hit = cached_composition(session, [previous, clip], version)
            signs = _sign_segments(payload)
            if len(signs) != 2:
                raise ComposeError("compiled transition has invalid sign segmentation")
            parts.append(_slice_payload(
                payload, signs[0]["endFrame"], signs[1]["endFrame"], occurrence,
            ))
            seams.append(_matching_seam(payload, previous.gloss.name, clip.gloss.name))
        all_cached = all_cached and hit
        previous = clip
    return _join_payloads(parts, seams), clips[-1].id, all_cached


def assemble_live_close(session: Session, from_clip_id: int, version: str) -> tuple[dict, bool]:
    clip = session.get(SignClip, from_clip_id)
    if clip is None or not clip.is_canonical:
        raise ComposeError("The live stream tail recording is stale.")
    payload, hit = cached_composition(session, [clip], version)
    signs = _sign_segments(payload)
    if len(signs) != 1:
        raise ComposeError("compiled closure has invalid sign segmentation")
    part = _slice_payload(payload, signs[0]["endFrame"], payload["frameCount"], None)
    seam = _matching_seam(payload, clip.gloss.name, "")
    return _join_payloads([part], [seam]), hit


def readiness(session: Session) -> dict:
    version = library_version(session)
    clips = canonical_clips(session)
    by_name = {clip.gloss.name: clip for clip in clips}
    missing_core = [name for name in CORE_GLOSSES if name not in by_name]
    missing_alphabet = [name for name in ALPHABET_GLOSSES if name not in by_name]
    published_hashes = {by_name[name].content_hash for name in PUBLISHED_GLOSSES if name in by_name}
    expected_pairs = {(left, right) for left in published_hashes for right in published_hashes}
    rows = session.scalars(select(LiveMotionArtifact).where(
        LiveMotionArtifact.from_clip_hash.in_(published_hashes),
        LiveMotionArtifact.to_clip_hash.in_(published_hashes),
    )).all() if published_hashes else []
    current_rows = [row for row in rows if row.library_version == version]
    ready_pairs = sum(
        row.status == "ready" and Path(row.artifact_path).exists()
        and (row.from_clip_hash, row.to_clip_hash) in expected_pairs
        for row in current_rows
    )
    failed = [{"from": row.from_clip_hash, "to": row.to_clip_hash, "error": row.error}
              for row in current_rows if row.status == "failed"]
    stale = sum(row.library_version != version or (
        row.status == "ready" and not Path(row.artifact_path).exists()
    ) for row in rows)
    required = len(PUBLISHED_GLOSSES) ** 2
    return {
        "ready": not missing_core and not missing_alphabet and ready_pairs >= required and not failed,
        "usable": bool(clips), "libraryVersion": version,
        "availableGlosses": sorted(by_name),
        "missingCoreGlosses": missing_core, "missingAlphabetGlosses": missing_alphabet,
        "compiledTransitions": ready_pairs, "requiredTransitions": required,
        "staleArtifacts": stale, "failedTransitions": failed,
        "algorithmVersion": ALGORITHM_VERSION,
    }
