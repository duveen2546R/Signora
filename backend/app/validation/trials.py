"""Auditable, explicitly matched motion-validation trials."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from .mixed_effects import ValidationError


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Trial:
    performance_id: str
    action_id: str
    performer_id: str
    repetition: str
    suit_fbx: Path
    non_suit_fbx: Path | None
    reference_video: Path
    video_landmarks: Path | None
    hashes: dict[str, str]
    windows: dict[str, tuple[float, float]]
    calibration_phase: tuple[float, float]
    pairing_verified_by: str


def _path(base: Path, value: object, label: str, suffix: str | tuple[str, ...]) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} must be a file path.")
    path = (base / value).resolve()
    allowed = (suffix,) if isinstance(suffix, str) else suffix
    if path.suffix.lower() not in allowed or not path.is_file():
        raise ValidationError(
            f"{label} must point to an existing {suffix} file: {path}"
        )
    return path


def _interval(value: object, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValidationError(f"{label} must be [start_seconds, end_seconds].")
    try:
        start, end = map(float, value)
    except (ValueError, TypeError) as exc:
        raise ValidationError(f"{label} contains an invalid time.") from exc
    if not all(map(math.isfinite, (start, end))) or start < 0 or end <= start:
        raise ValidationError(f"{label} must have finite times with 0 <= start < end.")
    return start, end


def load_manifest(
    path: str | Path,
    *,
    require_landmarks: bool = False,
    allow_unpaired_case: bool = False,
) -> list[Trial]:
    """Read a study manifest; file hashes and human pairing attestation are mandatory."""
    path = Path(path).resolve()
    try:
        source = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValidationError(f"Could not read trial manifest: {exc}") from exc
    if not isinstance(source, dict) or source.get("schema_version") != 1:
        raise ValidationError("Trial manifest needs schema_version: 1.")
    entries = source.get("trials")
    if not isinstance(entries, list) or not entries:
        raise ValidationError("Trial manifest needs a nonempty trials array.")

    trials: list[Trial] = []
    ids: set[str] = set()
    videos: set[Path] = set()
    motion_files: set[Path] = set()
    source_digests: set[str] = set()
    video_digests: set[str] = set()
    triplets: set[tuple[str, str, str]] = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise ValidationError(f"Trial {index + 1} must be an object.")
        relationship = item.get("recording_relationship", "same_performance")
        if not isinstance(relationship, str) or relationship not in {
            "same_performance",
            "separate_repetitions",
            "unknown",
        }:
            raise ValidationError("Invalid recording relationship.")
        if relationship != "same_performance" and not allow_unpaired_case:
            raise ValidationError(
                "Separate or unverified performances cannot enter matched accuracy scoring or LMEM. Use case-study for descriptive movement similarity."
            )
        labels = (
            "performance_id",
            "action_id",
            "performer_id",
            "repetition",
            "pairing_verified_by",
        )
        for label in labels:
            if not isinstance(item.get(label), str) or not item[label].strip():
                raise ValidationError(f"Trial {index + 1}: {label} is required.")
        if item.get("reference_independent") is not True:
            raise ValidationError(
                f"Trial {index + 1}: independent reference video must be attested."
            )
        performance = item["performance_id"].strip()
        triplet = tuple(
            item[key].strip() for key in ("action_id", "performer_id", "repetition")
        )
        if performance in ids or triplet in triplets:
            raise ValidationError(
                f"Duplicate performance or action/performer/repetition: {performance}"
            )
        ids.add(performance)
        triplets.add(triplet)

        files = {
            "suit_fbx": _path(path.parent, item.get("suit_fbx"), "suit_fbx", ".fbx"),
            "reference_video": _path(
                path.parent,
                item.get("reference_video"),
                "reference_video",
                (".mp4", ".mov", ".m4v"),
            ),
        }
        if "non_suit_fbx" in item:
            files["non_suit_fbx"] = _path(path.parent, item["non_suit_fbx"], "non_suit_fbx", ".fbx")

        if "non_suit_fbx" in files and files["suit_fbx"] == files["non_suit_fbx"]:
            raise ValidationError(
                f"{performance}: suit and non-suit files are identical paths."
            )
        for fbx_key in ("suit_fbx", "non_suit_fbx"):
            if fbx_key in files:
                if files[fbx_key] in motion_files:
                    raise ValidationError(
                        f"{performance}: an FBX is reused across independent performances."
                    )
                motion_files.add(files[fbx_key])

        if files["reference_video"] in videos:
            raise ValidationError(
                f"{performance}: reference video is assigned to another performance."
            )
        videos.add(files["reference_video"])
        hashes = item.get("sha256", {})
        for label, file in files.items():
            expected = hashes.get(label)
            if expected is not None:
                if not isinstance(expected, str) or len(expected) != 64 or expected.lower() != sha256(file):
                    raise ValidationError(
                        f"{performance}: {label} SHA-256 is missing or does not match."
                    )
        current_motion = {hashes.get("suit_fbx", "a").lower()}
        if "non_suit_fbx" in hashes:
            current_motion.add(hashes["non_suit_fbx"].lower())
            if hashes.get("suit_fbx", "a").lower() == hashes["non_suit_fbx"].lower():
                raise ValidationError(f"{performance}: FBX contents are duplicated within this trial.")
        if current_motion & source_digests:
            raise ValidationError(
                f"{performance}: FBX contents are duplicated within or across trials."
            )
        source_digests.update(current_motion)
        if hashes.get("reference_video", "").lower() in video_digests:
            raise ValidationError(
                f"{performance}: reference video contents are reused across trials."
            )
        video_digests.add(hashes.get("reference_video", "").lower())
        landmarks = item.get("video_landmarks")
        pose_path = (
            _path(path.parent, landmarks, "video_landmarks", ".csv")
            if landmarks
            else None
        )
        if require_landmarks and pose_path is None:
            raise ValidationError(
                f"{performance}: extract and review video_landmarks before scoring."
            )
        if pose_path is not None:
            expected = hashes.get("video_landmarks")
            if expected is not None:
                if not isinstance(expected, str) or expected.lower() != sha256(pose_path):
                    raise ValidationError(
                        f"{performance}: video_landmarks SHA-256 is missing or does not match."
                    )

        windows = item.get("windows")
        if not isinstance(windows, dict):
            raise ValidationError(
                f"{performance}: windows are required for all three sources."
            )
        bounds = {}
        for key in ("suit", "non_suit", "video"):
            if key == "non_suit" and "non_suit_fbx" not in files:
                continue
            bounds[key] = _interval(windows.get(key), f"{performance}: windows.{key}")

        calibration = _interval(
            item.get("calibration_phase"), f"{performance}: calibration_phase"
        )
        if calibration[1] > 1:
            raise ValidationError(
                f"{performance}: calibration phase must be within [0, 1]."
            )
        trials.append(
            Trial(
                performance,
                triplet[0],
                triplet[1],
                triplet[2],
                files["suit_fbx"],
                files.get("non_suit_fbx"),
                files["reference_video"],
                pose_path,
                {key: value.lower() for key, value in hashes.items()},
                bounds,
                calibration,
                item["pairing_verified_by"].strip(),
            )
        )
    return trials
