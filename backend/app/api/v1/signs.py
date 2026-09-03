from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.models import Gloss, SignClip

router = APIRouter(tags=["signs"])


def _serialise(clip: SignClip) -> dict:
    return {
        "id": clip.id, "gloss": clip.gloss.name, "english": clip.gloss.english,
        "take": clip.take, "isCanonical": clip.is_canonical,
        "durationMs": int(clip.duration * 1000), "frameCount": clip.frame_count,
        "fps": clip.fps, "byteSize": clip.byte_size, "rigDigest": clip.rig_digest,
        "url": f"/api/v1/clips/{clip.content_hash}.signclip",
        "landmarksUrl": f"/api/v1/clips/{clip.content_hash}.landmarks.json",
        "qc": clip.qc,
    }


@router.get("/signs")
def list_signs(
    q: str | None = None,
    canonical_only: bool = True,
    limit: int = Query(100, le=500),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    stmt = select(SignClip).join(Gloss)
    if canonical_only:
        stmt = stmt.where(SignClip.is_canonical.is_(True))
    if q:
        like = f"%{q.upper()}%"
        stmt = stmt.where(Gloss.name.like(like))
    total = len(session.scalars(stmt).all())
    rows = session.scalars(stmt.order_by(Gloss.name).limit(limit).offset(offset)).all()
    return {"total": total, "items": [_serialise(c) for c in rows]}


@router.post("/signs/{clip_id}/canonical")
def set_canonical(clip_id: int, session: Session = Depends(get_session)):
    clip = session.get(SignClip, clip_id)
    if clip is None:
        raise HTTPException(404, "no such clip")
    for sibling in clip.gloss.clips:
        sibling.is_canonical = sibling.id == clip.id
    session.commit()
    return _serialise(clip)


@router.get("/clips/{content_hash}.landmarks.json")
def get_landmarks(content_hash: str, session: Session = Depends(get_session)):
    """Landmark frames for the Signora Unity runtime (MediaPipe layout)."""
    clip = session.scalars(
        select(SignClip).where(SignClip.content_hash == content_hash)
    ).first()
    if clip is None:
        raise HTTPException(404, "no such clip")
    path = Path(clip.clip_path).parent / f"{content_hash}.landmarks.json"
    if not path.exists():
        raise HTTPException(404, "this clip has no landmark frames; re-ingest the capture")
    return FileResponse(
        path,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=31536000, immutable", "ETag": content_hash},
    )


@router.get("/clips/{content_hash}.signclip")
def get_clip(content_hash: str, session: Session = Depends(get_session)):
    clip = session.scalars(
        select(SignClip).where(SignClip.content_hash == content_hash)
    ).first()
    if clip is None or not Path(clip.clip_path).exists():
        raise HTTPException(404, "no such clip")
    # Content-addressed, so it can be cached indefinitely.
    return FileResponse(
        clip.clip_path,
        media_type="application/octet-stream",
        headers={"Cache-Control": "public, max-age=31536000, immutable", "ETag": content_hash},
    )
