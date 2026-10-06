"""Persistent local video/FBX analysis jobs, processed outside the API interpreter."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.core.config import settings

_WORKER_SLOT = threading.Semaphore(1)
JOB_STAGES = {"queued", "inspecting", "extracting", "scoring"}


def readiness():
    missing = [
        name
        for name in ("ufbx", "cv2", "mediapipe", "matplotlib", "scipy")
        if importlib.util.find_spec(name) is None
    ]
    model = settings.analysis_pose_model.is_file()
    return {
        "ready": not missing and model,
        "missingDependencies": missing,
        "poseModelAvailable": model,
        "message": "Ready to compare video and FBX movement."
        if not missing and model
        else "Prepare the backend with requirements-validation-video.txt and configure SIGNSURE_ANALYSIS_POSE_MODEL.",
    }


def write_status(directory: Path, status: str, **extra):
    payload = {
        "jobId": directory.name,
        "status": status,
        "updatedAt": time.time(),
        **extra,
    }
    temporary = directory / ".status.tmp"
    temporary.write_text(json.dumps(payload, allow_nan=False))
    temporary.replace(directory / "status.json")
    return payload


def job_directory(job_id: str):
    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        return None
    directory = settings.analysis_dir / job_id
    return directory if (directory / "status.json").is_file() else None


def read_status(directory: Path):
    payload = json.loads((directory / "status.json").read_text())
    expiry = 3600 if payload["status"] == "queued" else 900
    if payload["status"] in JOB_STAGES and time.time() - payload["updatedAt"] > expiry:
        payload = write_status(
            directory,
            "failed",
            error="Analysis was interrupted. Start a new comparison.",
        )
    return payload


def run_job(directory: Path):
    with _WORKER_SLOT:
        if not directory.exists():
            return
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
        environment["MPLCONFIGDIR"] = str(directory / "plot-cache")
        try:
            write_status(directory, "inspecting")
            with (directory / "worker.log").open("w") as log:
                process = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "app.services.analysis_worker",
                        str(directory),
                    ],
                    stdout=log,
                    stderr=log,
                    env=environment,
                    timeout=600,
                )
            if process.returncode and read_status(directory)["status"] != "failed":
                write_status(
                    directory,
                    "failed",
                    error=(
                        "The local analysis worker could not finish. Check backend video-analysis dependencies "
                        "and native graphics access, then retry."
                    ),
                )
        except subprocess.TimeoutExpired:
            write_status(
                directory,
                "failed",
                error="Analysis exceeded ten minutes. Use a shorter action recording and retry.",
            )
        except Exception:
            write_status(
                directory,
                "failed",
                error="Analysis could not start. Check the backend configuration and retry.",
            )
