import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import analysis
from app.services import analysis_service as service

RUN_JOB = service.run_job


def test_recording_relationship_cannot_be_overridden_by_sync_metadata():
    from pydantic import ValidationError

    separate = analysis.Options(
        pairing_confirmed=True, recording_relationship="separate_repetitions"
    )
    assert separate.recording_relationship == "separate_repetitions"
    assert analysis.Options(pairing_confirmed=True).recording_relationship == "unknown"
    with pytest.raises(ValidationError, match="Synchronized accuracy requires"):
        analysis.Options(
            pairing_confirmed=True,
            recording_relationship="separate_repetitions",
            synchronization={"suit": {}},
        )


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "analysis_dir", tmp_path / "analyses")
    monkeypatch.setattr(
        service, "readiness", lambda: {"ready": True, "message": "Ready"}
    )
    monkeypatch.setattr(service, "run_job", lambda _: None)
    app = FastAPI()
    app.include_router(analysis.router)
    with TestClient(app) as client:
        yield client


def upload(client, options=None, **files):
    sources = {
        "motioncapture_fbx": ("same.fbx", b"motion capture"),
        "old_fbx": ("same.fbx", b"old capture"),
        "reference_video": ("action.mp4", b"video"),
    }
    sources.update(files)
    return client.post(
        "/analyses",
        files=sources,
        data={"options": json.dumps(options or {"pairing_confirmed": True})},
    )


def test_uploads_are_isolated_and_status_survives_reload(client):
    first = upload(client).json()
    second = upload(client).json()
    assert first["jobId"] != second["jobId"]
    directory = service.job_directory(first["jobId"])
    assert (directory / "motioncapture.fbx").read_bytes() == b"motion capture"
    assert (directory / "old.fbx").read_bytes() == b"old capture"
    assert client.get(f"/analyses/{first['jobId']}").json()["status"] == "queued"
    assert (
        client.get(f"/analyses/{first['jobId']}/files/report.html").status_code == 409
    )


@pytest.mark.parametrize(
    "options,files",
    [
        ({"pairing_confirmed": False}, {}),
        ({"pairing_confirmed": True, "windows": {"video": [3, 2]}}, {}),
        ({"pairing_confirmed": True, "synchronization": {"suit": []}}, {}),
        (
            {
                "pairing_confirmed": True,
                "synchronization": {"suit": {"clock_verified": True}},
            },
            {},
        ),
        (None, {"motioncapture_fbx": ("data.txt", b"text")}),
        (None, {"reference_video": ("empty.mp4", b"")}),
    ],
)
def test_bad_requests_leave_no_partial_jobs(client, options, files):
    assert upload(client, options, **files).status_code == 400
    assert not service.settings.analysis_dir.exists() or not list(
        service.settings.analysis_dir.iterdir()
    )


def test_upload_limit_and_missing_runtime_are_visible(client, monkeypatch):
    monkeypatch.setattr(analysis, "FBX_LIMIT", 3)
    assert upload(client).status_code == 413
    monkeypatch.setattr(
        service, "readiness", lambda: {"ready": False, "message": "Missing pose model"}
    )
    response = upload(client)
    assert response.status_code == 503
    assert response.json()["detail"] == "Missing pose model"


def test_results_and_artifacts_are_restricted_to_completed_job(client):
    job = upload(client).json()["jobId"]
    directory = service.job_directory(job)
    results = directory / "results"
    results.mkdir()
    summary = {
        "artifacts": {"traces": {"shape": "shape.csv"}, "figures": ["curve.svg"], "full_sequence_overlay": "full_sequence_overlay.mp4"}
    }
    (results / "summary.json").write_text(json.dumps(summary))
    (results / "report.html").write_text("<h1>Comparison</h1>")
    (results / "curve.png").write_bytes(b"png")
    (results / "full_sequence_overlay.mp4").write_bytes(b"overlay")
    service.write_status(directory, "done")
    assert client.get(f"/analyses/{job}").json()["summary"] == summary
    response = client.get(f"/analyses/{job}/files/report.html")
    assert response.status_code == 200
    assert "sandbox" in response.headers["content-security-policy"]
    assert client.get(f"/analyses/{job}/files/curve.png").status_code == 200
    overlay = client.get(f"/analyses/{job}/files/full_sequence_overlay.mp4")
    assert overlay.status_code == 200
    assert overlay.headers["content-type"] == "video/mp4"
    assert client.get(f"/analyses/{job}/files/worker.log").status_code == 404
    assert client.get("/analyses/not-a-job").status_code == 404


def test_failed_native_worker_and_interrupted_job_do_not_stay_processing(
    client, monkeypatch
):
    job = upload(client).json()["jobId"]
    directory = service.job_directory(job)
    monkeypatch.setattr(
        service.subprocess,
        "run",
        lambda *a, **kw: type("Process", (), {"returncode": -11})(),
    )
    RUN_JOB(directory)
    assert service.read_status(directory)["status"] == "failed"
    service.write_status(directory, "extracting", updatedAt=time.time() - 901)
    assert service.read_status(directory)["status"] == "failed"
