"""Exercise the real native FBX reader through preview, ingest, replacement, and serving."""
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import captures
from app.core.config import settings
from app.core.db import Base, get_session
from app.ingest.fbx import parse_fbx
from app.ingest.landmarks import ARKIT_BLENDSHAPES
from app.main import app
from app.models import IngestJob, SignClip

FIXTURE = Path(__file__).parent / "fixtures" / "combined_mixamo.fbx"


@pytest.fixture
def capture_client(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for key in ("upload_dir", "clip_dir"):
        directory = tmp_path / key
        directory.mkdir()
        monkeypatch.setattr(settings, key, directory)
    monkeypatch.setattr(captures, "SessionLocal", factory)
    def session():
        with factory() as value:
            yield value
    app.dependency_overrides[get_session] = session
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.pop(get_session, None)
        engine.dispose()


def upload(client, name="hello_01.fbx", body=None, phases=None):
    return client.post("/api/v1/captures", files={
        "file": (name, FIXTURE.read_bytes() if body is None else body, "application/octet-stream"),
    }, data=phases if phases is not None else {"sign_start_seconds": "0.2", "sign_end_seconds": "0.8"})


def test_native_fbx_preserves_full_strength_animated_face():
    for _ in range(3):  # Native wrappers must survive repeated scene destruction and loading.
        take = parse_fbx(FIXTURE)
        jaw = ARKIT_BLENDSHAPES.index("jawOpen")
        assert take.frame_count == 61
        np.testing.assert_allclose(take.face_blendshapes[[0, 30, 60], jaw], [0, 1, 0])
        assert np.isfinite(take.pose).all()
        np.testing.assert_allclose(take.left_hand[:, 0], take.pose[:, 15])
        np.testing.assert_allclose(take.right_hand[:, 0], take.pose[:, 16])


def test_preview_upload_and_reupload_preserve_motion_and_clip_identity(capture_client):
    client, factory = capture_client
    preview = client.post("/api/v1/captures/preview", files={"file": ("hello_01.fbx", FIXTURE.read_bytes())})
    assert preview.status_code == 200, preview.text
    assert preview.json()["faceBlendshapes"][30][ARKIT_BLENDSHAPES.index("jawOpen")] == 1
    ids = []
    for _ in range(2):
        response = upload(client)
        assert response.status_code == 202, response.text
        result = client.get(f"/api/v1/captures/{response.json()['jobId']}").json()
        assert result["status"] == "done", result
        assert result["qc"]["face"]["activeChannelCount"] == 1
        ids.append(result["clipId"])
    assert ids[0] == ids[1]
    with factory() as session:
        clip = session.get(SignClip, ids[0])
        assert len(session.scalars(select(SignClip)).all()) == 1
        assert len(session.scalars(select(IngestJob)).all()) == 2
        stored = json.loads(Path(clip.clip_path).read_text())
        assert stored["faceBlendshapes"] == preview.json()["faceBlendshapes"]
        assert clip.is_canonical and clip.qc["phases"]["reviewed"]
        served = client.get(f"/api/v1/clips/{clip.content_hash}.motion.json")
        assert served.status_code == 200
        assert served.json() == stored
        raw = client.get(f"/api/v1/signs/{clip.id}/raw")
        assert raw.status_code == 200, raw.text
        assert raw.json()["faceBlendshapes"] == stored["faceBlendshapes"]
        track = client.get(f"/api/v1/signs/{clip.id}/track")
        assert track.status_code == 200, track.text
        assert np.asarray(track.json()["faceBlendshapes"])[:, ARKIT_BLENDSHAPES.index("jawOpen")].max() > 0.9


@pytest.mark.parametrize("body,phases", [
    (b"", None), (b"not an FBX", None),
    (None, {}), (None, {"sign_start_seconds": "0.8", "sign_end_seconds": "0.2"}),
])
def test_rejected_uploads_leave_no_sources_or_jobs(capture_client, body, phases):
    client, factory = capture_client
    response = upload(client, body=body, phases=phases)
    assert response.status_code == 400, response.text
    assert not list(settings.upload_dir.iterdir())
    with factory() as session:
        assert not session.scalars(select(IngestJob)).all()


def test_oversize_upload_returns_actionable_error_and_cleans_up(capture_client, monkeypatch):
    client, _ = capture_client
    monkeypatch.setattr(captures, "MAX_CAPTURE_BYTES", 10)
    assert upload(client).status_code == 413
    assert not list(settings.upload_dir.iterdir())
