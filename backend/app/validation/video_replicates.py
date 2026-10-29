"""Whole-body keypoints in pixels with test-time-augmented replicates, for the two-view protocol.

The person detector runs once per frame. RTMW then runs on the original crop and on augmented
crops (mirrored image, rescaled and shifted boxes); each augmentation yields one replicate track.
Their spread measures how much the detector's answer depends on incidental input changes while
the signer moves. That is a lower bound on detector noise, which is how the protocol uses it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from .fbx_motion import CASE_JOINTS
from .mixed_effects import ValidationError
from .multiview import View
from .trials import sha256

# COCO-WholeBody indices; the left index MCP is 91 + 5 and the right 112 + 5.
WHOLEBODY = {
    "left_shoulder": 5, "right_shoulder": 6, "left_elbow": 7, "right_elbow": 8,
    "left_wrist": 9, "right_wrist": 10, "left_hip": 11, "right_hip": 12,
    "left_index": 96, "right_index": 117,
}
MIRROR = {name: name.replace("left", "@").replace("right", "left").replace("@", "right") for name in WHOLEBODY}
# (mirror, box scale, horizontal shift as a fraction of box width). The first entry is the
# primary measurement; the rest are replicates.
AUGMENTATIONS = (
    (False, 1.00, 0.00),
    (True, 1.00, 0.00),
    (False, 0.92, 0.00),
    (False, 1.08, 0.00),
    (False, 1.00, -0.04),
    (False, 1.00, 0.04),
)
CACHE_VERSION = 1


def _box(box: np.ndarray, scale: float, shift: float, width: int, height: int) -> np.ndarray:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2 + shift * (x1 - x0), (y0 + y1) / 2
    hw, hh = scale * (x1 - x0) / 2, scale * (y1 - y0) / 2
    return np.array([max(0, cx - hw), max(0, cy - hh), min(width, cx + hw), min(height, cy + hh)])


def _estimator():
    try:
        from rtmlib import Wholebody
    except ImportError as exc:
        raise ValidationError(
            "Video extraction requires rtmlib and onnxruntime (requirements-validation-video.txt)."
        ) from exc
    try:
        return Wholebody(mode="performance", to_openpose=False, backend="onnxruntime", device="cpu")
    except Exception as exc:  # model download or ONNX failure
        raise ValidationError(f"RTMW models could not load: {exc}") from exc


def extract_replicated_views(
    video: str | Path,
    *,
    replicates: int = len(AUGMENTATIONS) - 1,
    cache_dir: str | Path | None = None,
    progress=None,
) -> tuple[View, tuple[View, ...], dict]:
    """Primary View, replicate Views and video metadata, all in pixels on the decoder clock."""
    import cv2

    video = Path(video)
    if not video.is_file():
        raise ValidationError(f"{video} does not exist.")
    augmentations = AUGMENTATIONS[: replicates + 1]
    digest = sha256(video)
    key = hashlib.sha256(json.dumps([CACHE_VERSION, digest, augmentations]).encode()).hexdigest()[:16]
    cache = Path(cache_dir) / f"{video.stem}.{key}.npz" if cache_dir else None
    if cache and cache.is_file():
        data = np.load(cache, allow_pickle=False)
        return _views(data["times"], data["uv"], data["confidence"], tuple(data["size"]), json.loads(str(data["meta"])))

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValidationError(f"Could not decode {video.name}.")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if not np.isfinite(fps) or fps <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise ValidationError(f"{video.name}: invalid frame rate or size.")
    model = _estimator()
    names = CASE_JOINTS
    times, uv, confidence = [], [], []
    previous = -1.0
    try:
        frame_index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            clock = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
            if not np.isfinite(clock) or clock <= previous:
                clock = frame_index / fps
            previous = clock
            times.append(clock)
            points = np.full((len(augmentations), len(names), 2), np.nan)
            scores = np.zeros((len(augmentations), len(names)))
            boxes = np.asarray(model.det_model(frame), dtype=float).reshape(-1, 4)
            if len(boxes):
                # The signer is the largest detected person.
                box = boxes[np.argmax((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]))]
                mirrored = frame[:, ::-1]
                for a, (mirror, scale, shift) in enumerate(augmentations):
                    if mirror:
                        flipped = np.array([width - box[2], box[1], width - box[0], box[3]])
                        kp, sc = model.pose_model(np.ascontiguousarray(mirrored), bboxes=[_box(flipped, scale, shift, width, height)])
                        kp = kp[0].copy()
                        kp[:, 0] = width - kp[:, 0]
                        lookup = {name: WHOLEBODY[MIRROR[name]] for name in names}
                    else:
                        kp, sc = model.pose_model(frame, bboxes=[_box(box, scale, shift, width, height)])
                        kp = kp[0]
                        lookup = WHOLEBODY
                    for j, name in enumerate(names):
                        x, y = kp[lookup[name]]
                        if np.isfinite([x, y]).all() and 0 <= x <= width and 0 <= y <= height:
                            points[a, j] = (x, y)
                            scores[a, j] = float(np.clip(sc[0][lookup[name]], 0, 1))
            uv.append(points)
            confidence.append(scores)
            frame_index += 1
            if progress and frame_index % 10 == 0:
                progress(frame_index, total)
    finally:
        capture.release()
    if len(times) < 10:
        raise ValidationError(f"{video.name}: fewer than ten frames decoded.")
    times = np.array(times)
    uv = np.stack(uv, axis=1)  # augmentations x frames x joints x 2
    confidence = np.stack(confidence, axis=1)
    meta = {
        "video": video.name, "video_sha256": digest, "frame_rate": fps, "frames": int(len(times)),
        "width": width, "height": height, "pose_model": "rtmlib RTMW (performance)",
        "augmentations": [list(a) for a in augmentations], "joint_names": list(names),
    }
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, times=times, uv=uv, confidence=confidence, size=np.array([width, height]), meta=json.dumps(meta))
    return _views(times, uv, confidence, (width, height), meta)


def _views(times, uv, confidence, size, meta):
    # Detector score is not on the 0-1 confidence scale the triangulation gates use; RTMW
    # SimCC scores for visible joints sit around 0.3-1.0, so rescale by a robust maximum.
    scale = max(float(np.nanpercentile(confidence[0][confidence[0] > 0], 95)) if (confidence[0] > 0).any() else 1.0, 1e-6)
    normalised = np.clip(confidence / scale, 0, 1)
    views = [View(times, uv[a], normalised[a], tuple(int(v) for v in size)) for a in range(len(uv))]
    return views[0], tuple(views[1:]), meta
