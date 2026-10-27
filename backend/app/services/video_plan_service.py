from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import SessionLocal
from app.ingest.compose import ALGORITHM_VERSION
from app.models import Gloss, SignClip, VideoPlan, VideoPlanUnit
from app.services.compose_service import ComposeError, compose_clips
from app.services.live_motion_service import library_version
from app.services.live_translate_service import _aliases
from app.services.subtitle_service import TranslationUnit
from app.services.translate_service import Interpretation, PlaylistItem, interpret, load_registry, normalise

POLICY_VERSION = 1
ARTICLES = {"a", "an", "the"}
REMOVABLE_COPULAS = {"am", "is", "are"}
QUESTION_WORDS = {"who", "what", "when", "where", "why", "how", "which", "whose"}
NEGATIONS = {"not", "no", "never", "neither", "nor"}


def resolve_caption(session: Session, text: str) -> Interpretation:
    """Registry first; conservative literal fallback suitable for subtitle units."""
    registry = load_registry()
    exact = interpret(session, text, registry)
    if exact.status in {"ready", "preview"} and exact.items:
        exact.status = "ready" if exact.status == "ready" else "literal-preview"
        return exact

    normalized = normalise(text)
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", normalized)
    recordings = session.scalars(
        select(SignClip).join(Gloss).where(SignClip.is_canonical.is_(True))
        .order_by(SignClip.created_at.desc(), SignClip.id.desc())
    ).all()
    by_gloss: dict[str, SignClip] = {}
    for clip in recordings:
        by_gloss.setdefault(clip.gloss.name, clip)

    retained = [word for word in words if word not in ARTICLES]
    has_question = "?" in normalized or bool(QUESTION_WORDS.intersection(words))
    has_negation = bool(NEGATIONS.intersection(words)) or any("n't" in word for word in words)
    copula_removable = not has_question and not has_negation and len(retained) >= 3
    if copula_removable:
        retained = [word for word in retained if word not in REMOVABLE_COPULAS]
    if not retained:
        return Interpretation("function-only", registry.version, pattern_id="caption-policy", issues=[{
            "code": "function-only", "message": "This unit contains only contextual function words.",
        }])

    aliases = _aliases(registry, by_gloss)
    resolved: list[tuple[str, str, bool]] = []
    missing_words: list[str] = []
    at = 0
    while at < len(retained):
        matched = next((entry for entry in aliases
                        if tuple(retained[at:at + len(entry[0])]) == entry[0]), None)
        if matched and len(matched[1]) == 1:
            phrase, glosses = matched
            resolved.append((glosses[0], " ".join(phrase), False))
            at += len(phrase)
            continue
        word = retained[at]
        letters = [letter.upper() for letter in word if letter.isalpha()]
        if letters and all(letter in by_gloss for letter in letters):
            resolved.extend((letter, word, True) for letter in letters)
        else:
            missing_words.append(word)
        at += 1
    if missing_words:
        return Interpretation("unsupported", registry.version, pattern_id="caption-policy",
                              unmapped=missing_words, issues=[{
            "code": "unsupported-unit", "sourceWords": missing_words,
            "message": "The complete subtitle unit was skipped because some words have no sign and the A-Z alphabet is incomplete.",
        }])
    result = Interpretation("literal-preview", registry.version, pattern_id="caption-policy")
    for gloss, source, spelled in resolved:
        clip = by_gloss[gloss]
        result.items.append(PlaylistItem(
            gloss=gloss, clip_id=clip.id, duration_ms=int(clip.duration * 1000),
            fingerspelled=spelled, source_word=source, occurrence_index=len(result.items),
        ))
    result.issues.append({
        "code": "literal-caption-preview",
        "message": "Literal recorded-sign preview; this wording has not been linguistically reviewed as an ISL sentence.",
    })
    return result


def create_plan(session: Session, video_id: str, subtitle_hash: str,
                units: list[TranslationUnit]) -> tuple[VideoPlan, bool]:
    registry = load_registry()
    version = library_version(session)
    existing = session.scalar(select(VideoPlan).where(
        VideoPlan.youtube_video_id == video_id,
        VideoPlan.subtitle_hash == subtitle_hash,
        VideoPlan.policy_version == POLICY_VERSION,
        VideoPlan.pattern_version == registry.version,
        VideoPlan.library_version == version,
        VideoPlan.motion_algorithm_version == ALGORITHM_VERSION,
        VideoPlan.status == "ready",
    ).order_by(VideoPlan.created_at.desc()))
    if existing:
        return existing, True
    plan = VideoPlan(
        id=str(uuid.uuid4()), youtube_video_id=video_id, subtitle_hash=subtitle_hash,
        status="pending", policy_version=POLICY_VERSION, pattern_version=registry.version,
        library_version=version, motion_algorithm_version=ALGORITHM_VERSION,
        total_units=len(units),
    )
    for unit in units:
        plan.units.append(VideoPlanUnit(
            ordinal=unit.ordinal, start_ms=unit.start_ms, end_ms=unit.end_ms,
            source_text=unit.text, normalized_text=unit.normalized_text,
            source_cue_ids=unit.cue_ids,
        ))
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan, False


def _artifact_path(payload: dict, clips: list[SignClip], version: str) -> Path:
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    identity = "|".join([version, str(ALGORITHM_VERSION), *[clip.content_hash for clip in clips]]).encode()
    # The payload hash also covers ordered gloss/segment labels, facial channels, and timing.
    key = hashlib.sha256(identity + b"|" + hashlib.sha256(encoded).digest()).hexdigest()
    path = settings.video_plan_dir / f"{key}.json.gz"
    if not path.exists():
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(gzip.compress(encoded))
        temporary.replace(path)
    return path


def prepare_plan(plan_id: str) -> None:
    with SessionLocal() as session:
        plan = session.scalar(select(VideoPlan).options(selectinload(VideoPlan.units))
                              .where(VideoPlan.id == plan_id))
        if not plan or plan.status != "pending":
            return
        plan.status = "processing"
        session.commit()
        try:
            for unit in plan.units:
                interpretation = resolve_caption(session, unit.source_text)
                unit.status = interpretation.status
                unit.glosses = [item.gloss for item in interpretation.items]
                unit.fingerspelled_words = list(dict.fromkeys(
                    item.source_word for item in interpretation.items if item.fingerspelled
                ))
                unit.issues = interpretation.issues
                if interpretation.status not in {"ready", "literal-preview"} or not interpretation.items:
                    continue
                clips = session.scalars(select(SignClip).where(
                    SignClip.id.in_([item.clip_id for item in interpretation.items])
                )).all()
                by_id = {clip.id: clip for clip in clips}
                try:
                    ordered = []
                    for item in interpretation.items:
                        clip = by_id.get(item.clip_id)
                        if clip is None or not (clip.qc or {}).get("phases", {}).get("reviewed"):
                            raise ComposeError(f"{item.gloss} needs reviewed phase timestamps.")
                        ordered.append((item.gloss, clip))
                    composition, warnings = compose_clips(ordered)
                    if composition.blend_quality.get("status") != "direct":
                        raise ComposeError("Sentence transitions did not pass validation.", composition.blend_quality)
                    payload = composition.to_payload()
                    unit.motion_path = str(_artifact_path(payload, [clip for _, clip in ordered], plan.library_version))
                    unit.motion_duration_ms = int(payload["frameCount"] / payload["fps"] * 1000)
                    if warnings:
                        unit.issues = [*unit.issues, *({"code": "motion-warning", "message": w} for w in warnings)]
                except ComposeError as exc:
                    unit.status = "motion-rejected"
                    unit.motion_path = ""
                    unit.issues = [*unit.issues, {"code": "motion-rejected", "message": str(exc)}]
                session.commit()
            playable = [unit for unit in plan.units if unit.motion_path]
            eligible = [unit for unit in plan.units if unit.status != "function-only"]
            plan.signed_units = len(playable)
            plan.fingerspelled_units = sum(bool(unit.fingerspelled_words) for unit in playable)
            plan.function_only_units = sum(unit.status == "function-only" for unit in plan.units)
            plan.unsupported_units = sum(unit.status in {"unsupported", "motion-rejected"} for unit in plan.units)
            plan.coverage = round(100 * len(playable) / len(eligible), 1) if eligible else 100.0
            plan.status = "ready"
        except Exception as exc:  # keep background failures visible to the client
            plan.status = "failed"
            plan.error = str(exc)
        plan.finished_at = dt.datetime.now(dt.UTC)
        session.commit()


def serialize_plan(plan: VideoPlan, session: Session) -> dict:
    stale = (
        plan.policy_version != POLICY_VERSION
        or plan.pattern_version != load_registry().version
        or plan.motion_algorithm_version != ALGORITHM_VERSION
        or plan.library_version != library_version(session)
    )
    return {
        "id": plan.id, "status": plan.status, "youtubeVideoId": plan.youtube_video_id,
        "language": plan.language, "stale": stale, "error": plan.error,
        "coverage": {
            "percent": plan.coverage, "totalUnits": plan.total_units,
            "signedUnits": plan.signed_units, "fingerspelledUnits": plan.fingerspelled_units,
            "functionOnlyUnits": plan.function_only_units, "unsupportedUnits": plan.unsupported_units,
        },
        "versions": {
            "policy": plan.policy_version, "patterns": plan.pattern_version,
            "library": plan.library_version, "motionAlgorithm": plan.motion_algorithm_version,
        },
        "units": [{
            "id": unit.id, "ordinal": unit.ordinal, "startMs": unit.start_ms, "endMs": unit.end_ms,
            "text": unit.source_text, "normalizedText": unit.normalized_text,
            "status": unit.status, "glosses": unit.glosses,
            "fingerspelledWords": unit.fingerspelled_words, "issues": unit.issues,
            "sourceCueIds": unit.source_cue_ids, "motionDurationMs": unit.motion_duration_ms,
            "motionAvailable": bool(unit.motion_path),
            "motionUrl": f"/api/v1/video-plans/{plan.id}/units/{unit.id}/motion" if unit.motion_path else None,
        } for unit in plan.units],
    }
