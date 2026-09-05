from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.models import Gloss, SignClip
from app.services.artifact_paths import clip_file, source_file
from app.services.compose_service import ComposeError, compose_clips, landmark_path
from app.services.phase_service import edit_phases
from app.services.source_motion import load_source_motion, raw_payload

router = APIRouter(tags=["signs"])


def _serialise(clip: SignClip) -> dict:
    return {
        "id": clip.id, "gloss": clip.gloss.name, "english": clip.gloss.english,
        "take": clip.take, "isCanonical": clip.is_canonical,
        "durationMs": int(clip.duration * 1000), "frameCount": clip.frame_count,
        "fps": clip.fps, "byteSize": clip.byte_size, "rigDigest": clip.rig_digest,
        "url": f"/api/v1/clips/{clip.content_hash}.signclip",
        "landmarksUrl": f"/api/v1/clips/{clip.content_hash}.landmarks.json",
        "qc": clip.qc, "contentHash": clip.content_hash,
        "rawUrl": f"/api/v1/signs/{clip.id}/raw",
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


class SequencePreview(BaseModel):
    clipIds: list[int] = Field(min_length=2, max_length=3)


@router.post("/signs/preview-sequence")
def preview_sequence(body: SequencePreview, session: Session = Depends(get_session)):
    """Explicit motion-review tool, never an ISL translation or linguistic approval."""
    clips = [session.get(SignClip, clip_id) for clip_id in body.clipIds]
    if any(clip is None for clip in clips):
        raise HTTPException(404, "one or more recordings no longer exist")
    try:
        composition, warnings = compose_clips([(clip.gloss.name, clip) for clip in clips])
        return {"purpose": "motion-review", "track": composition.to_payload(),
                "blendQuality": composition.blend_quality, "warnings": warnings, "error": None}
    except ComposeError as exc:
        return {"purpose": "motion-review", "track": None,
                "blendQuality": exc.blend_quality, "warnings": [], "error": str(exc)}


@router.get("/signs/{clip_id}/track")
def sign_track(clip_id: int, session: Session = Depends(get_session)):
    """One sign as a playable track: rest, transition in, the stroke, transition back to rest.

    The same composition a sentence uses, so previewing a sign shows what it will look like in one.
    """
    clip = session.get(SignClip, clip_id)
    if clip is None:
        raise HTTPException(404, "no such clip")
    try:
        composition, _warnings = compose_clips([(clip.gloss.name, clip)])
        return composition.to_payload()
    except ComposeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/signs/{clip_id}/raw")
def raw_capture(clip_id: int, session: Session = Depends(get_session)):
    clip = session.get(SignClip, clip_id)
    if clip is None:
        raise HTTPException(404, "no such clip")
    try:
        raw, source = load_source_motion(landmark_path(clip), str(source_file(clip.source_csv)), validate_stored_phases=False)
        return raw_payload(raw, source)
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


class PhaseUpdate(BaseModel):
    signStartSeconds: float = Field(allow_inf_nan=False)
    signEndSeconds: float = Field(allow_inf_nan=False)
    expectedContentHash: str | None = None


@router.patch("/signs/{clip_id}/phases")
def update_phases(clip_id: int, body: PhaseUpdate, session: Session = Depends(get_session)):
    clip = session.get(SignClip, clip_id)
    if clip is None:
        raise HTTPException(404, "no such clip")
    try:
        return _serialise(edit_phases(session, clip, body.signStartSeconds,
                                     body.signEndSeconds, body.expectedContentHash))
    except FileNotFoundError as exc:
        raise HTTPException(409, "Source motion is missing; re-ingest this capture.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/signs/{clip_id}/canonical")
def set_canonical(clip_id: int, session: Session = Depends(get_session)):
    clip = session.get(SignClip, clip_id)
    if clip is None:
        raise HTTPException(404, "no such clip")
    for sibling in clip.gloss.clips:
        sibling.is_canonical = sibling.id == clip.id
    session.commit()
    return _serialise(clip)


def _artifact_path(content_hash: str, session: Session) -> Path | None:
    clip = session.scalars(select(SignClip).where(SignClip.content_hash == content_hash)).first()
    if clip is not None:
        return clip_file(clip.clip_path)
    for row in session.scalars(select(SignClip)):
        for version in (row.qc or {}).get("phaseHistory", []):
            if version["contentHash"] == content_hash:
                return clip_file(version["clipPath"])
    return None


@router.get("/clips/{content_hash}.landmarks.json")
def get_landmarks(content_hash: str, session: Session = Depends(get_session)):
    """Landmark frames for the Signora Unity runtime (MediaPipe layout)."""
    artifact = _artifact_path(content_hash, session)
    if artifact is None:
        raise HTTPException(404, "no such clip")
    path = artifact.with_suffix(".landmarks.json")
    if not path.exists():
        raise HTTPException(404, "this clip has no landmark frames; re-ingest the capture")
    return FileResponse(
        path,
        media_type="application/json",
        headers={"Cache-Control": "public, max-age=31536000, immutable", "ETag": content_hash},
    )


@router.get("/clips/{content_hash}.signclip")
def get_clip(content_hash: str, session: Session = Depends(get_session)):
    path = _artifact_path(content_hash, session)
    if path is None or not path.exists():
        raise HTTPException(404, "no such clip")
    # Content-addressed, so it can be cached indefinitely.
    return FileResponse(
        path,
        media_type="application/octet-stream",
        headers={"Cache-Control": "public, max-age=31536000, immutable", "ETag": content_hash},
    )
