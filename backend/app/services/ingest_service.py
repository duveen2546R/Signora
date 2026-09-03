"""Turn an uploaded CSV into a stored, servable clip."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingest import clipfmt, rigprofile
from app.ingest.landmarks import to_landmarks
from app.ingest.pipeline import ingest_file
from app.ingest.rokoko import parse_csv
from app.models import Gloss, IngestJob, RigProfileRow, SignClip

_TAKE_SUFFIX = re.compile(r"[_-](\d{1,3})$")


def gloss_and_take_from_filename(stem: str) -> tuple[str, int]:
    """`hello_02.csv` -> ("HELLO", 2). Falls back to take 1 when no suffix is present."""
    take = 1
    m = _TAKE_SUFFIX.search(stem)
    if m:
        take = int(m.group(1))
        stem = stem[: m.start()]
    name = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").upper()
    return name or "UNNAMED", take


def active_rig(session: Session, digest: str | None = None) -> rigprofile.RigProfile:
    stmt = select(RigProfileRow)
    if digest:
        stmt = stmt.where(RigProfileRow.digest == digest)
    row = session.scalars(stmt.order_by(RigProfileRow.created_at.desc())).first()
    if row is None:
        raise LookupError(
            "no rig profile has been uploaded yet. Export one from Unity "
            "(SignSure > Export Rig Profile) and POST it to /api/v1/rigs."
        )
    return rigprofile.from_dict(row.payload, digest=row.digest)


def run_ingest(session: Session, job_id: str) -> None:
    job = session.get(IngestJob, job_id)
    if job is None:
        return
    try:
        rig = active_rig(session)
        clip, qc = ingest_file(job.source_csv, rig)
        blob = clipfmt.encode(clip)
        content_hash = hashlib.sha256(blob).hexdigest()[:32]

        path = settings.clip_dir / f"{content_hash}.signclip"
        path.write_bytes(blob)

        # Landmark frames for the Signora Unity runtime, which retargets in-engine from
        # MediaPipe-style points rather than consuming baked bone rotations.
        landmarks = to_landmarks(parse_csv(job.source_csv))
        (settings.clip_dir / f"{content_hash}.landmarks.json").write_text(
            json.dumps(landmarks.to_payload())
        )

        gloss_name, take = gloss_and_take_from_filename(Path(job.source_csv).stem)
        gloss = session.scalars(select(Gloss).where(Gloss.name == gloss_name)).first()
        if gloss is None:
            gloss = Gloss(name=gloss_name, english=gloss_name.replace("_", " ").lower())
            session.add(gloss)
            session.flush()

        existing = session.scalars(
            select(SignClip).where(SignClip.gloss_id == gloss.id, SignClip.take == take)
        ).first()
        if existing is not None:
            session.delete(existing)
            session.flush()

        row = SignClip(
            gloss_id=gloss.id, rig_digest=rig.digest, take=take,
            is_canonical=not any(c.is_canonical for c in gloss.clips),
            source_csv=job.source_csv, clip_path=str(path), content_hash=content_hash,
            fps=clip.fps, frame_count=clip.frame_count, duration=clip.duration,
            byte_size=len(blob), qc=qc.__dict__,
        )
        session.add(row)
        session.flush()

        job.clip_id = row.id
        job.qc = qc.__dict__
        job.status = "done"
    except Exception as exc:  # surfaced to the admin UI rather than swallowed
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        job.finished_at = dt.datetime.now(dt.UTC)
        session.commit()


def create_job(session: Session, csv_path: Path) -> IngestJob:
    gloss_name, _ = gloss_and_take_from_filename(csv_path.stem)
    job = IngestJob(id=str(uuid.uuid4()), gloss_name=gloss_name, source_csv=str(csv_path))
    session.add(job)
    session.commit()
    return job
