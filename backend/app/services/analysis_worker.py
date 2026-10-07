"""Private analysis worker: validate clocks, extract landmarks, build a case report."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from app.core.config import settings
from app.services.analysis_service import write_status
from app.validation.case_study import run_case_study
from app.validation.fbx_motion import load_motion
from app.validation.mixed_effects import ValidationError
from app.validation.trials import sha256
from app.validation.video_pose import extract_video_pose, read_pose_csv


def video_window(times, supplied=None):
    """Default to decoded samples; only absorb sub-millisecond input rounding."""
    first, last = float(times[0]), float(times[-1])
    if supplied is None:
        return [first, last]
    start, end = supplied
    if start < first - 0.0005 or end > last + 0.0005 or start >= end:
        raise ValidationError(
            f"video: action timestamps must be within the decoded landmark clock, {first:.6f}–{last:.6f} seconds."
        )
    bounds = [max(start, first), min(end, last)]
    if bounds[0] >= bounds[1]:
        raise ValidationError("Video action interval contains no decoded samples.")
    return bounds


def process(directory: Path):
    import cv2

    options = json.loads((directory / "options.json").read_text())
    files = options["files"]
    paths = {key: directory / filename for key, filename in files.items()}
    capture = cv2.VideoCapture(str(paths["reference_video"]))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if (
            not capture.isOpened()
            or not all(map(math.isfinite, (fps, frames)))
            or fps <= 0
            or frames < 2
        ):
            raise ValidationError(
                "The reference video could not be decoded. Use a valid MP4, MOV, or M4V file."
            )
        duration = (frames - 1) / fps
        if duration > 120:
            raise ValidationError(
                "Use a reference video of one action, at most two minutes long."
            )
    finally:
        capture.release()
    durations = {"video": duration}
    for label, key in (("suit", "suit_fbx"), ("non_suit", "non_suit_fbx")):
        if key in paths:
            motion = load_motion(paths[key], include_elbows=True)
            durations[label] = float(motion.times[-1])
    windows = {}
    for label, duration in durations.items():
        supplied = options.get("windows", {}).get(label)
        start, end = supplied if supplied else (0, duration)
        if not 0 <= start < end <= duration + 1e-6:
            raise ValidationError(
                f"{label}: action timestamps must be within 0–{duration:.3f} seconds."
            )
        windows[label] = [start, min(end, duration)]
    write_status(directory, "extracting")
    pose = directory / "reference_pose.csv"
    extract_video_pose(
        paths["reference_video"],
        settings.analysis_pose_model,
        pose,
        include_elbows=True,
        hand_model=settings.analysis_hand_model,
    )
    paths["video_landmarks"] = pose
    extracted = read_pose_csv(pose, include_elbows=True)
    windows["video"] = video_window(
        extracted.times, options.get("windows", {}).get("video")
    )
    metadata = pose.with_suffix(".metadata.json")
    relationship = options.get("recording_relationship", "unknown")
    attestation = {
        "same_performance": "Website uploader confirmed the exact same physical performance",
        "separate_repetitions": "Website uploader confirmed separate repetitions of the same action",
        "unknown": "Website uploader could not confirm matching physical performances",
    }[relationship]
    manifest = {
        "schema_version": 1,
        "trials": [
            {
                "performance_id": options["action"],
                "action_id": options["action"],
                "performer_id": "uploaded-performer",
                "repetition": "01",
                "pairing_verified_by": attestation,
                "recording_relationship": relationship,
                "reference_independent": True,
                **{key: path.name for key, path in paths.items()},
                "sha256": {key: sha256(path) for key, path in paths.items()},
                "windows": windows,
                "calibration_phase": options["calibration_phase"],
            }
        ],
        "case_study": {
            "video_metadata": metadata.name,
            "video_metadata_sha256": sha256(metadata),
            "pose_model": str(settings.analysis_pose_model.resolve()),
            "hand_model": str(settings.analysis_hand_model.resolve()),
            "review": {
                "tracking": "unreviewed",
                "boundaries": "provisional",
                "calibration": "provisional",
            },
            "review_notes": [
                "Uploaded files and automatically extracted landmarks require visual review.",
                "File labels supplied by the uploader: "
                + json.dumps(options["original_names"]),
            ],
            "reference_view": options.get("reference_view", "automatic"),
            "tolerance_profile": options.get("tolerance_profile", "replication"),
            "synchronization": options.get("synchronization", {}),
            "tolerance_policy": "exploratory; no justified equivalence bounds",
        },
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    write_status(directory, "scoring")
    run_case_study(manifest_path, directory / "results")
    write_status(directory, "done")


if __name__ == "__main__":
    directory = Path(sys.argv[1]).resolve()
    try:
        process(directory)
    except (ValidationError, OSError, ValueError, ImportError) as exc:
        write_status(directory, "failed", error=str(exc))
        sys.exit(2)
