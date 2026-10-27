from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.db import get_session
from app.models import VideoPlan, VideoPlanUnit
from app.services.subtitle_service import MAX_SUBTITLE_BYTES, SubtitleError, build_translation_units, parse_subtitles
from app.services.video_plan_service import create_plan, prepare_plan, serialize_plan

router = APIRouter(tags=["video signing"])
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_video_id(value: str) -> str:
    candidate = value.strip()
    if _VIDEO_ID.fullmatch(candidate):
        return candidate
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host == "youtu.be":
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            candidate = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = parsed.path.strip("/").split("/")
            candidate = parts[1] if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"} else ""
    else:
        candidate = ""
    if not _VIDEO_ID.fullmatch(candidate):
        raise ValueError("Enter a valid YouTube video URL.")
    return candidate


def _get_plan(session: Session, plan_id: str) -> VideoPlan:
    plan = session.scalar(select(VideoPlan).options(selectinload(VideoPlan.units))
                          .where(VideoPlan.id == plan_id))
    if not plan:
        raise HTTPException(status_code=404, detail="Video signing plan not found.")
    return plan


@router.post("/video-plans", status_code=status.HTTP_202_ACCEPTED)
async def post_video_plan(
    background: BackgroundTasks,
    youtube_url: str = Form(..., min_length=1, max_length=500),
    subtitle: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    try:
        video_id = youtube_video_id(youtube_url)
        payload = await subtitle.read(MAX_SUBTITLE_BYTES + 1)
        cues = parse_subtitles(subtitle.filename or "subtitles.srt", payload)
        units = build_translation_units(cues)
    except (ValueError, SubtitleError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    plan, reused = create_plan(session, video_id, hashlib.sha256(payload).hexdigest(), units)
    if not reused:
        background.add_task(prepare_plan, plan.id)
    value = serialize_plan(plan, session)
    value["reused"] = reused
    return value


@router.get("/video-plans/{plan_id}")
def get_video_plan(plan_id: str, session: Session = Depends(get_session)):
    return serialize_plan(_get_plan(session, plan_id), session)


@router.get("/video-plans/{plan_id}/units/{unit_id}/motion")
def get_video_unit_motion(plan_id: str, unit_id: int, session: Session = Depends(get_session)):
    plan = _get_plan(session, plan_id)
    serialized = serialize_plan(plan, session)
    if serialized["stale"]:
        raise HTTPException(status_code=409, detail="This plan is stale; prepare it again.")
    unit = session.scalar(select(VideoPlanUnit).where(
        VideoPlanUnit.id == unit_id, VideoPlanUnit.plan_id == plan_id
    ))
    if not unit or not unit.motion_path:
        raise HTTPException(status_code=404, detail="This unit has no playable motion.")
    path = Path(unit.motion_path).resolve()
    root = settings.video_plan_dir.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=410, detail="The prepared motion is no longer available.")
    return Response(
        content=path.read_bytes(), media_type="application/json",
        headers={"Content-Encoding": "gzip", "Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.delete("/video-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video_plan(plan_id: str, session: Session = Depends(get_session)):
    plan = _get_plan(session, plan_id)
    session.delete(plan)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
