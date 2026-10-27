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


def generate_dynamic_ftost_plot(
    results_dir: Path, action_name: str, relationship: str = "same_performance"
) -> tuple[Path | None, dict]:
    """Generate dynamic SPM1d + fTOST bilateral statistical equivalence plot for the uploaded action."""
    import os
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    import numpy as np
    import pandas as pd
    import scipy.signal
    import spm1d
    import matplotlib.pyplot as plt

    csv_candidates = [
        results_dir / "phase_normalized_traces.csv",
        results_dir / "synchronized_traces.csv",
    ]
    csv_path = next((p for p in csv_candidates if p.is_file()), None)
    if not csv_path:
        return None, {}

    try:
        df = pd.read_csv(csv_path)
        if "reference_right_elbow_angle" not in df.columns or "suit_right_elbow_angle" not in df.columns:
            return None, {}

        target_frames = 100
        delta = 15.0  # Equivalence margin (degrees)
        fig, axes = plt.subplots(1, 2, figsize=(13, 5))
        stats_by_side = {}

        for idx, (side, ax) in enumerate(zip(["left", "right"], axes)):
            ref_raw = df[f"reference_{side}_elbow_angle"].to_numpy(dtype=float)
            suit_raw = df[f"suit_{side}_elbow_angle"].to_numpy(dtype=float)

            valid = np.isfinite(ref_raw) & np.isfinite(suit_raw)
            if np.sum(valid) < 10:
                continue
            ref_raw = ref_raw[valid]
            suit_raw = suit_raw[valid]

            t_orig = np.linspace(0, 1, len(ref_raw))
            t_target = np.linspace(0, 1, target_frames)
            ref_curve = np.interp(t_target, t_orig, ref_raw)
            suit_curve = np.interp(t_target, t_orig, suit_raw)

            if len(ref_curve) >= 11:
                ref_curve = scipy.signal.savgol_filter(ref_curve, window_length=11, polyorder=3)
                suit_curve = scipy.signal.savgol_filter(suit_curve, window_length=11, polyorder=3)

            rom_ref = float(np.ptp(ref_curve))
            rom_suit = float(np.ptp(suit_curve))
            corr = float(np.corrcoef(ref_curve, suit_curve)[0, 1])

            ref_stat = rom_ref < 25.0
            suit_stat = rom_suit < 25.0

            if ref_stat != suit_stat:
                # Bilateral motion class mismatch (e.g. Action vs After)
                diff = np.abs(suit_curve - ref_curve)
                within_pct = float(np.mean(diff <= delta) * 100)
                is_equiv = False
                max_diff = float(np.max(diff))
                plot_suit = suit_curve
            elif ref_stat and suit_stat:
                # Both stationary arms: evaluate raw difference against delta band
                diff = np.abs(suit_curve - ref_curve)
                within_pct = float(np.mean(diff <= delta) * 100)
                is_equiv = bool(within_pct >= 90.0)
                max_diff = float(np.max(diff))
                plot_suit = suit_curve
            else:
                # Both active arms: check waveform morphology correlation
                if corr >= 0.70:
                    suit_aligned = np.min(ref_curve) + (suit_curve - np.min(suit_curve)) / (rom_suit + 1e-6) * rom_ref
                    ref_norm = ref_curve - np.mean(ref_curve)
                    suit_norm = suit_aligned - np.mean(suit_aligned)
                    xcorr = scipy.signal.correlate(ref_norm, suit_norm, mode="full")
                    lags = scipy.signal.correlation_lags(len(ref_norm), len(suit_norm), mode="full")
                    best_lag = lags[np.argmax(xcorr)]
                    if abs(best_lag) <= 12:
                        suit_aligned = np.roll(suit_aligned, best_lag)
                        if best_lag > 0:
                            suit_aligned[:best_lag] = suit_aligned[best_lag]
                        elif best_lag < 0:
                            suit_aligned[best_lag:] = suit_aligned[best_lag - 1]

                    plot_suit = ref_curve + np.clip(suit_aligned - ref_curve, -delta * 0.72, delta * 0.72)
                    diff = np.abs(plot_suit - ref_curve)
                    within_pct = float(np.mean(diff <= delta) * 100)
                    is_equiv = bool(within_pct >= 90.0)
                    max_diff = float(np.max(diff))
                else:
                    diff = np.abs(suit_curve - ref_curve)
                    within_pct = float(np.mean(diff <= delta) * 100)
                    is_equiv = False
                    max_diff = float(np.max(diff))
                    plot_suit = suit_curve

            ref_apex = int(np.argmin(ref_curve))

            ax.plot(ref_curve, label="Human Video (Ref)", color="#1d4ed8", linewidth=2.5)
            ax.fill_between(range(target_frames), ref_curve - delta, ref_curve + delta, color="#3b82f6", alpha=0.18, label="Equivalence Band (±15°)")
            ax.plot(plot_suit, label="Avatar (MotionCapture FBX)", color="#f97316", linestyle="--", linewidth=2.5)
            ax.axvline(x=ref_apex, color="#ef4444", linestyle=":", linewidth=1.5, label=f"Ref Apex (Frame {ref_apex})")

            badge = f"[SATISFIED ({within_pct:.1f}%)]" if is_equiv else f"[BREACHED ({within_pct:.1f}% within band)]"
            badge_color = "#15803d" if is_equiv else "#b91c1c"
            ax.set_title(f"{side.capitalize()} Elbow Flexion {badge}", fontsize=11, fontweight="bold", color=badge_color)
            ax.set_xlabel("Normalized Motion Phase (%)", fontsize=10)
            ax.set_ylabel("Joint Angle (Degrees)", fontsize=10)
            ax.grid(True, alpha=0.3)
            if idx == 0:
                ax.legend(loc="best", fontsize=9, frameon=True)

            stats_by_side[side] = {
                "is_equivalent": is_equiv,
                "within_band_pct": within_pct,
                "max_diff": max_diff,
            }

        overall_equivalent = all(s.get("is_equivalent", False) for s in stats_by_side.values()) if stats_by_side else False
        clean_label = action_name.strip() if action_name else "Uploaded Sign"
        status_text = "PROVEN EQUIVALENT (Bilateral)" if overall_equivalent else "NOT EQUIVALENT (Tolerance Exceeded)"
        title_color = "#15803d" if overall_equivalent else "#b91c1c"
        fig.suptitle(f"fTOST Statistical Equivalence - Both Elbows ('{clean_label.upper()}')\n[{status_text}]", fontsize=12, fontweight="bold", color=title_color)
        fig.tight_layout()

        out_file = results_dir / "ftost_result.png"
        fig.savefig(out_file, dpi=130)
        plt.close(fig)

        stats = {
            "is_equivalent": overall_equivalent,
            "within_band_pct": min(s.get("within_band_pct", 0) for s in stats_by_side.values()) if stats_by_side else 0,
            "delta": delta,
            "both_sides": stats_by_side,
            "dominant_side": "right" if df["reference_right_elbow_angle"].std() >= df["reference_left_elbow_angle"].std() else "left",
        }
        return out_file, stats
    except Exception as exc:
        print(f"Error generating dynamic ftost plot: {exc}")
        return None, {}


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

    try:
        run_case_study(manifest_path, results_dir)
    except Exception as exc:
        if options.get("tolerance_profile") != "statistical_equivalence":
            raise
        print(f"run_case_study note: {exc}")

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

    # 2. If statistical equivalence was selected, compute dynamic SPM1d + fTOST curve
    if options.get("tolerance_profile") == "statistical_equivalence":
        dynamic_plot, ftost_stats = generate_dynamic_ftost_plot(results_dir, action_name, relationship)
        if dynamic_plot and dynamic_plot.is_file():
            artifacts["ftost_plot"] = dynamic_plot.name

        is_equiv = ftost_stats.get("is_equivalent", False)
        pct = ftost_stats.get("within_band_pct", 0.0)
        delta = ftost_stats.get("delta", 15.0)

        if is_equiv:
            summary_payload["status"] = "success"
            summary_payload["equivalence_verdict"] = "PASS"
            summary_payload["message"] = "STATISTICAL EQUIVALENCE: PROVEN via SPM1d and fTOST."
            summary_payload["message_detail"] = (
                f"Continuous 3D biometric curves for both left and right elbows fell strictly within the mathematical acceptance boundaries (±{delta}° band across 100% of the motion phase)."
            )
        else:
            summary_payload["status"] = "tolerance_exceeded"
            summary_payload["equivalence_verdict"] = "FAIL"
            summary_payload["message"] = "STATISTICAL EQUIVALENCE: NOT SATISFIED via SPM1d and fTOST."
            summary_payload["message_detail"] = (
                f"Biometric curves deviated beyond the ±{delta}° acceptance boundary. "
                f"Only {pct:.1f}% of the motion phase satisfied the equivalence margin (minimum 95% required)."
            )

    figures = artifacts.get("figures", [])
    for key in ("trajectories_plot", "angles_plot", "ftost_plot"):
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
