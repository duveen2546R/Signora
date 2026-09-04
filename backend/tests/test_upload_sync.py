import datetime as dt
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.models import Gloss, SignClip
from app.services import ingest_service


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as value:
        yield value


def test_directory_discovery_finds_only_unregistered_or_updated_csvs(session, tmp_path):
    registered = tmp_path / "hello_01.csv"
    new_file = tmp_path / "father_01.csv"
    registered.write_text("registered")
    new_file.write_text("new")

    gloss = Gloss(name="HELLO", english="hello")
    session.add(gloss)
    session.flush()
    session.add(SignClip(
        gloss_id=gloss.id, rig_digest="d" * 16, take=1, is_canonical=True,
        source_csv=str(registered), clip_path="hello.signclip", content_hash="hello",
        fps=60.0, frame_count=60, duration=1.0, byte_size=1, qc={},
        created_at=dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(minutes=1),
    ))
    session.flush()

    assert ingest_service.uploads_needing_ingest(session, tmp_path) == [new_file]


def test_directory_sync_submits_each_discovered_capture(session, tmp_path, monkeypatch):
    paths = [tmp_path / "father_01.csv", tmp_path / "hello_01.csv"]
    for path in paths:
        path.write_text("csv")

    created = []
    ingested = []
    monkeypatch.setattr(ingest_service, "active_rig", lambda _session: object())

    def create(_session, path):
        created.append(path)
        return SimpleNamespace(id=f"job-{path.stem}")

    monkeypatch.setattr(ingest_service, "create_job", create)
    monkeypatch.setattr(
        ingest_service, "run_ingest", lambda _session, job_id: ingested.append(job_id),
    )

    jobs = ingest_service.sync_upload_directory(session, tmp_path)
    assert created == paths
    assert ingested == jobs == ["job-father_01", "job-hello_01"]
