"""Locate motion artifacts whose stored absolute path no longer points at this checkout.

Ingest records absolute paths, so moving or renaming the project directory orphans every row: the
normalized motion file is still on disk, but `clip_path` names the old location. Artifact and
upload names are unique within their directory, so falling back to the configured directory
recovers the file without a re-ingest.
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
    """The normalized motion artifact (or a legacy `.signclip`) for a stored clip path."""
    return _resolve(stored, settings.clip_dir)


def source_file(stored: str | Path) -> Path:
    """The immutable FBX source (or legacy CSV) a clip was normalized from."""
    return _resolve(stored, settings.upload_dir)
