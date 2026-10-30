"""Private analysis worker: validate clocks, extract landmarks, build a case report."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from app.core.config import settings
from app.services.analysis_service import write_status
from app.validation.case_study import run_case_study
from app.validation.fbx_motion import load_motion
from app.validation.mixed_effects import ValidationError
from app.validation.trials import sha256
from app.validation.video_pose import extract_video_pose, read_pose_csv

REPO_ROOT = Path(__file__).resolve().parents[3]


def single_take_summary(report: dict, action_name: str) -> dict:
    """summary.json for the two-view single-take equivalence protocol."""
    from app.validation.equivalence_single_take import EQUIVALENT, NOT_EQUIVALENT, PARTIALLY_EQUIVALENT
    from app.validation.single_take_job import FIGURE, REPORT

    verdict = report["decision"]
    claim = {
        "rms": "root-mean-square joint-angle difference over the sign",
        "mean": "sign-average joint-angle difference",
        "whole_curve": "joint-angle difference at every phase of the sign",
    }[report["primary_claim"]]
    margin = max(item["margin_deg"] for item in report["angles"].values())
    sequence = report.get("sequence") or {}

    def label(names):
        return ", ".join(name.replace("_", " ") for name in names)

    partial = (
        f"EQUIVALENCE ESTABLISHED for {len(sequence.get('confirmed', []))} of {len(report['angles'])} angles "
        f"({label(sequence.get('confirmed', []))}); testing stopped at {label(sequence.get('stopped_at') or [])}."
    )
    message, status = {
        EQUIVALENT: ("STATISTICAL EQUIVALENCE ESTABLISHED for this take.", "success"),
        PARTIALLY_EQUIVALENT: (partial, "partial"),
        NOT_EQUIVALENT: ("NOT EQUIVALENT: the FBX and the two-view video disagree beyond the margin.", "tolerance_exceeded"),
    }.get(verdict, ("INCONCLUSIVE: this take can establish neither equivalence nor a difference.", "inconclusive"))
    keep = (
        "decision", "margin_deg", "mean_difference_deg", "mean_ci_deg", "mean_decision", "rms_deg",
        "rms_ci_deg", "rms_decision", "curve_decision", "max_band_abs_deg", "measurement_sd_deg",
        "replicate_check", "pearson_r", "max_abs_deg", "fraction_outside_margin",
        "static_offset_deg", "static_offset_ci_deg", "raw_rms_deg", "raw_mean_difference_deg",
        "tested_in_sequence",
    )
    return {
        "performance_id": action_name,
        "comparison_kind": "single_take_equivalence",
        "assessment_kind": "single_take_equivalence",
        "status": status,
        "equivalence_verdict": verdict,
        "message": message,
        "message_detail": (
            f"Primary claim: the {claim} is within ±{margin:g}° (two one-sided tests, α = 0.05), "
            "after propagating the video's measured detector noise and calibration uncertainty, "
            "and confirmed across pose-model replicates. Angles are tested in a pre-registered order "
            "and testing stops at the first angle that does not pass, which keeps the chance of any "
            "false equivalence at 5% without splitting it across angles. " + report["scope"]
        ),
        "single_take": {
            "decision": verdict,
            "primary_claim": report["primary_claim"],
            "scope": report["scope"],
            "sequence": sequence,
            "angles": {name: {key: item[key] for key in keep if key in item} for name, item in report["angles"].items()},
            "noise_model": report["noise_model"],
            "diagnostics": report["diagnostics"],
        },
        "artifacts": {"single_take_plot": FIGURE, "single_take_report": REPORT, "figures": [FIGURE]},
    }


def process_single_take(directory: Path, options: dict, paths: dict, action_name: str) -> None:
    from app.validation.single_take_job import run_single_take

    if "oblique_video" not in paths:
        raise ValidationError("Statistical equivalence needs a second video of the same performance, 70-90 degrees to the side (at least 30).")
    results_dir = directory / "results"
    if results_dir.exists():
        import shutil
        shutil.rmtree(results_dir)
    write_status(directory, "extracting")

    def progress(message: str) -> None:
        print(message, flush=True)
        if message.startswith("Calibrating"):
            write_status(directory, "scoring")

    report = run_single_take(
        paths["reference_video"], paths["oblique_video"], paths["suit_fbx"], results_dir,
        noise_front=paths.get("noise_front_video"), noise_oblique=paths.get("noise_oblique_video"),
        focal_35mm=options.get("focal_35mm"), progress=progress,
    )
    (results_dir / "summary.json").write_text(json.dumps(single_take_summary(report, action_name), indent=2))
    write_status(directory, "done")


def compute_hand_speed(times, points):
    import scipy.signal
    dt = np.diff(times)
    wrists = points[:, 4:6, :2]
    dp = np.diff(wrists, axis=0)
    speed = np.linalg.norm(dp, axis=2).mean(axis=1)
    valid = dt > 0
    dt_safe = np.where(valid, dt, 1.0)
    velocities = np.zeros_like(speed)
    velocities[valid] = speed[valid] / dt_safe[valid]
    v_times = times[:-1] + dt / 2
    if len(velocities) > 5:
        velocities = scipy.signal.savgol_filter(velocities, window_length=5, polyorder=2)
    return v_times, np.clip(velocities, 0, None)


def auto_detect_action_windows(extracted_pose, suit_fbx_path: Path, video_dur: float, suit_dur: float):
    import scipy.signal
    motion = load_motion(suit_fbx_path, include_elbows=True)
    v_times_vid, v_speed_vid = compute_hand_speed(extracted_pose.times, extracted_pose.xy)
    v_times_fbx, v_speed_fbx = compute_hand_speed(motion.times, motion.joints)

    if len(v_speed_fbx) > 5 and v_speed_fbx[0] > np.median(v_speed_fbx) * 4:
        v_speed_fbx[:5] = np.median(v_speed_fbx[:10])

    fps = 60.0
    common_dt = 1.0 / fps
    max_t = max(v_times_vid[-1], v_times_fbx[-1])
    t_grid = np.arange(0, max_t, common_dt)

    sig_vid = np.interp(t_grid, v_times_vid, v_speed_vid / (np.max(v_speed_vid) + 1e-6), left=0, right=0)
    sig_fbx = np.interp(t_grid, v_times_fbx, v_speed_fbx / (np.max(v_speed_fbx) + 1e-6), left=0, right=0)

    corr = scipy.signal.correlate(sig_vid, sig_fbx, mode="full")
    lags = scipy.signal.correlation_lags(len(sig_vid), len(sig_fbx), mode="full")
    best_offset = float(lags[np.argmax(corr)] * common_dt)

    th_vid = 0.12 * np.max(v_speed_vid)
    active_idx = np.where(v_speed_vid > th_vid)[0]
    if len(active_idx) < 5:
        return None

    vid_start = max(0.0, float(v_times_vid[active_idx[0]] - 0.20))
    vid_end = min(float(video_dur), float(extracted_pose.times[-1]), float(v_times_vid[active_idx[-1]] + 0.20))
    fbx_start = max(0.0, float(vid_start - best_offset))
    fbx_end = min(float(suit_dur), float(motion.times[-1]), float(vid_end - best_offset))

    if 0 <= vid_start < vid_end and 0 <= fbx_start < fbx_end:
        return {
            "video": [round(vid_start, 3), round(vid_end, 3)],
            "suit": [round(fbx_start, 3), round(fbx_end, 3)],
        }
    return None


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
    action_name = (options.get("action") or "").strip()
    original_video = options.get("original_names", {}).get("reference_video", "")
    if (not action_name or action_name.lower() in ("action comparison", "after")) and original_video:
        derived = Path(original_video).stem.replace("_", " ").replace("-", " ").strip()
        if derived and derived.lower() not in ("reference", "video"):
            action_name = derived.capitalize()
    if not action_name:
        action_name = "Action comparison"
    options["action"] = action_name

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
    if options.get("tolerance_profile") == "statistical_equivalence":
        process_single_take(directory, options, paths, action_name)
        return
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
    if (
        not options.get("windows", {}).get("video")
        and not options.get("windows", {}).get("suit")
        and "suit_fbx" in paths
    ):
        try:
            auto_win = auto_detect_action_windows(
                extracted, paths["suit_fbx"], durations["video"], durations["suit"]
            )
            if auto_win:
                windows["video"] = auto_win["video"]
                windows["suit"] = auto_win["suit"]
        except Exception as exc:
            print(f"Auto-sync note: {exc}")
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
    
    # 1. Run the case study pipeline: extracts video landmarks via DWPose, FBX landmarks via ufbx,
    # aligns camera projections, and dynamically generates the sign-specific trajectories and elbow-angle plots.
    results_dir = directory / "results"
    if results_dir.exists():
        import shutil
        shutil.rmtree(results_dir)

    run_case_study(manifest_path, results_dir)

    results_dir.mkdir(exist_ok=True)
    summary_file = results_dir / "summary.json"

    summary_payload = {}
    if summary_file.is_file():
        try:
            summary_payload = json.loads(summary_file.read_text())
        except Exception:
            summary_payload = {}

    artifacts = summary_payload.setdefault("artifacts", {})

    # Register trajectories and angles plots directly from the case study output
    for traj_name in (
        "phase_normalized_trajectories.png",
        "synchronized_trajectories.png",
        "phase_normalized_trajectories.svg",
        "synchronized_trajectories.svg",
    ):
        if (results_dir / traj_name).is_file():
            artifacts["trajectories_plot"] = traj_name
            break

    for angles_name in (
        "phase_normalized_angles.png",
        "synchronized_angles.png",
        "phase_normalized_angles.svg",
        "synchronized_angles.svg",
    ):
        if (results_dir / angles_name).is_file():
            artifacts["angles_plot"] = angles_name
            break

    figures = artifacts.get("figures", [])
    for key in ("trajectories_plot", "angles_plot"):
        val = artifacts.get(key)
        if val and val not in figures:
            figures.append(val)
    artifacts["figures"] = figures

    if summary_file.is_file() or summary_payload:
        summary_file.write_text(json.dumps(summary_payload, indent=2))

    write_status(directory, "done")


if __name__ == "__main__":
    directory = Path(sys.argv[1]).resolve()
    try:
        process(directory)
    except (ValidationError, OSError, ValueError, ImportError) as exc:
        write_status(directory, "failed", error=str(exc))
        sys.exit(2)
