"""Single-camera video landmarks with explicit visibility and editable CSV output."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .fbx_motion import JOINTS
from .mixed_effects import ValidationError

POSE_INDICES = (11, 12, 23, 24, 15, 16)
COLUMNS = ("time_s", *(
    f"{joint}_{field}" for joint in JOINTS for field in ("x", "y", "confidence")
))


@dataclass(frozen=True)
class VideoPose:
    times: np.ndarray
    xy: np.ndarray  # frames x six joints x image-normalized xy
    confidence: np.ndarray


def read_pose_csv(path: str | Path) -> VideoPose:
    path = Path(path)
    try:
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            if not set(COLUMNS).issubset(reader.fieldnames or []):
                raise ValidationError(f"{path.name}: missing video landmark columns.")
            rows = list(reader)
    except OSError as exc:
        raise ValidationError(f"Cannot read video landmarks: {exc}") from exc
    if len(rows) < 2:
        raise ValidationError(f"{path.name}: at least two landmark frames are required.")
    times = np.empty(len(rows), dtype=float)
    xy = np.full((len(rows), len(JOINTS), 2), np.nan, dtype=float)
    confidence = np.zeros((len(rows), len(JOINTS)), dtype=float)
    for index, row in enumerate(rows):
        try:
            times[index] = float(row["time_s"])
            for joint, name in enumerate(JOINTS):
                values = [row[f"{name}_{axis}"].strip() for axis in ("x", "y", "confidence")]
                if all(values):
                    x, y, score = map(float, values)
                    if not np.isfinite([x, y, score]).all() or not (0 <= x <= 1 and 0 <= y <= 1 and 0 <= score <= 1):
                        raise ValueError("out-of-range video landmark")
                    xy[index, joint] = (x, y)
                    confidence[index, joint] = score
                elif any(values):
                    raise ValueError("partially missing video landmark")
        except (ValueError, TypeError, KeyError) as exc:
            raise ValidationError(f"{path.name}: invalid landmark row {index + 2}: {exc}") from exc
    if not np.isfinite(times).all() or times[0] < 0 or np.any(np.diff(times) <= 0):
        raise ValidationError(f"{path.name}: frame timestamps must be finite and strictly increasing.")
    return VideoPose(times, xy, confidence)


def extract_video_pose(video: str | Path, model: str | Path, output: str | Path) -> dict:
    """Run MediaPipe Pose Landmarker in VIDEO mode; missing joints stay missing."""
    try:
        import cv2
        import mediapipe as mp
    except ImportError as exc:
        raise ValidationError(
            "Video extraction requires OpenCV and MediaPipe; "
            "install backend/requirements-validation-video.txt."
        ) from exc
    video, model, output = Path(video), Path(model), Path(output)
    if not video.is_file() or not model.is_file():
        raise ValidationError("Both reference video and MediaPipe pose model must exist.")
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValidationError(f"Could not decode {video}.")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if not np.isfinite(fps) or fps <= 0:
        capture.release()
        raise ValidationError(f"{video.name}: invalid video frame rate.")
    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1,
    )
    rows = []
    previous_ms = -1
    try:
        with mp.tasks.vision.PoseLandmarker.create_from_options(options) as landmarker:
            frame_index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                # Decoder timestamps may be unset; frame_index/fps remains reproducible.
                clock_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC))
                if not np.isfinite(clock_ms) or clock_ms <= previous_ms:
                    clock_ms = frame_index * 1000.0 / fps
                timestamp_ms = max(previous_ms + 1, int(round(clock_ms)))
                previous_ms = timestamp_ms
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect_for_video(image, timestamp_ms)
                row = {"time_s": timestamp_ms / 1000.0}
                landmarks = result.pose_landmarks[0] if len(result.pose_landmarks) == 1 else None
                for name, pose_index in zip(JOINTS, POSE_INDICES):
                    if landmarks is None:
                        row.update({f"{name}_{axis}": "" for axis in ("x", "y", "confidence")})
                        continue
                    point = landmarks[pose_index]
                    visibility = getattr(point, "visibility", None)
                    presence = getattr(point, "presence", None)
                    score = min(float(1.0 if visibility is None else visibility),
                                float(1.0 if presence is None else presence))
                    if not np.isfinite([point.x, point.y, score]).all() or not (0 <= point.x <= 1 and 0 <= point.y <= 1):
                        row.update({f"{name}_{axis}": "" for axis in ("x", "y", "confidence")})
                    else:
                        row.update({f"{name}_x": point.x, f"{name}_y": point.y,
                                    f"{name}_confidence": max(0.0, min(1.0, score))})
                rows.append(row)
                frame_index += 1
    finally:
        capture.release()
    if len(rows) < 2:
        raise ValidationError(f"{video.name}: no usable frames were decoded.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return {"video": str(video), "landmarks": str(output), "frames": len(rows),
            "frame_rate": fps, "pose_model": str(model)}
