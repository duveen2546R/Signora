import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_session
from app.main import app
from app.models import Gloss, SignClip
from app.ingest.compose import prepare
from app.ingest.landmarks import LandmarkSkeleton, to_landmarks
from app.services.phase_service import edit_phases


@pytest.fixture
def stored(hello_take, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    raw = to_landmarks(hello_take)
    path = tmp_path / "original.signclip"
    path.write_bytes(b"original baked motion")
    path.with_suffix(".landmarks.json").write_text(json.dumps(raw.to_payload()))
    csv = tmp_path / "hello.csv"
    csv.write_bytes((Path(__file__).parent / "fixtures" / "hello.csv").read_bytes())
    with Session(engine, expire_on_commit=False) as session:
        gloss = Gloss(name="HELLO")
        session.add(gloss)
        session.flush()
        clip = SignClip(gloss_id=gloss.id, rig_digest="rig", take=1, is_canonical=True,
                        source_csv=str(csv), clip_path=str(path), content_hash="original",
                        fps=raw.fps, frame_count=raw.frame_count, duration=raw.duration,
                        byte_size=21, qc={})
        session.add(clip)
        session.commit()
        yield session, clip, raw


def test_phase_edit_preserves_motion_source_identity_and_old_artifacts(stored):
    session, clip, raw = stored
    old_path = Path(clip.clip_path)
    source = Path(clip.source_csv).read_bytes()
    old_landmarks = old_path.with_suffix(".landmarks.json").read_bytes()
    old_id = clip.id
    edited = edit_phases(session, clip, 0.3, 1.6, "original")
    assert edited.id == old_id and edited.is_canonical
    assert edited.content_hash != "original"
    new_payload = json.loads(Path(edited.clip_path).with_suffix(".landmarks.json").read_text())
    for channel in ("pose", "leftHand", "rightHand"):
        assert new_payload[channel] == json.loads(old_landmarks)[channel]
    assert old_path.exists() and old_path.with_suffix(".landmarks.json").read_bytes() == old_landmarks
    assert Path(clip.source_csv).read_bytes() == source
    assert clip.qc["linguisticReview"]["status"] == "pending"
    assert clip.qc["phaseHistory"][0]["contentHash"] == "original"
    first_hash = edited.content_hash
    edit_phases(session, clip, 0.4, 1.6, first_hash)
    assert clip.content_hash != first_hash


@pytest.mark.parametrize("start,end", [(-1, 1), (1, 0.5), (0.2, 99), (0.01, 1), (0.2, 0.3), (float('nan'), 1)])
def test_invalid_edits_never_update_database(stored, start, end):
    session, clip, _ = stored
    with pytest.raises(ValueError):
        edit_phases(session, clip, start, end)
    assert clip.content_hash == "original"


def test_stale_editor_is_rejected(stored):
    session, clip, _ = stored
    with pytest.raises(ValueError, match="changed"):
        edit_phases(session, clip, 0.3, 1.6, "stale")


def test_reviewed_sign_overlapping_corrupt_frames_cannot_be_trimmed(hello_take):
    raw = to_landmarks(hello_take)
    corrupt = replace(raw,
        pose=np.concatenate([raw.pose, raw.pose[-1:] + 1]),
        left_hand=np.concatenate([raw.left_hand, raw.left_hand[-1:] + 1]),
        right_hand=np.concatenate([raw.right_hand, raw.right_hand[-1:] + 1]),
        sign_start_s=0.2, sign_end_s=(raw.frame_count + 1) / raw.fps, phase_reviewed=True,
        timestamps=np.append(raw.times, raw.duration))
    with pytest.raises(ValueError, match="corrupt frames"):
        prepare(corrupt, LandmarkSkeleton.from_takes(raw))


def test_edit_endpoint_and_old_asset_urls(stored):
    session, clip, _ = stored
    app.dependency_overrides[get_session] = lambda: session
    try:
        with TestClient(app) as client:
            response = client.patch(f"/api/v1/signs/{clip.id}/phases", json={
                "signStartSeconds": 0.3, "signEndSeconds": 1.6, "expectedContentHash": "original"})
            assert response.status_code == 200, response.text
            updated = response.json()
            assert updated["id"] == clip.id
            assert client.get(updated["landmarksUrl"]).status_code == 200
            historical = client.get("/api/v1/clips/original.landmarks.json")
            assert historical.status_code == 200
            assert "immutable" in historical.headers["cache-control"]
            assert client.get("/api/v1/clips/original.signclip").content == b"original baked motion"
    finally:
        app.dependency_overrides.clear()


def test_raw_preview_does_not_register_a_capture(stored):
    session, _, _ = stored
    app.dependency_overrides[get_session] = lambda: session
    try:
        with TestClient(app) as client:
            source = Path(__file__).parent / "fixtures" / "hello.csv"
            response = client.post("/api/v1/captures/preview", files={"file": ("hello.csv", source.read_bytes(), "text/csv")})
            assert response.status_code == 200, response.text
            assert response.json()["frameCount"] > 1
    finally:
        app.dependency_overrides.clear()


def test_library_edit_must_agree_with_csv_phase_column(stored):
    import pandas as pd
    session, clip, raw = stored
    path = Path(clip.source_csv)
    df = pd.read_csv(path)
    df["Phase"] = ["start" if t < 0.3 else "sign" if t < 1.6 else "end" for t in raw.times]
    df.to_csv(path, index=False)
    with pytest.raises(ValueError, match="conflict with the CSV Phase"):
        edit_phases(session, clip, 0.4, 1.6)
    assert clip.content_hash == "original"


def test_off_grid_boundary_is_rejected_before_publishing(stored):
    session, clip, _ = stored
    with pytest.raises(ValueError, match="not a CSV Timestamp"):
        edit_phases(session, clip, 0.31, 1.6)
    assert clip.content_hash == "original"
