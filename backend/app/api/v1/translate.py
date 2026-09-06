from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.models import SignClip
from app.services.compose_service import ComposeError, compose_clips
from app.services.translate_service import interpret, load_registry

router = APIRouter(tags=["translate"])


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.get("/translate/patterns")
def patterns():
    """Expose review state and supported examples; approval is a version-controlled review."""
    return load_registry().model_dump()


@router.post("/translate")
def translate(body: TranslateRequest, session: Session = Depends(get_session)):
    interpretation = interpret(session, body.text)
    items = interpretation.items
    track, error, blend_quality = None, None, None
    warnings: list[str] = []
    issues = list(interpretation.issues)
    if interpretation.status in {"ready", "preview"} and items:
        clips = session.scalars(
            select(SignClip).where(SignClip.id.in_([i.clip_id for i in items]))
        ).all()
        by_id = {c.id: c for c in clips}
        try:
            for item in items:
                clip = by_id.get(item.clip_id)
                if clip is None:
                    raise ComposeError(f"Recording for {item.gloss} is no longer available.")
                if not (clip.qc or {}).get("phases", {}).get("reviewed"):
                    issues.append({"code": "phase-review-required", "clipId": clip.id,
                                   "message": f"Review phase timestamps for {item.gloss}."})
                    raise ComposeError(f"Review phase timestamps for {item.gloss}.")
            composition, warnings = compose_clips([(i.gloss, by_id[i.clip_id]) for i in items])
            blend_quality = composition.blend_quality
            if blend_quality.get("status") != "direct":
                raise ComposeError("Sentence transitions did not pass validation.", blend_quality)
            track = composition.to_payload()
        except ComposeError as exc:
            error = str(exc)
            blend_quality = exc.blend_quality
            issues.append({"code": "motion-rejected", "message": error})
    return {
        "language": "ISL",
        "translationStatus": interpretation.status,
        "patternId": interpretation.pattern_id, "patternVersion": interpretation.version,
        "issues": issues, "track": track, "error": error, "warnings": warnings,
        "blendQuality": blend_quality, "text": body.text,
        "items": [{
            "gloss": i.gloss, "clipId": i.clip_id, "durationMs": i.duration_ms,
            "transitionMs": i.transition_ms, "fingerspelled": i.fingerspelled,
            "sourceWord": i.source_word, "occurrenceIndex": i.occurrence_index,
        } for i in items],
        "unmapped": interpretation.unmapped,
        "totalMs": int(track["frameCount"] / track["fps"] * 1000) if track else 0,
    }
