"""Import the playlist vocabulary (Videos 2, 3, 6, 7) and the A-Z alphabet from trainer/.

Source of truth is docs/playlist-import-manifest.json. For each entry with a source:

- `selectedSource` set: that file is imported.
- `choose-canonical-take`: one take is chosen deterministically (`select_source`) - the
  non-numbered filename when there is one, otherwise the first candidate in sorted order. This is a
  mechanical choice, not a quality judgement; a reviewer can promote another take later through
  `POST /signs/{id}/canonical`.

All 26 alphabet letters are also ensured, so the caption fallback can fingerspell complete words.

Ingestion follows `prepare_demo_library.py`: the source is copied (never moved) into a fresh upload
folder under a clean import name and ingested with the Capture service functions (`create_job` +
`run_ingest`). No Start/Sign/End timestamps are supplied, so every new clip stays
`phase_reviewed=False` and video plans refuse it until a person reviews its boundaries.

A gloss that already has a recording is never re-imported, so reviewed library takes are not
replaced by an unreviewed one. trainer/ is only ever read from.

Usage: from backend/, `python tools/import_playlist_vocabulary.py [--write-patterns] [--dry-run]`
  --write-patterns  add candidate word->gloss patterns for imported non-letter glosses to
                    app/services/isl_patterns.json and bump the registry version.
  --dry-run         print the selection plan without ingesting anything.
"""

from __future__ import annotations

import json
import re
import shutil
import string
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings

REPO_ROOT = settings.repo_root
TRAINER_DIR = REPO_ROOT / "trainer"
MANIFEST_PATH = REPO_ROOT / "docs" / "playlist-import-manifest.json"
REPORT_PATH = REPO_ROOT / "docs" / "playlist-import-report.json"
REGISTRY_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "isl_patterns.json"
VIDEOS = (2, 3, 6, 7)

# "Teacher_1_mixamo.fbx" (take suffix) and "Chair_mixamo (1).fbx" (copy suffix) are numbered.
_NUMBERED = re.compile(r"_\d+_mixamo|\(\d+\)")


def is_numbered(filename: str) -> bool:
    return bool(_NUMBERED.search(filename))


def select_source(entry: dict) -> str | None:
    """The one trainer/ file to import for a manifest entry, or None when it has no source."""
    if entry.get("selectedSource"):
        return entry["selectedSource"]
    candidates = sorted(entry.get("sourceCandidates") or [])
    if entry.get("status") != "choose-canonical-take" or not candidates:
        return None
    plain = [name for name in candidates if not is_numbered(name)]
    return (plain or candidates)[0]


def letter_candidates(letter: str, filenames: list[str]) -> list[str]:
    """trainer/ files that record the single letter `letter`, e.g. `E_2_mixamo.fbx`, `e_mixamo.fbx`."""
    pattern = re.compile(rf"{letter}(_\d+)?_mixamo( \(\d+\))?\.fbx", re.IGNORECASE)
    return sorted(name for name in filenames if pattern.fullmatch(name))


def import_name(gloss: str) -> str:
    """Clean upload name that `gloss_and_take_from_filename` maps back to (gloss, take 1)."""
    return f"{gloss.lower()}_01.fbx"


def build_plan(manifest: dict, trainer_files: list[str]) -> list[dict]:
    """One row per gloss to ensure: manifest words first, then any alphabet letter not yet covered."""
    rows: dict[str, dict] = {}
    for entry in manifest["entries"]:
        if entry["video"] not in VIDEOS:
            continue
        source = select_source(entry)
        gloss = entry["proposedGloss"]
        row = rows.setdefault(gloss, {
            "gloss": gloss, "captionWords": [], "videos": [], "source": source,
            "candidates": sorted(entry.get("sourceCandidates") or []),
            "selection": entry["status"],
        })
        word = entry["captionWord"].replace("’", "'")
        if word not in row["captionWords"]:
            row["captionWords"].append(word)
        if entry["video"] not in row["videos"]:
            row["videos"].append(entry["video"])
        if row["source"] is None and source is not None:
            row.update(source=source, candidates=sorted(entry["sourceCandidates"]),
                       selection=entry["status"])
    for letter in string.ascii_uppercase:
        candidates = letter_candidates(letter, trainer_files)
        row = rows.get(letter)
        if row is not None and row["source"] is not None:
            continue
        entry = {"status": "choose-canonical-take", "sourceCandidates": candidates}
        if len(candidates) == 1:
            entry = {"selectedSource": candidates[0]}
        rows[letter] = {
            "gloss": letter, "captionWords": row["captionWords"] if row else [],
            "videos": row["videos"] if row else [], "source": select_source(entry),
            "candidates": candidates, "selection": "alphabet-fallback",
        }
    return list(rows.values())


def _import_one(session, row: dict) -> dict:
    from app.ingest.fbx import FbxFormatError, parse_fbx
    from app.models import Gloss, SignClip
    from app.services.ingest_service import create_job, run_ingest
    from sqlalchemy import select

    record = {**row, "outcome": None, "clipId": None, "contentHash": None,
              "phaseReviewed": False, "error": None}
    if row["source"] is None:
        record["outcome"] = "missing-source"
        return record
    existing = session.scalars(select(Gloss).where(Gloss.name == row["gloss"])).first()
    if existing is not None and existing.clips:
        canonical = next((c for c in existing.clips if c.is_canonical), existing.clips[0])
        record.update(outcome="already-in-library", clipId=canonical.id,
                      contentHash=canonical.content_hash,
                      phaseReviewed=bool((canonical.qc or {}).get("phases", {}).get("reviewed")))
        return record
    source_path = TRAINER_DIR / row["source"]
    if not source_path.is_file():
        record.update(outcome="failed", error=f"source file not found in trainer/: {row['source']}")
        return record

    upload_dir = settings.upload_dir / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / import_name(row["gloss"])
    shutil.copyfile(source_path, dest)
    try:
        parse_fbx(dest, name=dest.stem)
    except FbxFormatError as exc:
        record.update(outcome="failed", error=f"FBX validation failed: {exc}")
        return record

    # No timestamps: run_ingest records detected, unreviewed boundaries (see module docstring).
    job = create_job(session, dest, sign_start_s=None, sign_end_s=None)
    run_ingest(session, job.id)
    session.refresh(job)
    if job.status != "done" or job.clip_id is None:
        record.update(outcome="failed", error=job.error or f"ingest status {job.status}")
        return record
    clip = session.get(SignClip, job.clip_id)
    if clip.gloss.name != row["gloss"]:
        record.update(outcome="failed",
                      error=f"import name produced gloss {clip.gloss.name!r}, expected {row['gloss']!r}")
        return record
    record.update(outcome="imported", clipId=clip.id, contentHash=clip.content_hash,
                  phaseReviewed=bool((clip.qc or {}).get("phases", {}).get("reviewed")))
    return record


def candidate_patterns(records: list[dict], registry: dict) -> list[dict]:
    """Single-word candidate patterns for imported word glosses the registry does not cover yet.

    Letters are skipped on purpose: a one-letter recording is a fingerspelling unit, and mapping the
    word "I" or "a" to it would sign the pronoun or the article as a letter.
    """
    covered = {p["glosses"][0] for p in registry["patterns"] if len(p["glosses"]) == 1}
    ids = {p["id"] for p in registry["patterns"]}
    patterns = []
    for record in records:
        gloss = record["gloss"]
        if record["clipId"] is None or len(gloss) == 1 or gloss in covered:
            continue
        pattern_id = gloss.lower()
        if pattern_id in ids:
            continue
        forms = [word.lower() for word in record["captionWords"]]
        patterns.append({"id": pattern_id, "forms": forms, "glosses": [gloss],
                         "reviewStatus": "candidate"})
        ids.add(pattern_id)
    return patterns


def write_patterns(patterns: list[dict]) -> None:
    """Append in the registry's compact style so existing entries keep their formatting."""
    if not patterns:
        return
    text = REGISTRY_PATH.read_text()
    version = json.loads(text)["version"]
    body = ",\n".join(
        "    {\n"
        f'      "id": {json.dumps(p["id"])},\n'
        f'      "forms": {json.dumps(p["forms"], ensure_ascii=False)},\n'
        f'      "glosses": {json.dumps(p["glosses"])},\n'
        f'      "reviewStatus": "candidate"\n'
        "    }"
        for p in patterns
    )
    head, tail = text.rstrip().rsplit("]", 1)
    text = head.rstrip() + ",\n" + body + "\n  ]" + tail + "\n"
    text = text.replace(f'"version": {version},', f'"version": {version + 1},', 1)
    REGISTRY_PATH.write_text(text)


def main(argv: list[str]) -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    trainer_files = sorted(path.name for path in TRAINER_DIR.iterdir() if path.is_file())
    plan = build_plan(manifest, trainer_files)
    if "--dry-run" in argv:
        print(json.dumps(plan, indent=2, ensure_ascii=False))
        return 0

    from app.core.db import SessionLocal, init_db

    init_db()
    records = []
    with SessionLocal() as session:
        for row in plan:
            record = _import_one(session, row)
            print(f"{record['gloss']:<14} {record['outcome']:<20} {record['source'] or ''}"
                  f"{'  ' + record['error'] if record['error'] else ''}", file=sys.stderr)
            records.append(record)
    REPORT_PATH.write_text(json.dumps({
        "generatedBy": "backend/tools/import_playlist_vocabulary.py",
        "note": "Phase boundaries were detected automatically and are NOT human-reviewed; "
                "video plans refuse these clips until each is reviewed in Capture -> Edit timestamps. "
                "Duplicate takes were chosen mechanically, not by quality or meaning.",
        "records": records,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if "--write-patterns" in argv:
        patterns = candidate_patterns(records, json.loads(REGISTRY_PATH.read_text()))
        write_patterns(patterns)
        print(f"added {len(patterns)} candidate pattern(s) to {REGISTRY_PATH.name}", file=sys.stderr)
    counts: dict[str, int] = {}
    for record in records:
        counts[record["outcome"]] = counts.get(record["outcome"], 0) + 1
    print(json.dumps(counts), file=sys.stderr)
    return 1 if counts.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
