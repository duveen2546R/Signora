from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, get_session
from app.models import IngestJob
from app.ingest.rokoko import RokokoFormatError, parse_csv, with_phase_bounds
from app.services.ingest_service import active_rig, create_job, run_ingest

router = APIRouter(prefix="/captures", tags=["captures"])


def _ingest_in_background(job_id: str) -> None:
    with SessionLocal() as session:
        run_ingest(session, job_id)


@router.post("", status_code=202)
async def upload_capture(
    file: UploadFile,
    background: BackgroundTasks,
    sign_start_seconds: float | None = Form(None),
    sign_end_seconds: float | None = Form(None),
    session: Session = Depends(get_session),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "expected a .csv export from Rokoko Studio")

    try:
        active_rig(session)
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc

    dest = settings.upload_dir / file.filename
    temporary = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.uploading")
    temporary.write_bytes(await file.read())
    try:
        parsed = parse_csv(temporary, name=dest.stem)
        if (
            sign_start_seconds is None
            and sign_end_seconds is None
            and not parsed.has_phase_bounds
        ):
            raise RokokoFormatError(
                "enter the Start→Sign and Sign→End timestamps before uploading"
            )
        with_phase_bounds(parsed, sign_start_seconds, sign_end_seconds)
    except RokokoFormatError as exc:
        temporary.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    temporary.replace(dest)

    job = create_job(session, dest, sign_start_seconds, sign_end_seconds)
    background.add_task(_ingest_in_background, job.id)
    return {"jobId": job.id, "status": job.status, "gloss": job.gloss_name}


@router.get("/{job_id}")
def capture_status(job_id: str, session: Session = Depends(get_session)):
    job = session.get(IngestJob, job_id)
    if job is None:
        raise HTTPException(404, "no such ingest job")
    return {
        "jobId": job.id, "status": job.status, "gloss": job.gloss_name,
        "clipId": job.clip_id, "error": job.error, "qc": job.qc,
        "createdAt": job.created_at, "finishedAt": job.finished_at,
    }
