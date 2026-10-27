"""Single-camera video landmarks with explicit visibility and editable CSV output."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .fbx_motion import JOINTS, CASE_JOINTS
from .trials import sha256
from .mixed_effects import ValidationError


# Public six-joint CSV schema retained for validation-pipeline callers.
COLUMNS = (
    "time_s",
    *(f"{joint}_{field}" for joint in JOINTS for field in ("x", "y", "confidence")),
)


@dataclass(frozen=True)
class VideoPose:
    times: np.ndarray
    xy: np.ndarray  # frames x joints x image-normalized xy
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
    model: str | Path,  # Keeping signature, though DWPose pulls its own weights
    output: str | Path,
    *,
    include_elbows: bool = False,
    hand_model: str | Path | None = None,
) -> dict:
    """Run DWPose (via rtmlib) to extract highly robust 2D landmarks."""
    try:
        import cv2
        from rtmlib import Wholebody
    except ImportError as exc:
        raise ValidationError(
            "Video extraction requires OpenCV and rtmlib; "
            "install onnxruntime and rtmlib."
        ) from exc
    video, output = Path(video), Path(output)
    if not video.is_file():
        raise ValidationError("Reference video must exist.")

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValidationError(f"Could not decode {video}.")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if not np.isfinite(fps) or fps <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise ValidationError(f"{video.name}: invalid video frame rate.")

    joints = CASE_JOINTS if include_elbows else JOINTS

    # Mapping our joints to COCO-WholeBody (133 points)
    # 5: l_sh, 6: r_sh, 7: l_el, 8: r_el, 9: l_wr, 10: r_wr, 11: l_hip, 12: r_hip
    # 96: l_index (MCP), 117: r_index (MCP)
    mapping = {
        "left_shoulder": 5,
        "right_shoulder": 6,
        "left_hip": 11,
        "right_hip": 12,
        "left_wrist": 9,
        "right_wrist": 10,
        "left_elbow": 7,
        "right_elbow": 8,
        "left_index": 96,
        "right_index": 117
    }

    # We map requested joints to their DWPose indices
    indices = [mapping[j] for j in joints]

    columns = (
        "time_s",
        *(f"{joint}_{field}" for joint in joints for field in ("x", "y", "confidence")),
    )

    print(f"Initializing DWPose via rtmlib for {video.name}...")
    try:
        wholebody = Wholebody(
            mode='performance',  # RTMW / DWPose whole-body model
            to_openpose=False,  # COCO-WholeBody 133 format
            backend='onnxruntime',
            device='cpu'
        )
    except Exception as exc:
        capture.release()
        raise ValidationError(f'DWPose ONNX models could not load: {exc}') from exc

    rows = []
    upper_pose = []
    upper_hands = []

    previous_clock_ms = -1.0
    frame_index = 0

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break

            clock_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC))
            if not np.isfinite(clock_ms) or clock_ms <= previous_clock_ms:
                clock_ms = frame_index * 1000.0 / fps
            if clock_ms <= previous_clock_ms:
                raise ValidationError("Video decoder timestamps are not strictly increasing.")
            previous_clock_ms = clock_ms

            # Infer
            keypoints, scores = wholebody(frame)

            row = {"time_s": clock_ms / 1000.0}

            # Find the largest person bounding box if multiple people are detected
            best_person_idx = 0
            if len(keypoints) > 1:
                # Heuristic: person with highest average score across body joints
                body_scores = [np.mean(s[:17]) for s in scores]
                best_person_idx = np.argmax(body_scores)

            person_kpts = keypoints[best_person_idx] if len(keypoints) > 0 else None
            person_scores = scores[best_person_idx] if len(scores) > 0 else None

            # Populate requested CSV joints
            for name, pose_index in zip(joints, indices):
                if person_kpts is None:
                    row.update({f"{name}_{axis}": "" for axis in ("x", "y", "confidence")})
                    continue

                x, y = person_kpts[pose_index]
                score = person_scores[pose_index]

                # Normalize to 0-1
                x_norm, y_norm = x / width, y / height

                if not np.isfinite([x_norm, y_norm, score]).all() or not (0 <= x_norm <= 1 and 0 <= y_norm <= 1):
                    row.update({f"{name}_{axis}": "" for axis in ("x", "y", "confidence")})
                else:
                    row.update({
                        f"{name}_x": float(x_norm),
                        f"{name}_y": float(y_norm),
                        f"{name}_confidence": float(max(0.0, min(1.0, score))),
                    })

            rows.append(row)

            # Optionally populate upper_hands data
            if include_elbows:
                # upper_pose historically had 33 mediapipe points. We only really need it to be
                # shape (33, 3) for compatibility in the rest of the code, but the rest of the code
                # in case_study.py does NOT use `upper_pose`. It only uses `upper_hands` which is (2, 21, 2).
                # We'll save empty `upper_pose` just to satisfy the npz format expectations.
                full_pose = np.zeros((33, 3), dtype=np.float32)

                hands = np.full((2, 21, 2), np.nan)
                if person_kpts is not None:
                    # Left hand: 91:112
                    lh = person_kpts[91:112] / [width, height]
                    lh_scores = person_scores[91:112]
                    # Gate each point; a high hand average must not hide a bad finger.
                    accepted = (lh_scores >= 0.70) & np.isfinite(lh).all(axis=1) & ((lh >= 0) & (lh <= 1)).all(axis=1)
                    hands[0, accepted] = lh[accepted]

                    # Right hand: 112:133
                    rh = person_kpts[112:133] / [width, height]
                    rh_scores = person_scores[112:133]
                    accepted = (rh_scores >= 0.70) & np.isfinite(rh).all(axis=1) & ((rh >= 0) & (rh <= 1)).all(axis=1)
                    hands[1, accepted] = rh[accepted]

                upper_pose.append(full_pose)
                upper_hands.append(hands)

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
        "pose_model": "rtmlib_dwpose_wholebody",
        "video_sha256": sha256(video),
        "landmarks_sha256": sha256(output),
        "timestamp_policy": "unrounded decoder seconds",
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
            "hand_model_available": True,
            "hand_quality": "DWPose per-point score >= 0.70; scores are not calibrated uncertainty",
            "hand_observed_frame_fraction": np.isfinite(np.array(upper_hands))
            .all(axis=(2, 3))
            .mean(axis=0)
            .tolist(),
        }

    output.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n"
    )

    return metadata
