from __future__ import annotations

import uuid
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.db import SessionLocal, get_session
from app.models import IngestJob
from app.services.source_motion import raw_payload
from app.ingest.fbx import FbxFormatError, parse_fbx
from app.ingest.rokoko import RokokoFormatError, with_phase_bounds
from app.services.ingest_service import create_job, run_ingest

router = APIRouter(prefix="/captures", tags=["captures"])
MAX_CAPTURE_BYTES = 100 * 1024 * 1024


def _filename(file: UploadFile) -> str:
    name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name.lower().endswith(".fbx") or not name[:-4].strip() or "\x00" in name:
        raise HTTPException(400, "expected a combined .fbx export from Rokoko Studio")
    return name


async def _save_upload(file: UploadFile, destination: Path) -> None:
    size = 0
    with destination.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_CAPTURE_BYTES:
                raise HTTPException(413, "FBX capture exceeds the 100 MB upload limit")
            output.write(chunk)
    if not size:
        raise HTTPException(400, "the FBX file is empty")


def _validate_capture(path: Path, name: str, start: float | None, end: float | None):
    parsed = parse_fbx(path, name=name)
    if start is None and end is None and not parsed.has_phase_bounds:
        raise RokokoFormatError("enter the Start→Sign and Sign→End timestamps before uploading")
    return with_phase_bounds(parsed, start, end, snap=True, override_csv_phase=True)


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
    filename = _filename(file)

    source_dir = settings.upload_dir / uuid.uuid4().hex
    source_dir.mkdir(parents=True, exist_ok=True)
    dest = source_dir / filename
    temporary = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.uploading")
    accepted = False
    try:
        await _save_upload(file, temporary)
        await run_in_threadpool(
            _validate_capture, temporary, dest.stem, sign_start_seconds, sign_end_seconds,
        )
        accepted = True
    except (ValueError, IndexError, RokokoFormatError, FbxFormatError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        await file.close()
        if not accepted:
            temporary.unlink(missing_ok=True)
            source_dir.rmdir()
    temporary.replace(dest)

    job = create_job(session, dest, sign_start_seconds, sign_end_seconds)
    background.add_task(_ingest_in_background, job.id)
    return {"jobId": job.id, "status": job.status, "gloss": job.gloss_name}


@router.post("/preview")
async def preview_capture(file: UploadFile):
    """Inspect synchronized body, hand, and face motion without creating a capture."""
    filename = _filename(file)
    try:
        with tempfile.NamedTemporaryFile(suffix=".fbx") as temporary:
            await _save_upload(file, Path(temporary.name))
            raw = await run_in_threadpool(parse_fbx, temporary.name, name=Path(filename).stem)
        return raw_payload(raw, raw)
    except (ValueError, IndexError, FbxFormatError) as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        await file.close()


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
