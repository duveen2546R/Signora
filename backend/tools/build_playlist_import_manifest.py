"""Create a review-only FBX import manifest from a vocabulary-checklist DOCX.

The tool never changes the sign database and never writes into ``trainer/``.  It only matches
checklist terms to source filenames, so an interpreter can select duplicate takes and verify the
meaning before a separate ingest step is allowed to copy any FBX files.

Run from ``backend/``:

    ./.venv/Scripts/python.exe tools/build_playlist_import_manifest.py \
        --checklist E:/Vocabulary_Checklists_New_Words_Per_Video.docx \
        --videos 2 3 6 7 \
        --json-out ../docs/playlist-import-manifest.json \
        --markdown-out ../docs/playlist-import-plan.md
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET


WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REPO_ROOT = Path(__file__).resolve().parents[2]
TRAINER_DIR = REPO_ROOT / "trainer"


def normalise(value: str) -> str:
    """Compare words case-insensitively without filename punctuation."""
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def source_label(path: Path) -> str:
    """Recover a proposed word label from common Mixamo-export naming variants."""
    label = re.sub(r"_mixamo.*$", "", path.stem, flags=re.IGNORECASE)
    label = re.sub(r"\s*\(\d+\)$", "", label)
    label = re.sub(r"[_\s]+\d+$", "", label)
    return label.strip("_ ")


def gloss_name(word: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", word).strip("_").upper()
    return value or "UNNAMED"


def clean_checklist_word(value: str) -> str:
    """Remove a visible Word checkbox glyph while retaining the vocabulary label."""
    return re.sub(r"^[\s☐☑☒□✓✔]+", "", value).strip()


def _text(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.iter(f"{WORD_NAMESPACE}t"))


def checklist_tables(path: Path) -> Iterator[tuple[int, list[str]]]:
    """Yield ``(video_number, vocabulary)`` in DOCX document order.

    This uses only the OOXML standard library representation so the planning command needs no
    additional package installed in the backend environment.
    """
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))

    current_video: int | None = None
    for child in root.find(f"{WORD_NAMESPACE}body") or []:
        if child.tag == f"{WORD_NAMESPACE}p":
            match = re.match(r"\s*Video\s+(\d+)\b", _text(child))
            if match:
                current_video = int(match.group(1))
            continue
        if child.tag != f"{WORD_NAMESPACE}tbl" or current_video is None:
            continue

        words: list[str] = []
        for cell in child.iter(f"{WORD_NAMESPACE}tc"):
            value = clean_checklist_word(_text(cell))
            if value and value not in words:
                words.append(value)
        yield current_video, words


def candidates_by_word(trainer_dir: Path) -> dict[str, list[str]]:
    candidates: dict[str, list[str]] = defaultdict(list)
    for path in sorted(trainer_dir.glob("*.fbx"), key=lambda value: value.name.casefold()):
        candidates[normalise(source_label(path))].append(path.name)
    return dict(candidates)


def make_manifest(checklist: Path, videos: set[int]) -> dict:
    candidates = candidates_by_word(TRAINER_DIR)
    entries: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for video, words in checklist_tables(checklist):
        if video not in videos:
            continue
        for word in words:
            key = (video, normalise(word))
            if key in seen:
                continue
            seen.add(key)
            matches = candidates.get(key[1], [])
            entries.append({
                "video": video,
                "captionWord": word,
                "proposedGloss": gloss_name(word),
                "sourceCandidates": matches,
                "status": (
                    "missing-source" if not matches
                    else "ready-for-import-review" if len(matches) == 1
                    else "choose-canonical-take"
                ),
                "selectedSource": matches[0] if len(matches) == 1 else None,
                "phaseReviewRequired": bool(matches),
                "interpreterMeaningReviewRequired": bool(matches),
            })

    summary: dict[str, dict[str, int]] = {}
    for video in sorted(videos):
        subset = [entry for entry in entries if entry["video"] == video]
        summary[str(video)] = {
            "checklistWords": len(subset),
            "singleCandidate": sum(entry["status"] == "ready-for-import-review" for entry in subset),
            "duplicateTakeNeedsSelection": sum(entry["status"] == "choose-canonical-take" for entry in subset),
            "missingSource": sum(entry["status"] == "missing-source" for entry in subset),
        }
    return {
        "purpose": "Review-only import plan; no source has been validated, imported, or approved.",
        "checklist": str(checklist),
        "trainerDirectory": str(TRAINER_DIR),
        "videos": sorted(videos),
        "summary": summary,
        "entries": entries,
    }


def markdown(manifest: dict) -> str:
    lines = [
        "# Playlist Vocabulary Import Plan",
        "",
        "This is a review-only plan. A matching filename does not establish that the recording has",
        "the intended ISL meaning. Select duplicate takes, verify meaning with the interpreter, and",
        "review Start Sign End boundaries before importing any source.",
        "",
        "## Coverage",
        "",
        "| Video | Checklist words | Single candidate | Duplicate take review | Missing source |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for video, counts in manifest["summary"].items():
        lines.append(
            f"| {video} | {counts['checklistWords']} | {counts['singleCandidate']} | "
            f"{counts['duplicateTakeNeedsSelection']} | {counts['missingSource']} |"
        )
    lines.extend(["", "## Review Queue", ""])
    for entry in manifest["entries"]:
        if entry["status"] == "ready-for-import-review":
            continue
        sources = ", ".join(f"`{item}`" for item in entry["sourceCandidates"]) or "None"
        lines.append(
            f"- Video {entry['video']} - **{entry['captionWord']}** "
            f"({entry['status']}): {sources}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checklist", type=Path, required=True)
    parser.add_argument("--videos", nargs="+", type=int, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    args = parser.parse_args()

    if not args.checklist.is_file():
        parser.error(f"checklist not found: {args.checklist}")
    manifest = make_manifest(args.checklist, set(args.videos))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    args.markdown_out.write_text(markdown(manifest), encoding="utf-8")
    print(json.dumps(manifest["summary"], indent=2))


if __name__ == "__main__":
    main()
