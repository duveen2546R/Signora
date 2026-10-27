import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.services import ingest_service


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as value:
        yield value


def test_capture_job_persists_user_phase_input(session, tmp_path):
    path = tmp_path / "hello_01.csv"
    path.write_text("csv")
    job = ingest_service.create_job(session, path, 0.75, 2.25)
    assert job.qc["phaseInput"] == {
        "signStartSeconds": 0.75,
        "signEndSeconds": 2.25,
    }


def test_phase_edit_changes_content_identity():
    first = ingest_service.content_hash_for(
        b"same motion", {"signStartSeconds": 0.5, "signEndSeconds": 1.5}
    )
    edited = ingest_service.content_hash_for(
        b"same motion", {"signStartSeconds": 0.6, "signEndSeconds": 1.5}
    )
    assert first != edited
