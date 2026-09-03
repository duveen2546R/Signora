from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, get_session
from app.models import IngestJob
from app.services.ingest_service import active_rig, create_job, run_ingest

router = APIRouter(prefix="/captures", tags=["captures"])


def _ingest_in_background(job_id: str) -> None:
    with SessionLocal() as session:
        run_ingest(session, job_id)


@router.post("", status_code=202)
async def upload_capture(
    file: UploadFile,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "expected a .csv export from Rokoko Studio")

    try:
        active_rig(session)
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc

    dest = settings.upload_dir / file.filename
    dest.write_bytes(await file.read())

    job = create_job(session, dest)
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
