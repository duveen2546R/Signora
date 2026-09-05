"""Turn an uploaded CSV into a stored, servable clip."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
import hashlib
import json
import re
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.ingest import clipfmt, rigprofile
from app.ingest.compose import prepare
from app.ingest.landmarks import LandmarkSkeleton, to_landmarks
from app.ingest.segment import find_phases, usable_range
from app.ingest.pipeline import ingest_take
from app.ingest.rokoko import parse_csv, with_phase_bounds
from app.models import Gloss, IngestJob, RigProfileRow, SignClip

_TAKE_SUFFIX = re.compile(r"[_-](\d{1,3})$")


def content_hash_for(blob: bytes, phases: dict, raw_payload: dict | None = None) -> str:
    """Content identity includes semantic phase edits as well as the motion bytes."""
    phase_identity = json.dumps(phases, sort_keys=True, separators=(",", ":")).encode()
    motion_identity = json.dumps(raw_payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob + b"\0source-clock-v2\0" + phase_identity + b"\0" + motion_identity).hexdigest()[:32]


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
        parsed = parse_csv(job.source_csv)
        phase_input = (job.qc or {}).get("phaseInput", {})
        parsed = with_phase_bounds(
            parsed,
            phase_input.get("signStartSeconds"),
            phase_input.get("signEndSeconds"),
        )
        clip, qc = ingest_take(parsed, rig)
        blob = clipfmt.encode(clip)

        # Landmark frames for the Signora Unity runtime, which retargets in-engine from
        # MediaPipe-style points rather than consuming baked bone rotations.
        landmarks = to_landmarks(parsed)

        # Record where the sign itself starts and ends. Sentences play only the stroke, so a bad
        # detection here silently truncates a word - it belongs in the QC panel, not a log line.
        skeleton = LandmarkSkeleton.from_takes(landmarks)
        # Corrupt frames are dropped inside prepare(), so count them on the raw take - by the time
        # the stroke is found there is nothing left to report.
        head, tail, _interior = usable_range(landmarks)
        corrupt = head + (landmarks.frame_count - tail)
        prepared = prepare(landmarks, skeleton)
        phases = find_phases(prepared)

        # Persist detected bounds too, so reloading this content-addressed landmark asset reproduces
        # the reviewed composition exactly. Prepared timestamps are relative to the usable slice;
        # translate them back to the original take before storing them.
        if not landmarks.has_phase_bounds:
            offset = float(landmarks.times[head])
            landmarks = replace(
                landmarks,
                sign_start_s=offset + phases.stroke_start / prepared.fps,
                sign_end_s=offset + phases.stroke_end / prepared.fps,
                phase_source="detected",
                phase_reviewed=False,
            )

        phase_qc = phases.as_dict()
        phase_qc.update({
            "signStartSeconds": round(float(landmarks.sign_start_s), 4),
            "signEndSeconds": round(float(landmarks.sign_end_s), 4),
            "source": landmarks.phase_source or phases.source,
            "reviewed": landmarks.phase_reviewed,
        })
        qc.phases = phase_qc
        qc.stroke = {
            "start": phases.stroke_start,
            "end": phases.stroke_end,
            "durationSeconds": round(
                (phases.stroke_end - phases.stroke_start) / prepared.fps, 3
            ),
            "usedFallback": bool(phases.reason),
            "droppedCorruptFrames": corrupt,
            "reason": phases.reason,
        }
        if not landmarks.phase_reviewed:
            qc.warnings.append(
                "phase boundaries were detected automatically and need review; "
                "enter sign-start and sign-end timestamps when uploading this capture"
            )
        if corrupt:
            qc.warnings.append(
                f"dropped {corrupt} corrupt frame(s) where the whole skeleton jumped; "
                "the recording is truncated at that end"
            )

        raw_payload = landmarks.to_payload()
        content_hash = content_hash_for(blob, phase_qc, raw_payload)
        path = settings.clip_dir / f"{content_hash}.signclip"
        path.write_bytes(blob)
        (settings.clip_dir / f"{content_hash}.landmarks.json").write_text(
            json.dumps(raw_payload)
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
        was_canonical = existing.is_canonical if existing is not None else False
        if existing is not None:
            session.delete(existing)
            session.flush()

        row = SignClip(
            gloss_id=gloss.id, rig_digest=rig.digest, take=take,
            is_canonical=was_canonical or not any(
                c.is_canonical and c is not existing for c in gloss.clips
            ),
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


def create_job(
    session: Session,
    csv_path: Path,
    sign_start_s: float | None = None,
    sign_end_s: float | None = None,
) -> IngestJob:
    gloss_name, _ = gloss_and_take_from_filename(csv_path.stem)
    phase_input = {}
    if sign_start_s is not None or sign_end_s is not None:
        phase_input = {
            "signStartSeconds": sign_start_s,
            "signEndSeconds": sign_end_s,
        }
    job = IngestJob(
        id=str(uuid.uuid4()), gloss_name=gloss_name, source_csv=str(csv_path),
        qc={"phaseInput": phase_input} if phase_input else {},
    )
    session.add(job)
    session.commit()
    return job
