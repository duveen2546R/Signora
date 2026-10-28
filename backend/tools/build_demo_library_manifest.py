"""Generate the tracked demo-library manifest (docs/demo-library/) from the current database.

Re-derives readiness per asset rather than trusting prepare_demo_library.py's run-time log, so the
manifest always reflects the database's actual current state. Read-only except for writing the two
output files under docs/demo-library/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.main import app
from app.models import Gloss, SignClip
from app.services.compose_service import PLAYABLE_STATUSES, ComposeError, compose_playable
from app.services.translate_service import load_registry
from tools.prepare_demo_library import SOURCE_MAP

OUT_DIR = settings.repo_root / "docs" / "demo-library"
client = TestClient(app)

ALPHABET_GLOSSES = {"B", "E", "N", "D"}


def direct_playback(clip_id: int) -> tuple[bool, str, str | None]:
    """(plays, detail, blend status) for GET /signs/{id}/track - the real direct-playback path."""
    resp = client.get(f"/api/v1/signs/{clip_id}/track")
    if resp.status_code != 200:
        return False, f"HTTP {resp.status_code}: {resp.text[:160]}", None
    payload = resp.json()
    if not payload.get("frameCount"):
        return False, "empty track", None
    return True, "", payload.get("blendQuality", {}).get("status")


def main() -> None:
    registry = load_registry()
    pattern_forms = {
        form: pattern.glosses[0]
        for pattern in registry.patterns
        if len(pattern.glosses) == 1 and not pattern.fingerspellSlots
        for form in pattern.forms
    }

    rows = []
    with SessionLocal() as session:
        for source_name, import_name, gloss_name in SOURCE_MAP:
            gloss = session.scalar(select(Gloss).where(Gloss.name == gloss_name))
            row = {
                "sourceFile": source_name,
                "importFile": import_name,
                "gloss": gloss_name,
                "rawSourceExists": (settings.repo_root / "trainer" / source_name).exists(),
                "imported": False,
                "clipId": None,
                "contentHash": None,
                "durationSeconds": None,
                "jobStatus": None,
                "phaseSource": None,
                "phaseReviewed": False,
                "proposedSignStartSeconds": None,
                "proposedSignEndSeconds": None,
                "qcWarnings": [],
                "isCanonical": None,
                "directPlaybackReady": False,
                "directPlaybackDetail": "",
                "blendStatus": None,
                "subtitleAliasForm": next(
                    (form for form, g in pattern_forms.items() if g == gloss_name), None,
                ),
                "videoPlanReady": False,
                "state": "failed-or-missing",
            }
            if gloss is None:
                rows.append(row)
                continue
            clip = session.scalar(
                select(SignClip).where(SignClip.gloss_id == gloss.id, SignClip.take == 1)
            )
            if clip is None:
                rows.append(row)
                continue

            row["imported"] = True
            row["clipId"] = clip.id
            row["contentHash"] = clip.content_hash
            row["durationSeconds"] = round(clip.duration, 3)
            row["jobStatus"] = "done"
            row["isCanonical"] = clip.is_canonical
            phases = (clip.qc or {}).get("phases", {})
            row["phaseSource"] = phases.get("source")
            row["phaseReviewed"] = bool(phases.get("reviewed", False))
            row["proposedSignStartSeconds"] = phases.get("signStartSeconds")
            row["proposedSignEndSeconds"] = phases.get("signEndSeconds")
            row["qcWarnings"] = (clip.qc or {}).get("warnings", [])

            ok, detail, status = direct_playback(clip.id)
            row["directPlaybackReady"] = ok
            row["directPlaybackDetail"] = detail
            row["blendStatus"] = status

            # Exactly what video_plan_service.prepare_plan enforces: reviewed phases, then the
            # shared compose_playable policy, then a playable status.
            try:
                if not row["phaseReviewed"]:
                    raise ComposeError("needs reviewed phase timestamps")
                composition, _warnings = compose_playable([(gloss_name, clip)])
                row["videoPlanReady"] = composition.blend_quality.get("status") in PLAYABLE_STATUSES
            except ComposeError:
                row["videoPlanReady"] = False

            if not row["isCanonical"]:
                row["state"] = "imported-not-canonical"
            elif row["videoPlanReady"]:
                row["state"] = "subtitle-video-plan-ready"
            elif not row["phaseReviewed"]:
                row["state"] = "awaiting-phase-review"
            else:
                row["state"] = "failed-or-missing"
            rows.append(row)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps({
        "generatedBy": "backend/tools/build_demo_library_manifest.py",
        "patternRegistryVersion": registry.version,
        "assets": rows,
    }, indent=2), encoding="utf-8")

    _write_readme(rows, registry.version)
    print(f"wrote {manifest_path}")
    print(f"wrote {OUT_DIR / 'README.md'}")


def _write_readme(rows: list[dict], registry_version: int) -> None:
    lines = []
    lines.append("# SignSure demo library — readiness manifest")
    lines.append("")
    lines.append(
        "Generated by `backend/tools/build_demo_library_manifest.py` from the live database. "
        "Do not hand-edit this file; re-run the generator instead."
    )
    lines.append("")
    lines.append(
        "Source captures live in `trainer/` and are never modified, renamed, or deleted by this "
        "pipeline. Each asset below was copied into an isolated upload folder under a clean import "
        "name and ingested through the normal Capture service functions "
        "(`create_job` + `run_ingest`), the same functions the `/api/v1/captures` endpoint uses."
    )
    lines.append("")
    lines.append(
        "Captures were imported without timestamps, so nothing was falsely marked as reviewed; the "
        "Start → Sign → End boundaries below were then saved by a person through **Capture → Edit "
        "timestamps** (`phase_source=\"authored-ui\"`)."
    )
    lines.append("")
    direct_ready = sum(r["directPlaybackReady"] for r in rows)
    plan_ready = sum(r["videoPlanReady"] for r in rows)
    reviewed_count = sum(r["phaseReviewed"] for r in rows)
    settled = [r["gloss"] for r in rows if r["blendStatus"] == "reviewed-direct"]
    lines.append(
        f"**Summary: {sum(r['imported'] for r in rows)}/{len(rows)} imported, "
        f"{reviewed_count}/{len(rows)} human-reviewed, {direct_ready}/{len(rows)} play directly, "
        f"{plan_ready}/{len(rows)} subtitle/video-plan ready.** "
        f"{len(settled)} play through a labelled settle"
        + (f" (`{', '.join(settled)}`)" if settled else "") + "; the rest are fully direct."
    )
    lines.append("")
    lines.append("## How a recording plays")
    lines.append("")
    lines.append(
        "- **`direct`** — every join to and from rest passed the full transition-quality gate."
    )
    lines.append(
        "- **`reviewed-direct`** — the reviewed take was captured slightly short (it starts while "
        "the hands are already moving, or stops before they are back at rest), so no direct bridge "
        "to the neutral pose passes every check. It plays through a settle: the recorded edge "
        "velocity decelerates to a stop, then a zero-velocity bridge reaches rest. Only "
        "boundary-envelope checks may be waived for it (`blend.SETTLE_WAIVABLE_REASONS`); finite "
        "values, bone lengths, wrist/joint speed, torso/head intersection, contact handshape and "
        "excursion stay mandatory. The seam reports `mode: \"reviewed-direct\"`, `passed: false` "
        "and the exact `waivedChecks`."
    )
    lines.append(
        "- Every Rokoko combined FBX opens with a one-frame reference **T-pose**. It is trimmed "
        "before composition (`segment.CORRUPT_WRIST_SPEED_CM_S`); before that fix it survived on "
        "some takes and became the rest pose, which is why 10 reviewed signs were rejected."
    )
    lines.append("")
    lines.append("## Readiness states")
    lines.append("")
    lines.append("| State | Meaning |")
    lines.append("|---|---|")
    lines.append("| `subtitle-video-plan-ready` | Reviewed phases exist and the video-plan policy (`compose_service.compose_playable`) produces playable motion. |")
    lines.append("| `awaiting-phase-review` | Imported and canonical, but its Start/Sign/End timestamps have not been reviewed; video plans refuse it. |")
    lines.append("| `imported-not-canonical` | Clip exists but is not the canonical take for its gloss. |")
    lines.append("| `failed-or-missing` | Raw source, validation, ingestion or composition failed. |")
    lines.append("")
    lines.append("## 27-asset table")
    lines.append("")
    lines.append(
        "| # | Gloss | Source file | Import file | Clip ID | Duration (s) | "
        "Sign start/end (s) | Reviewed | Canonical | Direct playback | Blend | Video-plan ready | State |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, row in enumerate(rows, start=1):
        start = row["proposedSignStartSeconds"]
        end = row["proposedSignEndSeconds"]
        window = f"{start} – {end}" if start is not None else "—"
        lines.append(
            f"| {i} | `{row['gloss']}` | `{row['sourceFile']}` | `{row['importFile']}` | "
            f"{row['clipId'] if row['clipId'] is not None else '—'} | "
            f"{row['durationSeconds'] if row['durationSeconds'] is not None else '—'} | "
            f"{window} | {'yes' if row['phaseReviewed'] else 'no'} | "
            f"{'yes' if row['isCanonical'] else 'no'} | "
            f"{'✅' if row['directPlaybackReady'] else '❌'} | "
            f"`{row['blendStatus'] or '—'}` | "
            f"{'✅' if row['videoPlanReady'] else '❌'} | `{row['state']}` |"
        )
    lines.append("")

    review_rows = [r for r in rows if r["imported"] and not r["phaseReviewed"]]
    lines.append("## Manual review queue — required before subtitle/video-plan playback")
    lines.append("")
    if not review_rows:
        lines.append(f"Empty: all {len(rows)} imported clips have human-reviewed boundaries.")
        lines.append("")
    else:
        lines.append(
            f"{len(review_rows)} of {len(rows)} imported clips have only *detected* (unreviewed) phase "
            "boundaries. `app/services/video_plan_service.py::prepare_plan` refuses to compose any unit "
            "whose clip is not marked `qc.phases.reviewed=true`, so every subtitle/video-plan unit "
            "touching these glosses will currently be rejected with "
            "\"`<GLOSS> needs reviewed phase timestamps.`\" "
            "A reviewer should open **Capture → Edit timestamps** for each gloss below, inspect the "
            "proposed Start/Sign/End window, correct it against the actual recording, and save — which "
            "calls `PATCH /api/v1/signs/{clipId}/phases` and sets `phase_reviewed=true` honestly, this "
            "time because a person actually looked at it."
        )
        lines.append("")
        lines.append(
            "| Priority | Gloss | Clip ID | Proposed sign start (s) | Proposed sign end (s) | "
            "Plays today? | QC warnings |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        review_rows_sorted = sorted(review_rows, key=lambda r: r["directPlaybackReady"])  # False first
        for row in review_rows_sorted:
            warnings = "; ".join(row["qcWarnings"]) or "—"
            priority = "**urgent**" if not row["directPlaybackReady"] else "normal"
            plays_today = "no (409)" if not row["directPlaybackReady"] else "yes"
            lines.append(
                f"| {priority} | `{row['gloss']}` | {row['clipId']} | {row['proposedSignStartSeconds']} | "
                f"{row['proposedSignEndSeconds']} | {plays_today} | {warnings} |"
            )
        lines.append("")
        urgent = [r for r in review_rows if not r["directPlaybackReady"]]
        if urgent:
            lines.append(
                f"The {len(urgent)} **urgent** rows above (`{', '.join(r['gloss'] for r in urgent)}`) "
                "currently fail blend-quality validation even for standalone playback "
                "(`GET /api/v1/signs/{clipId}/track` returns 409). Their detected Sign window still "
                "includes motion too fast to bridge from rest — typically the true preparation/retraction "
                "edge was folded into the detected \"sign\" because nobody has told the pipeline otherwise. "
                "Example rejection reason:"
            )
            lines.append("")
            lines.append(f"> {urgent[0]['directPlaybackDetail']}")
            lines.append("")

    lines.append("## Direct signs vs. subtitle aliases vs. fallback spelling")
    lines.append("")
    lines.append(
        "- All 23 required word glosses (`HELLO` … `AWAY`) are registered as single-word *candidate* "
        f"patterns in `backend/app/services/isl_patterns.json` (registry version {registry_version}), "
        "so a subtitle unit whose text is exactly that word resolves to that one gloss via "
        "`translate_service.interpret` / `video_plan_service.resolve_caption`."
    )
    lines.append(
        "- **ADVICE** is documented here as a subtitle alias of **ADVISE**: the `advise` pattern's "
        "`forms` list is `[\"advise\", \"advice\"]`, both mapping to the single gloss `ADVISE`. "
        "There is exactly one `SignClip` row for `ADVISE` — no duplicate motion asset was created."
    )
    lines.append(
        "- **BEND** is *not* a direct sign and has no gloss or pattern of its own. It is only "
        "reachable as an extension fallback plan: the literal caption-policy fallback in "
        "`video_plan_service.resolve_caption` (and the live-speech equivalent in "
        "`live_translate_service.interpret_live`) spells any word with no pattern/alias match using "
        "per-letter canonical alphabet clips, so `bend` would resolve to the sign sequence "
        "**B → E → N → D** using the four alphabet clips imported here. This was verified at the "
        "word-resolution layer (`resolve_caption(\"bend\")` returns four fingerspelled items in that "
        "order) but, like every other asset in this library, is still blocked from actually playing "
        "through a video plan until those four letter clips get human phase review (see the queue "
        "above)."
    )
    lines.append("")
    lines.append(
        "## Out of scope (per task instructions)\n\n"
        "The Chrome extension, YouTube UI/subtitle scraper, Unity rebuild, and the separate "
        "statistical-equivalence/research validation pipeline were not touched by this task."
    )
    lines.append("")

    (OUT_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
