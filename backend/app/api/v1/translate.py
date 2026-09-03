from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.services.translate_service import build_playlist

router = APIRouter(tags=["translate"])


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.post("/translate")
def translate(body: TranslateRequest, session: Session = Depends(get_session)):
    items, unmapped = build_playlist(session, body.text)
    return {
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
        "totalMs": sum(i.duration_ms + i.transition_ms for i in items),
    }
