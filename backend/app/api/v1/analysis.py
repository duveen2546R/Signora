"""Upload one matched video and two FBXs; retrieve persistent analysis results."""

from __future__ import annotations

import json
import math
import shutil
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError as SchemaError, model_validator

from app.core.config import settings
from app.services import analysis_service as service

router = APIRouter(prefix="/analyses", tags=["motion agreement"])
FBX_LIMIT = 100 * 1024 * 1024
VIDEO_LIMIT = 250 * 1024 * 1024


class SyncEvent(BaseModel):
    reviewed: bool = False
    description: str = Field(default="", max_length=2000)
    video_seconds: float = Field(ge=0, allow_inf_nan=False)
    fbx_seconds: float = Field(ge=0, allow_inf_nan=False)


class Synchronization(BaseModel):
    clock_verified: bool = False
    clock_evidence: str = Field(default="", max_length=2000)
    event: SyncEvent | None = None
    video_seconds_per_fbx_second: float = Field(default=1, gt=0, allow_inf_nan=False)
    rate_evidence: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_evidence(self):
        if self.clock_verified:
            if (
                not self.clock_evidence.strip()
                or not self.event
                or not self.event.reviewed
                or not self.event.description.strip()
            ):
                raise ValueError(
                    "Verified timing requires clock evidence and a reviewed matching event."
                )
            if (
                self.video_seconds_per_fbx_second != 1
                and not self.rate_evidence.strip()
            ):
                raise ValueError(
                    "A playback-rate correction requires documented evidence."
                )
        return self


class Options(BaseModel):
    action: str = Field(default="Action comparison", min_length=1, max_length=120)
    pairing_confirmed: bool = False
    recording_relationship: Literal[
        "same_performance", "separate_repetitions", "unknown"
    ] = "unknown"
    windows: dict[Literal["suit", "non_suit", "video"], tuple[float, float]] = Field(
        default_factory=dict
    )
    reference_view: Literal["automatic", "front"] = "automatic"
    calibration_phase: tuple[float, float] = (0.0, 0.15)
    synchronization: dict[Literal["suit", "non_suit"], Synchronization] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def validate_options(self):
        if not self.pairing_confirmed:
            raise ValueError(
                "Confirm the recording relationship and that the video shows the real person independently of the FBX renders."
            )
        if self.recording_relationship != "same_performance" and self.synchronization:
            raise ValueError(
                "Synchronized accuracy requires the exact same performance. Separate repetitions support movement similarity only."
            )
        for label, bounds in {
            **self.windows,
            "calibration": self.calibration_phase,
        }.items():
            start, end = bounds
            if not all(map(math.isfinite, bounds)) or not 0 <= start < end:
                raise ValueError(
                    f"{label}: enter finite start and end times with start < end."
                )
        if self.calibration_phase[1] > 1:
            raise ValueError(
                "Calibration interval must be within 0–100% of the action."
            )
        return self


async def save_upload(upload, destination, suffixes, limit):
    original = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if Path(original).suffix.lower() not in suffixes or "\x00" in original:
        raise HTTPException(
            400, f"Select a {' or '.join(suffixes)} file for {destination.stem}."
        )
    size = 0
    with destination.open("wb") as stream:
        while chunk := await upload.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise HTTPException(
                    413,
                    f"{original}: maximum upload size is {limit // (1024 * 1024)} MB.",
                )
            stream.write(chunk)
    if not size:
        raise HTTPException(400, f"{original}: the file is empty.")
    return original


def require_job(job_id):
    directory = service.job_directory(job_id)
    if directory is None:
        raise HTTPException(404, "This analysis could not be found.")
    return directory


@router.get("/readiness")
def readiness():
    return service.readiness()


@router.post("", status_code=202)
async def create_analysis(
    background: BackgroundTasks,
    motioncapture_fbx: UploadFile,
    reference_video: UploadFile,
    old_fbx: UploadFile | None = None,
    options: str = Form("{}"),
):
    uploads = (motioncapture_fbx, old_fbx, reference_video)
    directory = None
    accepted = False
    try:
        if len(options) > 20000:
            raise HTTPException(400, "Analysis options are too long.")
        try:
            parsed = Options.model_validate_json(options)
        except SchemaError as exc:
            message = "; ".join(
                error["msg"].removeprefix("Value error, ") for error in exc.errors()
            )
            raise HTTPException(400, message) from exc
        if not service.readiness()["ready"]:
            raise HTTPException(503, service.readiness()["message"])
        settings.analysis_dir.mkdir(parents=True, exist_ok=True)
        pending = sum(
            service.read_status(p)["status"] in service.JOB_STAGES
            for p in settings.analysis_dir.iterdir()
            if (p / "status.json").is_file()
        )
        if pending >= 4:
            raise HTTPException(
                429,
                "Four analyses are already queued. Wait for a comparison to finish.",
            )
        directory = settings.analysis_dir / uuid.uuid4().hex
        directory.mkdir()
        video_suffix = Path(reference_video.filename or "").suffix.lower()
        files = {
            "suit_fbx": "motioncapture.fbx",
            "non_suit_fbx": "old.fbx",
            "reference_video": "reference" + video_suffix,
        }
        names = {}
        for upload, key, suffixes, limit in (
            (motioncapture_fbx, "suit_fbx", {".fbx"}, FBX_LIMIT),
            (old_fbx, "non_suit_fbx", {".fbx"}, FBX_LIMIT),
            (reference_video, "reference_video", {".mp4", ".mov", ".m4v"}, VIDEO_LIMIT),
        ):
            if upload is None:
                continue
            names[key] = await save_upload(
                upload, directory / files[key], suffixes, limit
            )

        # Remove non_suit_fbx from files dictionary if it was not uploaded
        if old_fbx is None:
            del files["non_suit_fbx"]

        payload = {
            **parsed.model_dump(mode="json"),
            "files": files,
            "original_names": names,
        }
        (directory / "options.json").write_text(json.dumps(payload))
        status = service.write_status(directory, "queued")
        background.add_task(service.run_job, directory)
        accepted = True
        return status
    finally:
        for upload in uploads:
            if upload is not None:
                await upload.close()
        if directory is not None and not accepted:
            shutil.rmtree(directory)


@router.get("/{job_id}")
def analysis_status(job_id: str):
    directory = require_job(job_id)
    result = service.read_status(directory)
    if result["status"] == "done":
        result["summary"] = json.loads(
            (directory / "results" / "summary.json").read_text()
        )
    return result


@router.get("/{job_id}/files/{filename}")
def analysis_file(job_id: str, filename: str, download: bool = False):
    directory = require_job(job_id)
    if service.read_status(directory)["status"] != "done":
        raise HTTPException(409, "This analysis is not finished yet.")
    results = directory / "results"
    summary = json.loads((results / "summary.json").read_text())
    artifacts = summary["artifacts"]
    allowed = {
        "report.html",
        "summary.json",
        "manifest.json",
        "reference_pose.csv",
        "reference_pose.metadata.json",
        artifacts.get("reference_review"),
        artifacts.get("comparison_overlay"),
        *artifacts["traces"].values(),
        *artifacts.get("figures", []),
    }
    allowed.update(
        name.removesuffix(".svg") + ".png" for name in artifacts.get("figures", [])
    )
    if filename not in allowed:
        raise HTTPException(404, "This result file could not be found.")
    path = (
        directory / filename
        if filename
        in {"manifest.json", "reference_pose.csv", "reference_pose.metadata.json"}
        else results / filename
    )
    if not path.is_file():
        raise HTTPException(404, "This result file could not be found.")
    response = FileResponse(path, filename=filename if download else None)
    if filename == "report.html":
        response.headers["Content-Security-Policy"] = (
            "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
