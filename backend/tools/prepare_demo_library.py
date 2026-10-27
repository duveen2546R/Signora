"""Import the YouTube Chrome-extension demo library from trainer/ FBX sources.

Copies each required trainer/ FBX into a fresh upload folder under a clean import name, then
ingests it through the same service functions the Capture API uses (`create_job` + `run_ingest`).

Deliberately does not supply sign-start/sign-end timestamps: those values would be synthetic (not
authored by a human reviewer), and `app.ingest.rokoko.with_phase_bounds` marks any supplied
timestamp as human-reviewed (`phase_source="authored-ui"`, `phase_reviewed=True`) with no way to
distinguish "a person typed this" from "a script typed this". Leaving timestamps unset keeps every
imported clip honestly marked `phase_reviewed=False` and lets `run_ingest` record its own detected
stroke boundaries for later human review instead.

trainer/ is only ever read from; nothing there is renamed, moved, or deleted.

Usage: from backend/, `python tools/prepare_demo_library.py`
"""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.db import SessionLocal, init_db
from app.ingest.fbx import FbxFormatError, parse_fbx
from app.models import Gloss, SignClip
from app.services.ingest_service import create_job, run_ingest

REPO_ROOT = settings.repo_root
TRAINER_DIR = REPO_ROOT / "trainer"

# Reproducible source -> clean import name -> gloss mapping. One take (take 1) per gloss.
# (source filename in trainer/, clean import filename, expected gloss)
SOURCE_MAP: list[tuple[str, str, str]] = [
    ("Hello_mixamo.fbx", "hello_01.fbx", "HELLO"),
    ("Good_Morning_New_mixamo.fbx", "good_morning_01.fbx", "GOOD_MORNING"),
    ("Namaste_2_mixamo.fbx", "namaste_01.fbx", "NAMASTE"),
    ("ThankYou_4_mixamo.fbx", "thankyou_01.fbx", "THANKYOU"),
    ("Father_mixamo.fbx", "father_01.fbx", "FATHER"),
    ("Able_mixamo.fbx", "able_01.fbx", "ABLE"),
    ("Action_mixamo.fbx", "action_01.fbx", "ACTION"),
    ("Add_2_mixamo.fbx", "add_01.fbx", "ADD"),
    ("Addition_New__mixamo.fbx", "addition_01.fbx", "ADDITION"),
    ("Adjective_2_mixamo.fbx", "adjective_01.fbx", "ADJECTIVE"),
    ("Advise_mixamo.fbx", "advise_01.fbx", "ADVISE"),
    ("After_mixamo.fbx", "after_01.fbx", "AFTER"),
    ("Again_mixamo.fbx", "again_01.fbx", "AGAIN"),
    ("Age_mixamo.fbx", "age_01.fbx", "AGE"),
    ("Agree_mixamo.fbx", "agree_01.fbx", "AGREE"),
    ("All_mixamo.fbx", "all_01.fbx", "ALL"),
    ("Always_mixamo.fbx", "always_01.fbx", "ALWAYS"),
    ("Answer_mixamo.fbx", "answer_01.fbx", "ANSWER"),
    ("App_mixamo.fbx", "app_01.fbx", "APP"),
    ("Apply_mixamo.fbx", "apply_01.fbx", "APPLY"),
    ("Appointment_mixamo.fbx", "appointment_01.fbx", "APPOINTMENT"),
    ("Assume_mixamo.fbx", "assume_01.fbx", "ASSUME"),
    ("Away_mixamo.fbx", "away_01.fbx", "AWAY"),
    ("B_mixamo.fbx", "b_01.fbx", "B"),
    ("E_2_mixamo.fbx", "e_01.fbx", "E"),
    ("N_mixamo.fbx", "n_01.fbx", "N"),
    ("D_mixamo.fbx", "d_01.fbx", "D"),
]


def _import_one(session, source_name: str, import_name: str, expected_gloss: str) -> dict:
    record: dict = {
        "sourceFile": source_name,
        "importFile": import_name,
        "expectedGloss": expected_gloss,
        "rawSourceExists": False,
        "validated": False,
        "jobStatus": None,
        "clipId": None,
        "contentHash": None,
        "durationSeconds": None,
        "frameCount": None,
        "fps": None,
        "phase": None,
        "qcWarnings": [],
        "isCanonical": None,
        "error": None,
    }
    source_path = TRAINER_DIR / source_name
    if not source_path.exists():
        record["error"] = f"source file not found in trainer/: {source_name}"
        return record
    record["rawSourceExists"] = True

    # Copy (never move) the original into an isolated upload folder, same layout the Capture API
    # uses, under the clean import name.
    upload_dir = settings.upload_dir / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / import_name
    shutil.copyfile(source_path, dest)

    try:
        parse_fbx(dest, name=dest.stem)
        record["validated"] = True
    except FbxFormatError as exc:
        record["error"] = f"FBX validation failed: {exc}"
        return record

    # No sign_start_seconds/sign_end_seconds: see module docstring. run_ingest records its own
    # detected (unreviewed) phase boundaries.
    job = create_job(session, dest, sign_start_s=None, sign_end_s=None)
    run_ingest(session, job.id)
    session.refresh(job)
    record["jobStatus"] = job.status
    record["error"] = job.error or None

    if job.status != "done" or job.clip_id is None:
        return record

    clip = session.get(SignClip, job.clip_id)
    gloss = session.get(Gloss, clip.gloss_id)
    if gloss.name != expected_gloss:
        record["error"] = (
            f"filename->gloss mapping produced {gloss.name!r}, expected {expected_gloss!r}"
        )
        return record

    phases = (clip.qc or {}).get("phases", {})
    record.update({
        "clipId": clip.id,
        "contentHash": clip.content_hash,
        "durationSeconds": round(clip.duration, 3),
        "frameCount": clip.frame_count,
        "fps": clip.fps,
        "phase": {
            "source": phases.get("source"),
            "reviewed": phases.get("reviewed", False),
            "signStartSeconds": phases.get("signStartSeconds"),
            "signEndSeconds": phases.get("signEndSeconds"),
        },
        "qcWarnings": (clip.qc or {}).get("warnings", []),
        "isCanonical": clip.is_canonical,
    })
    return record


def main() -> list[dict]:
    init_db()
    results: list[dict] = []
    with SessionLocal() as session:
        for source_name, import_name, gloss in SOURCE_MAP:
            results.append(_import_one(session, source_name, import_name, gloss))
    return results


if __name__ == "__main__":
    out = main()
    print(json.dumps(out, indent=2))
    ok = sum(1 for r in out if r["clipId"] is not None)
    print(f"\n{ok}/{len(out)} glosses imported successfully", file=sys.stderr)
