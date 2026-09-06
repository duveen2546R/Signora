from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.models import SignClip
from app.services.compose_service import ComposeError
from app.services.live_motion_service import (
    assemble_live_close,
    assemble_live_motion,
    library_version,
    readiness,
)
from app.services.live_translate_service import interpret_live
from app.services.translate_service import normalise

router = APIRouter(tags=["live"])


class LiveTranslateRequest(BaseModel):
    streamId: str = Field(min_length=1, max_length=100)
    sequence: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=500)
    fromClipId: int | None = None
    libraryVersion: str = Field(min_length=1, max_length=64)


class LiveCloseRequest(BaseModel):
    streamId: str = Field(min_length=1, max_length=100)
    sequence: int = Field(ge=0)
    fromClipId: int
    libraryVersion: str = Field(min_length=1, max_length=64)


def _check_version(requested: str, session: Session) -> str:
    current = library_version(session)
    if requested != current:
        raise HTTPException(409, "The live motion library changed; refresh readiness and restart from neutral.")
    return current


@router.get("/live/readiness")
def live_readiness(session: Session = Depends(get_session)):
    return readiness(session)


@router.post("/live/translate")
def live_translate(body: LiveTranslateRequest, session: Session = Depends(get_session)):
    version = _check_version(body.libraryVersion, session)
    if body.fromClipId is not None:
        tail = session.get(SignClip, body.fromClipId)
        if tail is None or not tail.is_canonical:
            raise HTTPException(409, "The live stream tail recording is stale; restart from neutral.")
    interpretation = interpret_live(session, body.text)
    motion, tail, cache_hit, error = None, body.fromClipId, False, None
    issues = list(interpretation.issues)
    if interpretation.status in {"ready", "preview"} and interpretation.items:
        try:
            motion, tail, cache_hit = assemble_live_motion(
                session, interpretation.items, body.fromClipId, version,
            )
            issues.extend({"code": "continuity-degraded", "message": warning}
                          for warning in motion.get("warnings", []))
        except ComposeError as exc:
            error = str(exc)
            issues.append({"code": "motion-rejected", "message": error})
    return {
        "streamId": body.streamId, "sequence": body.sequence,
        "text": body.text, "normalizedText": normalise(body.text),
        "translationStatus": interpretation.status,
        "patternId": interpretation.pattern_id, "patternVersion": interpretation.version,
        "items": [{
            "gloss": item.gloss, "clipId": item.clip_id,
            "durationMs": item.duration_ms, "transitionMs": item.transition_ms,
            "fingerspelled": item.fingerspelled, "sourceWord": item.source_word,
            "occurrenceIndex": item.occurrence_index,
        } for item in interpretation.items],
        "unmapped": interpretation.unmapped, "issues": issues,
        "motion": motion, "tailClipId": tail, "libraryVersion": version,
        "cacheHit": cache_hit, "error": error,
    }


@router.post("/live/close")
def live_close(body: LiveCloseRequest, session: Session = Depends(get_session)):
    version = _check_version(body.libraryVersion, session)
    try:
        motion, cache_hit = assemble_live_close(session, body.fromClipId, version)
    except ComposeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "streamId": body.streamId, "sequence": body.sequence,
        "motion": motion, "tailClipId": None, "libraryVersion": version,
        "cacheHit": cache_hit,
    }
