from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import threading
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import SessionLocal
from app.ingest.compose import ALGORITHM_VERSION
from app.models import Gloss, SignClip, VideoPlan, VideoPlanUnit
from app.services.compose_service import PLAYABLE_STATUSES, ComposeError, compose_caption_sequence
from app.services.function_words import letter_gloss, match_phrases, may_fingerspell, plan_function_words
from app.services.live_motion_service import library_version
from app.services.live_translate_service import _aliases, alias_lookup
from app.services.plurals import load_plural_rules, plural_issue, resolve_plural
from app.services.subtitle_service import TranslationUnit
from app.services.translate_service import Interpretation, PlaylistItem, interpret, load_registry

# 2: YouTube captions use reviewed Sign spans plus bounded transitions, so one long subtitle plan
#    never blocks on the authoring composer's exhaustive seam search.
# 3: function words follow the shared `function_words` policy (contractions expanded, do-support
#    omitted, letter references and "a hundred" kept as meaning).
# 4: an ordinary plural with no stated quantity is signed BASE + MANY (`plurals`).
# 5: video captions use timestamp-faithful bounded composition rather than the authoring search.
# 6: legacy clips with an automatically detected usable Sign interval remain playable, with an
#    explicit notice, instead of rejecting every caption containing one.
POLICY_VERSION = 6
PLAN_PREPARATION_STALE_AFTER = dt.timedelta(minutes=2)

# Plan preparation runs in worker threads owned by this module, not in the request's background
# task: uvicorn waits for a request's background task before it will shut down, so Ctrl+C on a
# server composing a long video used to hang, and a second Ctrl+C cancelled the request while its
# thread kept composing. Workers now stop at the next caption unit when the server shuts down.
_stopping = threading.Event()
_workers: set[threading.Thread] = set()
_workers_lock = threading.Lock()
INTERRUPTED_ERROR = "The backend stopped while preparing this plan; retry to start a new plan."


class PreparationStopped(Exception):
    pass


def start_preparation(plan_id: str) -> threading.Thread:
    """Prepare `plan_id` in a daemon worker thread; the caller polls the plan for progress."""
    def run() -> None:
        try:
            prepare_plan(plan_id)
        finally:
            with _workers_lock:
                _workers.discard(threading.current_thread())

    worker = threading.Thread(target=run, name=f"video-plan-{plan_id[:8]}", daemon=True)
    with _workers_lock:
        _workers.add(worker)
    worker.start()
    return worker


def stop_preparations(timeout: float = 5.0) -> None:
    """Server shutdown: ask workers to stop after their current unit, and wait briefly for them
    to record the plan as interrupted. A worker still composing after `timeout` is a daemon thread
    and ends with the process; `recover_interrupted_plans` tidies its plan on the next start."""
    _stopping.set()
    with _workers_lock:
        workers = list(_workers)
    deadline = dt.datetime.now() + dt.timedelta(seconds=timeout)
    for worker in workers:
        worker.join(max(0.0, (deadline - dt.datetime.now()).total_seconds()))


def recover_interrupted_plans() -> int:
    """Server start: no worker survives a restart of this single-process server, so any plan
    still pending or processing was interrupted. Mark it failed at once, instead of leaving retries
    attached to it until it is two minutes old."""
    _stopping.clear()
    with SessionLocal() as session:
        plans = session.scalars(select(VideoPlan).where(
            VideoPlan.status.in_(("pending", "processing")))).all()
        for plan in plans:
            plan.status = "failed"
            plan.error = INTERRUPTED_ERROR
            plan.finished_at = dt.datetime.now(dt.UTC)
        session.commit()
        return len(plans)


def policy_version() -> int:
    """Caption policy identity for plan reuse; editing plural_rules.json makes old plans stale."""
    return POLICY_VERSION * 1000 + load_plural_rules().version


def resolve_caption(session: Session, text: str) -> Interpretation:
    """Registry first; conservative literal fallback suitable for subtitle units."""
    registry = load_registry()
    exact = interpret(session, text, registry)
    if exact.status in {"ready", "preview"} and exact.items:
        exact.status = "ready" if exact.status == "ready" else "literal-preview"
        return exact

    recordings = session.scalars(
        select(SignClip).join(Gloss).where(SignClip.is_canonical.is_(True))
        .order_by(SignClip.created_at.desc(), SignClip.id.desc())
    ).all()
    by_gloss: dict[str, SignClip] = {}
    for clip in recordings:
        by_gloss.setdefault(clip.gloss.name, clip)

    plan = plan_function_words(text)
    omitted = [plan.issue()] if plan.issue() else []
    if not plan.tokens:
        return Interpretation("function-only", registry.version, pattern_id="caption-policy", issues=[{
            "code": "function-only", "message": "This unit contains only contextual function words.",
        }, *omitted])

    aliases = _aliases(registry, by_gloss)
    lookup = alias_lookup(aliases)
    resolved: list[tuple[str, str, bool]] = []
    missing_words: list[str] = []
    plural_words: list[str] = []
    seen: list[str] = []
    for token, phrase, glosses in match_phrases(plan.tokens, aliases, accept=lambda g: len(g) == 1):
        plural = None
        if glosses is None and token.kind == "word":
            plural = resolve_plural(token.text, seen, lookup, by_gloss.__contains__)
        seen.extend(phrase or (token.text,))
        if glosses is not None:
            resolved.append((glosses[0], " ".join(phrase), False))
        elif plural is not None:
            resolved.extend((gloss, token.text, False) for gloss in plural.glosses)
            if plural.marked and not plural.reviewed:
                plural_words.append(token.text)
        elif token.kind == "letter":
            if letter_gloss(token) in by_gloss:
                resolved.append((letter_gloss(token), token.source, True))
            else:
                missing_words.append(token.source)
        else:
            word = token.text
            letters = [letter.upper() for letter in word if letter.isalpha()]
            if may_fingerspell(token) and letters and all(letter in by_gloss for letter in letters):
                resolved.extend((letter, word, True) for letter in letters)
            else:
                missing_words.append(word)
    if missing_words:
        return Interpretation("unsupported", registry.version, pattern_id="caption-policy",
                              unmapped=missing_words, issues=[{
            "code": "unsupported-unit", "sourceWords": missing_words,
            "message": "The complete subtitle unit was skipped because some words have no sign and the A-Z alphabet is incomplete.",
        }, *omitted])
    result = Interpretation("literal-preview", registry.version, pattern_id="caption-policy",
                            issues=omitted)
    if plural_issue(plural_words):
        result.issues.append(plural_issue(plural_words))
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
    existing_plans = session.scalars(select(VideoPlan).where(
        VideoPlan.youtube_video_id == video_id,
        VideoPlan.subtitle_hash == subtitle_hash,
        VideoPlan.policy_version == policy_version(),
        VideoPlan.pattern_version == registry.version,
        VideoPlan.library_version == version,
        VideoPlan.motion_algorithm_version == ALGORITHM_VERSION,
        # Retry must attach to the active plan instead of launching another expensive
        # composition job for the same video and subtitle bytes.
        VideoPlan.status.in_(("pending", "processing", "ready")),
    ).order_by(VideoPlan.created_at.desc())).all()
    # SQLite returns DateTime columns without tzinfo. A plan that outlives its worker (for
    # example after a development-server restart) otherwise remains "processing" forever and
    # every retry attaches to it. Leave a live job alone, but retire one that is clearly orphaned.
    stale_before = dt.datetime.now(dt.UTC).replace(tzinfo=None) - PLAN_PREPARATION_STALE_AFTER
    for existing in existing_plans:
        if existing.status == "ready":
            return existing, True
        if existing.created_at >= stale_before:
            return existing, True
        existing.status = "failed"
        existing.error = "Preparation worker stopped before completing this plan; retry to start a new plan."
        existing.finished_at = dt.datetime.now(dt.UTC)
        session.commit()
    plan = VideoPlan(
        id=str(uuid.uuid4()), youtube_video_id=video_id, subtitle_hash=subtitle_hash,
        status="pending", policy_version=policy_version(), pattern_version=registry.version,
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
                if _stopping.is_set():
                    raise PreparationStopped(INTERRUPTED_ERROR)
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
                    detected_phase_glosses = []
                    for item in interpretation.items:
                        clip = by_id.get(item.clip_id)
                        if clip is None:
                            raise ComposeError(f"{item.gloss} has no recording.")
                        if not (clip.qc or {}).get("phases", {}).get("reviewed"):
                            detected_phase_glosses.append(item.gloss)
                        ordered.append((item.gloss, clip))
                    composition, warnings = compose_caption_sequence(ordered)
                    status = composition.blend_quality.get("status")
                    if status not in PLAYABLE_STATUSES:
                        raise ComposeError("Sentence transitions did not pass validation.", composition.blend_quality)
                    payload = composition.to_payload()
                    unit.motion_path = str(_artifact_path(payload, [clip for _, clip in ordered], plan.library_version))
                    unit.motion_duration_ms = int(payload["frameCount"] / payload["fps"] * 1000)
                    if status != "direct":
                        # Playable, but not a fully quality-optimised sentence blend - say how it
                        # was joined rather than presenting it as a reviewed sentence translation.
                        unit.issues = [*unit.issues, {
                            "code": "motion-fallback", "blendStatus": status,
                            "message": "Played with a labelled transition fallback "
                                       f"({status}); see the seam details for what was waived.",
                        }]
                    if detected_phase_glosses:
                        unit.issues = [*unit.issues, {
                            "code": "detected-phase-playback",
                            "glosses": list(dict.fromkeys(detected_phase_glosses)),
                            "message": "Used an automatically detected Sign interval for: "
                                       + ", ".join(dict.fromkeys(detected_phase_glosses))
                                       + ". Review its Start, Sign and End timestamps to replace this fallback.",
                        }]
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
        plan.policy_version != policy_version()
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
