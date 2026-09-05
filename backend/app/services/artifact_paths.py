"""Locate clip artifacts whose stored absolute path no longer points at this checkout.

Ingest records absolute paths, so moving or renaming the project directory orphans every row: the
landmark file is still on disk, but `clip_path` names the old location and composing reports
"has no landmark frames" for every sign. Artifact and upload names are unique within their
directory, so falling back to the configured directory recovers the file without a re-ingest.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings


def _resolve(stored: str | Path, directory: Path) -> Path:
    path = Path(stored)
    if path.exists() or not path.name:
        return path
    relocated = directory / path.name
    return relocated if relocated.exists() else path


def clip_file(stored: str | Path) -> Path:
    """The `.signclip` (or sibling artifact) for a stored clip path."""
    return _resolve(stored, settings.clip_dir)


def source_file(stored: str | Path) -> Path:
    """The uploaded CSV a clip was retargeted from."""
    return _resolve(stored, settings.upload_dir)
