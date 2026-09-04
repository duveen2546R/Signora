from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from sqlalchemy import select

from app.core.db import get_session
from app.ingest.compose import ALGORITHM_VERSION
from app.models import SignClip
from app.services.compose_service import ComposeError, compose_clips
from app.services.translate_service import build_playlist

router = APIRouter(tags=["translate"])


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.post("/translate")
def translate(body: TranslateRequest, session: Session = Depends(get_session)):
    """Resolve text to signs and return the sentence as one continuous landmark track.

    The track is composed rather than concatenated: each sign contributes only its stroke, and the
    movement between strokes is generated. Playing the recordings back to back instead would restart
    every word from the performer's resting posture and snap between poses at each boundary.
    """
    items, unmapped = build_playlist(session, body.text)

    track = None
    error = None
    warnings: list[str] = []
    blend_quality = None
    resolved = [i for i in items if i.clip_id is not None]
    if resolved:
        clips = session.scalars(
            select(SignClip).where(SignClip.id.in_([i.clip_id for i in resolved]))
        ).all()
        by_id = {c.id: c for c in clips}
        try:
            composition, warnings = compose_clips(
                [(i.gloss, by_id[i.clip_id]) for i in resolved]
            )
            track = composition.to_payload()
            blend_quality = composition.blend_quality
        except (ComposeError, KeyError) as exc:
            error = str(exc)
            blend_quality = {
                "status": "rejected",
                "score": 0.0,
                "algorithmVersion": ALGORITHM_VERSION,
                "seams": [],
            }

    return {
        "track": track,
        "error": error,
        "warnings": warnings,
        "blendQuality": blend_quality,
        "text": body.text,
        "items": [
            {
                "gloss": i.gloss, "clipId": i.clip_id, "durationMs": i.duration_ms,
                "transitionMs": i.transition_ms, "fingerspelled": i.fingerspelled,
                "sourceWord": i.source_word,
            }
            for i in items
        ],
        "unmapped": unmapped,
        "totalMs": int(track["frameCount"] / track["fps"] * 1000) if track else 0,
    }
