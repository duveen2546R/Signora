"""Project matched FBX joints into a single-camera reference and score paired motion."""

from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from .fbx_motion import Motion, load_motion
from .mixed_effects import PRIMARY_METRIC, ValidationError
from .trials import Trial, load_manifest, sha256
from .video_pose import VideoPose, read_pose_csv

PHASE = np.linspace(0.0, 1.0, 101)
MIN_CONFIDENCE = 0.70
MAX_REFERENCE_GAP_S = 0.15
MIN_COVERAGE = 0.80
MAX_TORSO_FIT_RMSE = 0.35  # reference shoulder widths


def _sample_video(source: VideoPose, window: tuple[float, float]) -> np.ndarray:
    """Interpolate observed landmarks only across short, high-confidence gaps."""
    queries = window[0] + PHASE * (window[1] - window[0])
    output = np.full((len(PHASE), 6, 2), np.nan)
    if window[1] > source.times[-1] + 1e-6:
        raise ValidationError("Video window exceeds the landmark track duration.")
    for joint in range(6):
        valid = (source.confidence[:, joint] >= MIN_CONFIDENCE
                 ) & np.isfinite(source.xy[:, joint]).all(axis=1)
        times = source.times[valid]
        points = source.xy[valid, joint]
        if len(times) < 2:
            continue
        after = np.searchsorted(times, queries, side="left")
        for i, next_index in enumerate(after):
            if next_index < len(times) and abs(times[next_index] - queries[i]) < 1e-7:
                output[i, joint] = points[next_index]
            elif 0 < next_index < len(times):
                before = next_index - 1
                gap = times[next_index] - times[before]
                if gap <= MAX_REFERENCE_GAP_S:
                    weight = (queries[i] - times[before]) / gap
                    output[i, joint] = points[before] * (1 - weight) + points[next_index] * weight
    return output


def _sample_motion(motion: Motion, window: tuple[float, float]) -> np.ndarray:
    if window[1] > motion.times[-1] + 1e-6:
        raise ValidationError(f"{motion.path.name}: annotated window exceeds FBX duration.")
    queries = window[0] + PHASE * (window[1] - window[0])
    output = np.empty((len(PHASE), 6, 3), dtype=float)
    for joint in range(6):
        for axis in range(3):
            output[:, joint, axis] = np.interp(
                queries, motion.times, motion.joints[:, joint, axis]
            )
    return output


def _reference_body_frame(xy: np.ndarray) -> tuple[np.ndarray, float]:
    shoulders = xy[:, :2]
    center = shoulders.mean(axis=1)
    center[~np.isfinite(shoulders).all(axis=(1, 2))] = np.nan
    widths = np.linalg.norm(shoulders[:, 0] - shoulders[:, 1], axis=1)
    widths = widths[np.isfinite(widths)]
    if len(widths) < 20 or np.median(widths) < 0.02:
        raise ValidationError("Reference shoulders are insufficient or too small for normalization.")
    width = float(np.median(widths))
    return (xy - center[:, None]) / width, width


def _motion_body_frame(xyz: np.ndarray) -> tuple[np.ndarray, float]:
    center = xyz[:, :2].mean(axis=1)
    width = float(np.median(np.linalg.norm(xyz[:, 0] - xyz[:, 1], axis=1)))
    if width < 0.05:
        raise ValidationError("FBX shoulder width is degenerate.")
    return (xyz - center[:, None]) / width, width


def _project(xyz: np.ndarray, rotation: np.ndarray, scale: float) -> np.ndarray:
    return (xyz @ Rotation.from_rotvec(rotation).as_matrix().T)[..., :2] * scale


def calibrate_camera(xyz: np.ndarray, reference: np.ndarray,
                     calibration_phase: tuple[float, float]) -> tuple[np.ndarray, float, float]:
    """Fit one constant camera rotation/scale using torso joints on a declared interval."""
    if xyz.shape != (101, 6, 3) or reference.shape != (101, 6, 2):
        raise ValidationError("Calibration needs 101 phase samples and six canonical joints.")
    start, end = calibration_phase
    phase_mask = (PHASE >= start) & (PHASE <= end)
    valid = phase_mask & np.isfinite(reference[:, :4]).all(axis=(1, 2))
    if valid.sum() < 5:
        raise ValidationError("At least five fully observed torso samples are needed for calibration.")
    source = xyz[valid, :4]
    target = reference[valid, :4]

    def residual(parameters: np.ndarray) -> np.ndarray:
        return (_project(source, parameters[:3], float(np.exp(parameters[3]))) - target).ravel()

    starts = (
        [0, 0, 0], [np.pi, 0, 0], [0, np.pi, 0],
        [0, np.pi / 2, 0], [0, -np.pi / 2, 0], [np.pi, np.pi / 2, 0],
    )
    solutions = [least_squares(residual, [*angles, 0.0], max_nfev=300,
                               bounds=([-2*np.pi]*3 + [np.log(0.35)],
                                       [2*np.pi]*3 + [np.log(2.5)]))
                 for angles in starts]
    best = min(solutions, key=lambda fit: np.mean(fit.fun ** 2))
    rmse = float(np.sqrt(np.mean(best.fun ** 2)))
    if not best.success or not np.isfinite(rmse) or rmse > MAX_TORSO_FIT_RMSE:
        raise ValidationError(
            f"Fixed camera calibration failed (torso RMSE {rmse:.3f} shoulder widths); "
            "review axes, paired takes, reference tracking, and the neutral interval."
        )
    return best.x[:3], float(np.exp(best.x[3])), rmse


def score_trial(trial: Trial) -> tuple[dict, list[dict], dict]:
    if trial.video_landmarks is None:
        raise ValidationError(f"{trial.performance_id}: video landmarks are missing.")
    reference = _sample_video(read_pose_csv(trial.video_landmarks), trial.windows["video"])
    reference, video_shoulder_width = _reference_body_frame(reference)
    captured = {}
    transforms = {}
    for label, file in (("suit", trial.suit_fbx), ("non_suit", trial.non_suit_fbx)):
        motion = load_motion(file)
        xyz, shoulder_width = _motion_body_frame(_sample_motion(motion, trial.windows[label]))
        rotation, scale, rmse = calibrate_camera(xyz, reference, trial.calibration_phase)
        captured[label] = _project(xyz, rotation, scale)
        transforms[label] = {
            "fbx_profile": motion.profile, "fbx_fps": motion.fps,
            "source_shoulder_width_m": shoulder_width, "rotation_vector_rad": rotation.tolist(),
            "scale": scale, "torso_fit_rmse_shoulder_widths": rmse,
        }
    valid = np.isfinite(reference[:, [4, 5]]).all(axis=(1, 2))
    coverage = float(np.mean(valid))
    if coverage < MIN_COVERAGE:
        raise ValidationError(
            f"{trial.performance_id}: only {coverage:.0%} of phases show both wrists and shoulders; "
            f"minimum is {MIN_COVERAGE:.0%}."
        )
    errors = {label: np.linalg.norm(captured[label][:, [4, 5]] - reference[:, [4, 5]], axis=2)
              for label in captured}
    means = {label: float(errors[label][valid].mean()) for label in errors}
    if min(means.values()) <= 0:
        raise ValidationError("A zero mean error needs a prespecified zero-handling policy before log analysis.")
    score = {
        "performance_id": trial.performance_id, "action_id": trial.action_id,
        "performer_id": trial.performer_id, "reference_id": trial.hashes["reference_video"],
        "metric": PRIMARY_METRIC, "suit_error": means["suit"],
        "non_suit_error": means["non_suit"],
    }
    traces = []
    for index, phase in enumerate(PHASE):
        row: dict[str, object] = {"phase": float(phase), "valid": int(valid[index])}
        for side, joint in (("left", 4), ("right", 5)):
            for axis, coordinate in (("x", 0), ("y", 1)):
                row[f"reference_{side}_{axis}"] = (
                    float(reference[index, joint, coordinate]) if valid[index] else ""
                )
                for label in ("suit", "non_suit"):
                    row[f"{label}_{side}_{axis}"] = (
                        float(captured[label][index, joint, coordinate]) if valid[index] else ""
                    )
            for label in ("suit", "non_suit"):
                row[f"{label}_{side}_error"] = float(errors[label][index, joint - 4]) if valid[index] else ""
        traces.append(row)
    diagnostics = {
        "performance_id": trial.performance_id,
        "pairing_verified_by": trial.pairing_verified_by,
        "video_landmarks_sha256": sha256(trial.video_landmarks),
        "source_sha256": trial.hashes,
        "reference_shoulder_width_image_fraction": video_shoulder_width,
        "common_wrist_coverage": coverage,
        "calibration_phase": trial.calibration_phase,
        "calibration": transforms,
        "durations_s": {label: end - start for label, (start, end) in trial.windows.items()},
        "duration_error_s": {label: (trial.windows[label][1] - trial.windows[label][0])
                             - (trial.windows["video"][1] - trial.windows["video"][0])
                             for label in ("suit", "non_suit")},
        "mean_wrist_error": means,
    }
    return score, traces, diagnostics


def run_manifest(path: str | Path, output: str | Path) -> dict:
    trials = load_manifest(path, require_landmarks=True)
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValidationError(f"Output directory already contains results: {output}. Use a fresh directory.")
    scores = []
    audits = []
    traces_by_id = {}
    failures = {}
    for trial in trials:
        try:
            score, traces, audit = score_trial(trial)
            scores.append(score)
            audits.append(audit)
            traces_by_id[trial.performance_id] = traces
        except ValidationError as exc:
            failures[trial.performance_id] = str(exc)
    if failures:
        # Never emit a selected subset of pairs that could bias a study result.
        raise ValidationError("Some trials failed QC; no paired score file was written: " + json.dumps(failures))
    output.mkdir(parents=True, exist_ok=True)
    traces_dir = output / "traces"
    traces_dir.mkdir(exist_ok=True)
    for performance_id, rows in traces_by_id.items():
        # IDs are metadata, not trusted filenames.
        safe_name = sha256(next(t.suit_fbx for t in trials if t.performance_id == performance_id))[:16]
        with (traces_dir / f"{safe_name}.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        overlay = traces_dir / f"{safe_name}.svg"
        _render_overlay(rows, performance_id, overlay)
        audit = next(a for a in audits if a["performance_id"] == performance_id)
        audit["trace_file"] = str(Path("traces") / f"{safe_name}.csv")
        audit["overlay_file"] = str(Path("traces") / f"{safe_name}.svg")
    with (output / "paired_scores.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=scores[0].keys())
        writer.writeheader()
        writer.writerows(scores)
    report = {
        "manifest_sha256": sha256(Path(path)), "n_trials": len(trials),
        "metric": PRIMARY_METRIC, "phase_samples": len(PHASE),
        "minimum_video_confidence": MIN_CONFIDENCE,
        "minimum_common_wrist_coverage": MIN_COVERAGE,
        "trials": audits,
    }
    (output / "qc.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def _render_overlay(rows: list[dict], label: str, path: Path) -> None:
    """Self-contained SVG for human inspection of fixed-camera wrist paths."""
    colors = {"reference": "#151515", "suit": "#087c9d", "non_suit": "#c65c23"}
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="540" viewBox="0 0 1000 540">',
             '<rect width="1000" height="540" fill="white"/>',
             f'<text x="25" y="32" font-family="sans-serif" font-size="19">{escape(label)}</text>']
    for panel, side in enumerate(("left", "right")):
        offset = panel * 500
        samples = [
            (float(row[f"{method}_{side}_x"]), float(row[f"{method}_{side}_y"]))
            for method in colors for row in rows if row["valid"]
        ]
        xmin, xmax = min(x for x, _ in samples), max(x for x, _ in samples)
        ymin, ymax = min(y for _, y in samples), max(y for _, y in samples)
        span = max(xmax - xmin, ymax - ymin, 0.2)
        center_x, center_y = (xmin + xmax) / 2, (ymin + ymax) / 2
        parts.append(f'<rect x="{offset + 15}" y="55" width="470" height="455" '
                     'fill="none" stroke="#d0d0d0"/>')
        parts.append(f'<text x="{offset + 28}" y="80" font-family="sans-serif" '
                     f'font-size="17">{side.title()} wrist</text>')
        for method, color in colors.items():
            segment = []
            for row in rows:
                if row["valid"]:
                    x = offset + 250 + (float(row[f"{method}_{side}_x"]) - center_x) / span * 385
                    y = 282 + (float(row[f"{method}_{side}_y"]) - center_y) / span * 385
                    segment.append(f"{x:.2f},{y:.2f}")
                elif segment:
                    parts.append(f'<polyline points="{" ".join(segment)}" fill="none" '
                                 f'stroke="{color}" stroke-width="2"/>')
                    segment = []
            if segment:
                parts.append(f'<polyline points="{" ".join(segment)}" fill="none" '
                             f'stroke="{color}" stroke-width="2"/>')
            parts.append(f'<text x="{offset + 28}" y="{465 + 15 * list(colors).index(method)}" '
                         f'font-family="sans-serif" font-size="12" fill="{color}">{method}</text>')
    parts.append('</svg>')
    path.write_text("\n".join(parts) + "\n")
