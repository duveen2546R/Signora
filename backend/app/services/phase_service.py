"""Edit semantic boundaries without changing source motion or overwriting published assets."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, UTC
import json
from pathlib import Path
import uuid

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.ingest.compose import prepare
from app.ingest.landmarks import LandmarkSkeleton
from app.ingest.rokoko import with_phase_bounds
from app.ingest.segment import find_phases
from app.models import SignClip
from app.services.artifact_paths import clip_file, source_file
from app.services.compose_service import landmark_path
from app.services.ingest_service import content_hash_for
from app.services.source_motion import load_source_motion


def publish(path: Path, data: bytes) -> None:
    """Only publish complete immutable files; an existing identity must have identical bytes."""
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Artifact identity conflict; original file was preserved.")
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def edit_phases(session: Session, clip: SignClip, start: float, end: float,
                expected_hash: str | None = None) -> SignClip:
    old_hash = clip.content_hash
    if expected_hash is not None and expected_hash != old_hash:
        raise ValueError("This capture changed. Reopen the editor before saving.")
    payload = json.loads(landmark_path(clip).read_text())
    raw, source = load_source_motion(landmark_path(clip), str(source_file(clip.source_csv)), validate_stored_phases=False)
    # An edit made in the studio is a deliberate re-authoring: snap it onto a captured row
    # and let it supersede the CSV Phase column, which is a default rather than a contract.
    checked = with_phase_bounds(source, start, end, snap=True, override_csv_phase=True)
    start, end = checked.sign_start_s, checked.sign_end_s
    revised = replace(raw, sign_start_s=start, sign_end_s=end,
                      phase_source="authored-ui", phase_reviewed=True)
    prepared = prepare(revised, LandmarkSkeleton.from_takes(revised))
    phases = find_phases(prepared).as_dict()
    phases.update(signStartSeconds=start, signEndSeconds=end, source="authored-ui", reviewed=True)
    clip_artifact = clip_file(clip.clip_path)
    blob = clip_artifact.read_bytes()
    # Preserve every raw coordinate and the original CSV; only annotation fields change.
    payload.update(timestampsSeconds=source.times.tolist(), durationSeconds=raw.duration,
                   signStartSeconds=start, signEndSeconds=end,
                   phaseSource="authored-ui", phaseReviewed=True)
    new_hash = content_hash_for(blob, phases, payload)
    if new_hash == old_hash:
        return clip
    destination = clip_artifact.parent / f"{new_hash}.signclip"
    publish(destination, blob)
    publish(destination.with_suffix(".landmarks.json"), json.dumps(payload).encode())
    qc = dict(clip.qc or {})
    history = list(qc.get("phaseHistory", []))
    history.append({"contentHash": old_hash, "clipPath": clip.clip_path,
                    "phases": qc.get("phases"), "replacedAt": datetime.now(UTC).isoformat()})
    qc.update(phases=phases, phaseHistory=history)
    qc["stroke"] = {**qc.get("stroke", {}),
                    "start": phases["sign"]["start"], "end": phases["sign"]["end"],
                    "durationSeconds": phases["sign"]["durationSeconds"],
                    "usedFallback": False, "reason": ""}
    # Timestamp authorship never confers linguistic approval.
    qc["linguisticReview"] = {"status": "pending", "reason": "Phase boundaries changed."}
    statement = update(SignClip).where(SignClip.id == clip.id, SignClip.content_hash == old_hash).values(
        content_hash=new_hash, clip_path=str(destination), qc=qc,
    ).execution_options(synchronize_session=False)
    if session.execute(statement).rowcount != 1:
        session.rollback()
        raise ValueError("This capture changed. Reopen the editor before saving.")
    session.commit()
    session.refresh(clip)
    return clip
