"""A moved or renamed project must not orphan clips recorded with absolute paths."""
from pathlib import Path

from app.core.config import settings
from app.services.artifact_paths import clip_file, source_file


def test_existing_path_is_returned_unchanged(tmp_path):
    present = tmp_path / "somewhere.signclip"
    present.write_bytes(b"")
    assert clip_file(present) == present


def test_stale_clip_path_recovers_from_the_configured_directory():
    stale = "/old/checkout/backend/data/clips/relocated.signclip"
    artifact = settings.clip_dir / "relocated.signclip"
    artifact.write_bytes(b"")
    try:
        assert clip_file(stale) == artifact
    finally:
        artifact.unlink()


def test_stale_source_csv_recovers_from_the_upload_directory():
    stale = "/old/checkout/backend/data/uploads/relocated.csv"
    upload = settings.upload_dir / "relocated.csv"
    upload.write_text("")
    try:
        assert source_file(stale) == upload
    finally:
        upload.unlink()


def test_missing_file_keeps_the_stored_path_so_errors_name_it():
    stale = "/old/checkout/backend/data/clips/never_ingested.signclip"
    assert clip_file(stale) == Path(stale)
