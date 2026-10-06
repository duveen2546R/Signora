"""Single-camera video landmarks with explicit visibility and editable CSV output."""

from __future__ import annotations

import csv
import json
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .fbx_motion import JOINTS, CASE_JOINTS
from .trials import sha256
from .mixed_effects import ValidationError

POSE_INDICES = (11, 12, 23, 24, 15, 16)
COLUMNS = (
    "time_s",
    *(f"{joint}_{field}" for joint in JOINTS for field in ("x", "y", "confidence")),
)


@dataclass(frozen=True)
class VideoPose:
    times: np.ndarray
    xy: np.ndarray  # frames x six joints x image-normalized xy
    confidence: np.ndarray


def read_pose_csv(path: str | Path, *, include_elbows: bool = False) -> VideoPose:
    path = Path(path)
    joints = CASE_JOINTS if include_elbows else JOINTS
    columns = (
        "time_s",
        *(f"{joint}_{field}" for joint in joints for field in ("x", "y", "confidence")),
    )
    try:
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            if not set(columns).issubset(reader.fieldnames or []):
                raise ValidationError(f"{path.name}: missing video landmark columns.")
            rows = list(reader)
    except OSError as exc:
        raise ValidationError(f"Cannot read video landmarks: {exc}") from exc
    if len(rows) < 2:
        raise ValidationError(
            f"{path.name}: at least two landmark frames are required."
        )
    times = np.empty(len(rows), dtype=float)
    xy = np.full((len(rows), len(joints), 2), np.nan, dtype=float)
    confidence = np.zeros((len(rows), len(joints)), dtype=float)
    for index, row in enumerate(rows):
        try:
            times[index] = float(row["time_s"])
            for joint, name in enumerate(joints):
                values = [
                    row[f"{name}_{axis}"].strip() for axis in ("x", "y", "confidence")
                ]
                if all(values):
                    x, y, score = map(float, values)
                    if not np.isfinite([x, y, score]).all() or not (
                        0 <= x <= 1 and 0 <= y <= 1 and 0 <= score <= 1
                    ):
                        raise ValueError("out-of-range video landmark")
                    xy[index, joint] = (x, y)
                    confidence[index, joint] = score
                elif any(values):
                    raise ValueError("partially missing video landmark")
        except (ValueError, TypeError, KeyError) as exc:
            raise ValidationError(
                f"{path.name}: invalid landmark row {index + 2}: {exc}"
            ) from exc
    if not np.isfinite(times).all() or times[0] < 0 or np.any(np.diff(times) <= 0):
        raise ValidationError(
            f"{path.name}: frame timestamps must be finite and strictly increasing."
        )
    return VideoPose(times, xy, confidence)


def extract_video_pose(
    video: str | Path,
    model: str | Path,
    output: str | Path,
    *,
    include_elbows: bool = False,
    hand_model: str | Path | None = None,
) -> dict:
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
        raise ValidationError(
            "Both reference video and MediaPipe pose model must exist."
        )
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValidationError(f"Could not decode {video}.")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width, height = (
        int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
        int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    )
    joints = CASE_JOINTS if include_elbows else JOINTS
    indices = (*POSE_INDICES, 13, 14) if include_elbows else POSE_INDICES
    columns = (
        "time_s",
        *(f"{joint}_{field}" for joint in joints for field in ("x", "y", "confidence")),
    )
    if not np.isfinite(fps) or fps <= 0:
        capture.release()
        raise ValidationError(f"{video.name}: invalid video frame rate.")
    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model), delegate=mp.tasks.BaseOptions.Delegate.CPU
        ),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1,
    )
    rows = []
    upper_pose, upper_hands = [], []
    previous_ms = -1
    previous_clock_ms = -1.0
    try:
        with ExitStack() as stack:
            landmarker = stack.enter_context(
                mp.tasks.vision.PoseLandmarker.create_from_options(options)
            )
            hand_tracker = None
            crop_tracker = None
            if hand_model is not None and Path(hand_model).is_file():
                hand_tracker = stack.enter_context(
                    mp.tasks.vision.HandLandmarker.create_from_options(
                        mp.tasks.vision.HandLandmarkerOptions(
                            base_options=mp.tasks.BaseOptions(
                                model_asset_path=str(hand_model),
                                delegate=mp.tasks.BaseOptions.Delegate.CPU,
                            ),
                            running_mode=mp.tasks.vision.RunningMode.VIDEO,
                            num_hands=2,
                            min_hand_detection_confidence=0.7,
                            min_hand_presence_confidence=0.7,
                            min_tracking_confidence=0.7,
                        )
                    )
                )
                crop_tracker = stack.enter_context(
                    mp.tasks.vision.HandLandmarker.create_from_options(
                        mp.tasks.vision.HandLandmarkerOptions(
                            base_options=mp.tasks.BaseOptions(
                                model_asset_path=str(hand_model),
                                delegate=mp.tasks.BaseOptions.Delegate.CPU,
                            ),
                            running_mode=mp.tasks.vision.RunningMode.IMAGE,
                            num_hands=2,
                            min_hand_detection_confidence=0.7,
                            min_hand_presence_confidence=0.7,
                        )
                    )
                )
            frame_index = 0
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                # Decoder timestamps may be unset; frame_index/fps remains reproducible.
                clock_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC))
                if not np.isfinite(clock_ms) or clock_ms <= previous_clock_ms:
                    clock_ms = frame_index * 1000.0 / fps
                if clock_ms <= previous_clock_ms:
                    raise ValidationError(
                        "Video decoder timestamps are not strictly increasing."
                    )
                previous_clock_ms = clock_ms
                timestamp_ms = max(previous_ms + 1, int(round(clock_ms)))
                previous_ms = timestamp_ms
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect_for_video(image, timestamp_ms)
                # MediaPipe needs integer milliseconds; the analysis clock retains
                # the decoder's precision rather than inheriting that rounding.
                row = {"time_s": clock_ms / 1000.0}
                landmarks = (
                    result.pose_landmarks[0]
                    if len(result.pose_landmarks) == 1
                    else None
                )
                full_pose = np.full((33, 3), np.nan)
                if landmarks is not None:
                    for j, point in enumerate(landmarks):
                        full_pose[j] = (
                            point.x,
                            point.y,
                            min(point.visibility, point.presence),
                        )
                hands = np.full((2, 21, 2), np.nan)
                if hand_tracker is not None:
                    detected = hand_tracker.detect_for_video(image, timestamp_ms)
                    candidates = [
                        np.array([[p.x, p.y] for p in hand])
                        for hand in detected.hand_landmarks
                    ]
                    # Anatomical identity comes from pose wrists, not mirrored-image handedness labels.
                    if (
                        candidates
                        and np.isfinite(full_pose[[11, 12, 15, 16]]).all()
                        and np.all(full_pose[[11, 12, 15, 16], 2] >= 0.7)
                    ):
                        sw = np.linalg.norm(
                            (full_pose[11, :2] - full_pose[12, :2]) * [width, height]
                        )
                        wrists = full_pose[[15, 16], :2] * [width, height]
                        distances = np.array(
                            [
                                np.linalg.norm(
                                    wrists - hand[0] * [width, height], axis=1
                                )
                                / max(sw, 1)
                                for hand in candidates
                            ]
                        )
                        for side in range(2):
                            eligible = [
                                k
                                for k, hand in enumerate(candidates)
                                if distances[k, side] < 0.35
                                and distances[k, 1 - side] - distances[k, side] > 0.10
                                and np.isfinite(hand).all()
                                and np.all((hand >= 0) & (hand <= 1))
                            ]
                            if len(eligible) == 1:
                                hands[side] = candidates[eligible[0]]
                    # Fixed-size pose-guided crops help when hands occupy few pixels
                    # in a full-body frame. Same policy for both sides and recordings.
                    if np.isfinite(full_pose[[11, 12, 15, 16]]).all() and np.all(
                        full_pose[[11, 12, 15, 16], 2] >= 0.7
                    ):
                        sw = np.linalg.norm(
                            (full_pose[11, :2] - full_pose[12, :2]) * [width, height]
                        )
                        wrists = full_pose[[15, 16], :2] * [width, height]
                        for side in range(2):
                            if np.isfinite(hands[side]).all():
                                continue
                            x, y = wrists[side]
                            radius = max(32, int(0.6 * sw))
                            x0, y0 = max(0, int(x) - radius), max(0, int(y) - radius)
                            x1, y1 = (
                                min(width, int(x) + radius),
                                min(height, int(y) + radius),
                            )
                            if x1 - x0 < 32 or y1 - y0 < 32:
                                continue
                            crop = mp.Image(
                                image_format=mp.ImageFormat.SRGB,
                                data=np.ascontiguousarray(rgb[y0:y1, x0:x1]),
                            )
                            cropped = crop_tracker.detect(crop)
                            accepted = []
                            for hand in cropped.hand_landmarks:
                                pts = np.array(
                                    [
                                        [p.x * (x1 - x0) + x0, p.y * (y1 - y0) + y0]
                                        for p in hand
                                    ]
                                )
                                distances = np.linalg.norm(
                                    wrists - pts[0], axis=1
                                ) / max(sw, 1)
                                normalized = pts / [width, height]
                                if (
                                    distances[side] < 0.35
                                    and distances[1 - side] - distances[side] > 0.10
                                    and np.isfinite(normalized).all()
                                    and np.all((normalized >= 0) & (normalized <= 1))
                                ):
                                    accepted.append(normalized)
                            if len(accepted) == 1:
                                hands[side] = accepted[0]
                upper_pose.append(full_pose)
                upper_hands.append(hands)
                for name, pose_index in zip(joints, indices):
                    if landmarks is None:
                        row.update(
                            {f"{name}_{axis}": "" for axis in ("x", "y", "confidence")}
                        )
                        continue
                    point = landmarks[pose_index]
                    visibility = getattr(point, "visibility", None)
                    presence = getattr(point, "presence", None)
                    score = min(
                        float(1.0 if visibility is None else visibility),
                        float(1.0 if presence is None else presence),
                    )
                    if not np.isfinite([point.x, point.y, score]).all() or not (
                        0 <= point.x <= 1 and 0 <= point.y <= 1
                    ):
                        row.update(
                            {f"{name}_{axis}": "" for axis in ("x", "y", "confidence")}
                        )
                    else:
                        row.update(
                            {
                                f"{name}_x": point.x,
                                f"{name}_y": point.y,
                                f"{name}_confidence": max(0.0, min(1.0, score)),
                            }
                        )
                rows.append(row)
                frame_index += 1
    finally:
        capture.release()
    if len(rows) < 2:
        raise ValidationError(f"{video.name}: no usable frames were decoded.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "video": video.name,
        "landmarks": output.name,
        "frames": len(rows),
        "frame_rate": fps,
        "width": width,
        "height": height,
        "pose_model": model.name,
        "pose_model_sha256": sha256(model),
        "video_sha256": sha256(video),
        "landmarks_sha256": sha256(output),
        "timestamp_policy": "unrounded decoder seconds; frame_index/fps fallback; integer milliseconds for inference only",
        "mediapipe_version": mp.__version__,
        "opencv_version": cv2.__version__,
        "joint_names": list(joints),
        "tracking_review": "unreviewed",
    }
    if include_elbows:
        upper_path = output.with_suffix(".upper.npz")
        np.savez_compressed(
            upper_path,
            times=np.array([r["time_s"] for r in rows]),
            pose=np.array(upper_pose),
            hands=np.array(upper_hands),
        )
        metadata["upper_body"] = {
            "file": upper_path.name,
            "sha256": sha256(upper_path),
            "hand_model_sha256": sha256(Path(hand_model))
            if hand_model is not None and Path(hand_model).is_file()
            else None,
            "hand_model_available": hand_tracker is not None,
            "hand_identity": "unique pose-wrist association within 0.35 shoulder widths; opposite wrist at least 0.10 widths farther away",
            "hand_quality": "detection/presence/IoU thresholds 0.70; no per-landmark confidence supplied; tracking remains provisional",
            "hand_crop_policy": "full-frame video detection, then missing-hand fallback to image detection on pose-wrist crop, radius 0.60 shoulder widths; unchanged thresholds and identity check",
            "hand_observed_frame_fraction": np.isfinite(np.array(upper_hands))
            .all(axis=(2, 3))
            .mean(axis=0)
            .tolist(),
        }
    if include_elbows:
        output.with_suffix(".metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n"
        )
    return metadata
