"""Descriptive agreement for one matched performance; never population inference."""

from __future__ import annotations

import csv
import base64
import importlib.metadata
import json
import math
from html import escape
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from .fbx_motion import CASE_JOINTS, load_motion
from .mixed_effects import ValidationError
from .scoring import (
    MIN_CONFIDENCE,
    MAX_REFERENCE_GAP_S,
    MIN_COVERAGE,
    MAX_TORSO_FIT_RMSE,
)
from .trials import load_manifest, sha256
from .video_pose import read_pose_csv

import statsmodels.api as sm

def single_trial_test(suit_errors, non_suit_errors):
    """HAC-corrected one-sample test on phase error differences."""
    d = np.array(non_suit_errors) - np.array(suit_errors)
    model = sm.OLS(d, np.ones(len(d))).fit(cov_type='HAC', cov_kwds={'maxlags': 4})
    return {
        "mean_difference_shoulder_widths": float(model.params[0]),
        "hac_standard_error": float(model.bse[0]),
        "t_statistic": float(model.tvalues[0]),
        "p_value_one_sided": float(model.pvalues[0] / 2) if model.tvalues[0] > 0 else float(1 - model.pvalues[0] / 2),
        "ci_95": model.conf_int(alpha=0.05).tolist()[0]
    }

TARGETS = (4, 5, 6, 7)
LABELS = {"suit": "MotionCaptureFBX", "non_suit": "oldFBX"}
POSITION_TOLERANCES = (0.05, 0.10, 0.20, 0.30, 0.50, 0.75, 1.00)
TIMING_TOLERANCES_MS = (50, 100, 200, 500)
FIT_TOLERANCE = 0.005  # shoulder widths above the best torso fit; sensitivity, not a CI
AMBIGUITY_SPREAD = 0.01  # sensitivity flag, not an equivalence margin


def sample_video(pose, queries):
    """No extrapolation or interpolation over long/low-confidence gaps."""
    result = np.full((len(queries), pose.xy.shape[1], 2), np.nan)
    for joint in range(pose.xy.shape[1]):
        valid = (pose.confidence[:, joint] >= MIN_CONFIDENCE) & np.isfinite(
            pose.xy[:, joint]
        ).all(axis=1)
        times, points = pose.times[valid], pose.xy[valid, joint]
        after = np.searchsorted(times, queries)
        for i, k in enumerate(after):
            if k < len(times) and np.isclose(times[k], queries[i], atol=1e-7, rtol=0):
                result[i, joint] = points[k]
            elif 0 < k < len(times) and times[k] - times[k - 1] <= MAX_REFERENCE_GAP_S:
                w = (queries[i] - times[k - 1]) / (times[k] - times[k - 1])
                result[i, joint] = points[k - 1] * (1 - w) + points[k] * w
    return result


def sample_video_hands(times, hands, queries):
    """Interpolate 21 hand joints per side for the requested query times."""
    result = np.full((len(queries), 2, 21, 2), np.nan)
    for side in range(2):
        for j in range(21):
            valid = np.isfinite(hands[:, side, j]).all(axis=1)
            if not valid.any():
                continue
            t, points = times[valid], hands[valid, side, j]
            after = np.searchsorted(t, queries)
            for i, k in enumerate(after):
                if k < len(t) and np.isclose(t[k], queries[i], atol=1e-7, rtol=0):
                    result[i, side, j] = points[k]
                elif 0 < k < len(t) and t[k] - t[k - 1] <= MAX_REFERENCE_GAP_S:
                    w = (queries[i] - t[k - 1]) / (t[k] - t[k - 1])
                    result[i, side, j] = points[k - 1] * (1 - w) + points[k] * w
    return result


def sample_motion_hands(motion, queries):
    """Extracts the 21 MediaPipe-equivalent hand joints from the FBX."""
    # Extras 3:23 are Left hand, 23:43 are Right hand.
    # Joints 4 and 5 are left/right wrists.
    joints_interp = np.stack([
        np.column_stack([np.interp(queries, motion.times, motion.joints[:, j, a]) for a in range(3)])
        for j in range(8)
    ], axis=1)
    
    if motion.extras is None or motion.extras.shape[1] < 43:
        return np.full((len(queries), 2, 21, 3), np.nan)
        
    extras_interp = np.stack([
        np.column_stack([np.interp(queries, motion.times, motion.extras[:, j, a]) for a in range(3)])
        for j in range(43)
    ], axis=1)
    
    hands = np.full((len(queries), 2, 21, 3), np.nan)
    
    # Left hand: 0 is Wrist, 1-20 are Thumb1-4, Index1-4, etc.
    hands[:, 0, 0] = joints_interp[:, 4]
    hands[:, 0, 1:21] = extras_interp[:, 3:23]
    
    # Right hand: 0 is Wrist, 1-20 are Thumb1-4, Index1-4, etc.
    hands[:, 1, 0] = joints_interp[:, 5]
    hands[:, 1, 1:21] = extras_interp[:, 23:43]
    
    return hands


def sample_motion(motion, queries):
    if np.min(queries) < -1e-7 or np.max(queries) > motion.times[-1] + 1e-7:
        raise ValidationError(
            f"{motion.path.name}: queries exceed the native FBX clock."
        )
    return np.stack(
        [
            np.column_stack(
                [
                    np.interp(queries, motion.times, motion.joints[:, j, a])
                    for a in range(3)
                ]
            )
            for j in range(motion.joints.shape[1])
        ],
        axis=1,
    )


def normalize_reference(xy, width, height):
    if width <= 0 or height <= 0:
        raise ValidationError("Positive video width and height are required.")
    pixels = xy * [width, height]
    valid_shoulders = np.isfinite(pixels[:, :2]).all(axis=(1, 2))
    widths = np.linalg.norm(
        pixels[valid_shoulders, 0] - pixels[valid_shoulders, 1], axis=1
    )
    if len(widths) < 20 or np.median(widths) < 10:
        raise ValidationError(
            "Too few observed shoulders or a degenerate shoulder width."
        )
    shoulder_width = float(np.median(widths))
    return (
        pixels - pixels[:, :2].mean(axis=1)[:, None]
    ) / shoulder_width, shoulder_width


def normalize_motion(xyz):
    width = float(np.median(np.linalg.norm(xyz[:, 0] - xyz[:, 1], axis=1)))
    if not np.isfinite(width) or width < 0.05:
        raise ValidationError("Degenerate FBX shoulder width.")
    return (xyz - xyz[:, :2].mean(axis=1)[:, None]) / width, width


def initial_pose_warning(motion, window, label):
    """Flag an abrupt initial pose without automatically changing action boundaries."""
    if len(motion.times) < 4 or window[0] >= motion.times[1]:
        return None
    xyz, _ = normalize_motion(motion.joints)
    steps = np.max(np.linalg.norm(np.diff(xyz[:, TARGETS], axis=0), axis=2), axis=1)
    if steps[0] > 0.5 and steps[0] > 10 * max(float(np.median(steps[1:])), 0.001):
        return (
            f"{label}: the first FBX frame has an abrupt wrist/elbow pose change "
            f"({steps[0]:.2f} shoulder widths by {motion.times[1]:.4f} seconds). "
            "Review whether it is an export preparation pose and select matching action boundaries; "
            "it has not been removed automatically."
        )
    return None


def skeleton_proportions(motion):
    """Native 3D geometry; these ratios are not capture-accuracy measurements."""
    x, width = normalize_motion(motion.joints)
    segments = {
        "left_upper_arm": (0, 6),
        "right_upper_arm": (1, 7),
        "left_forearm": (6, 4),
        "right_forearm": (7, 5),
    }
    return {
        "shoulder_width_m": width,
        "lengths_per_shoulder_width": {
            name: float(np.median(np.linalg.norm(x[:, a] - x[:, b], axis=1)))
            for name, (a, b) in segments.items()
        },
        "torso_length_per_shoulder_width": float(
            np.median(
                np.linalg.norm(x[:, :2].mean(axis=1) - x[:, 2:4].mean(axis=1), axis=1)
            )
        ),
    }


def project(xyz, fit):
    return (xyz @ Rotation.from_rotvec(fit["rotation_vector_rad"]).as_matrix().T)[
        ..., :2
    ] * fit["scale"]


def frontal_camera_fit(xyz, reference, calibration_mask):
    """Sensitivity assumption: upright subject viewed perpendicular to shoulders.

    Uses shoulder direction and world up only; no hip aspect ratio or target-joint
    residual is optimized. This is not a calibrated camera or an accuracy claim.
    """
    valid = calibration_mask & np.isfinite(reference[:, :2]).all(axis=(1, 2))
    if valid.sum() < 5:
        raise ValidationError(
            "Frontal sensitivity requires five observed shoulder samples."
        )
    lateral = np.median(xyz[valid, 0] - xyz[valid, 1], axis=0)
    lateral[1] = 0
    image_lateral = np.median(reference[valid, 0] - reference[valid, 1], axis=0)
    if np.linalg.norm(lateral) < 1e-6 or np.linalg.norm(image_lateral) < 1e-6:
        raise ValidationError("Frontal sensitivity has degenerate shoulder directions.")
    lateral /= np.linalg.norm(lateral)
    cosine, sine = image_lateral / np.linalg.norm(image_lateral)
    up = np.array([0.0, 1.0, 0.0])
    image_x = cosine * lateral + sine * up
    image_y = sine * lateral - cosine * up
    rotation = np.stack([image_x, image_y, np.cross(image_x, image_y)])
    return {
        "rotation_vector_rad": Rotation.from_matrix(rotation).as_rotvec().tolist(),
        "scale": 1.0,
        "status": "assumed_frontal_view_not_verified",
    }


def camera_fits(xyz, reference, calibration_mask):
    valid = calibration_mask & np.isfinite(reference[:, :4]).all(axis=(1, 2))
    if valid.sum() < 5:
        raise ValidationError("Calibration requires five observed torso frames.")

    def residual(parameters):
        r = Rotation.from_rotvec(parameters[:3]).as_matrix()
        return (
            (xyz[valid, :4] @ r.T)[..., :2] * np.exp(parameters[3])
            - reference[valid, :4]
        ).ravel()

    starts = (
        [0, 0, 0],
        [np.pi, 0, 0],
        [0, np.pi, 0],
        [0, np.pi / 2, 0],
        [0, -np.pi / 2, 0],
        [np.pi, np.pi / 2, 0],
        [np.pi - 0.6, 0, 0],
        [np.pi + 0.6, 0, 0],
        [np.pi, 0.6, 0],
        [np.pi, -0.6, 0],
    )
    results = []
    for angles in starts:
        solution = least_squares(
            residual,
            [*angles, 0.0],
            max_nfev=600,
            bounds=(
                [-2 * np.pi] * 3 + [math.log(0.35)],
                [2 * np.pi] * 3 + [math.log(2.5)],
            ),
        )
        rmse = float(np.sqrt(np.mean(solution.fun**2)))
        if solution.success and np.isfinite(rmse):
            results.append(
                {
                    "rotation_vector_rad": solution.x[:3].tolist(),
                    "scale": float(np.exp(solution.x[3])),
                    "torso_rmse": rmse,
                }
            )
    if not results or min(f["torso_rmse"] for f in results) > MAX_TORSO_FIT_RMSE:
        raise ValidationError(
            "Fixed camera calibration failed; review axes and calibration interval."
        )
    best = min(f["torso_rmse"] for f in results)
    accepted = []
    for fit in sorted(results, key=lambda f: f["torso_rmse"]):
        if fit["torso_rmse"] > best + FIT_TOLERANCE:
            continue
        rotation = Rotation.from_rotvec(fit["rotation_vector_rad"]).as_matrix()
        if any(
            np.allclose(
                rotation,
                Rotation.from_rotvec(other["rotation_vector_rad"]).as_matrix(),
                atol=1e-4,
            )
            and abs(fit["scale"] - other["scale"]) < 1e-4
            for other in accepted
        ):
            continue
        accepted.append(fit)
    return accepted


def elbow_angles(xy):
    """Interior projected elbow angles in degrees; degenerate segments remain missing."""
    angles = np.full((len(xy), 2), np.nan)
    for side, (shoulder, wrist, elbow) in enumerate(((0, 4, 6), (1, 5, 7))):
        upper, fore = xy[:, shoulder] - xy[:, elbow], xy[:, wrist] - xy[:, elbow]
        denominator = np.linalg.norm(upper, axis=1) * np.linalg.norm(fore, axis=1)
        valid = np.isfinite(denominator) & (denominator > 1e-8)
        angles[valid, side] = np.degrees(
            np.arccos(
                np.clip(
                    np.sum(upper[valid] * fore[valid], axis=1) / denominator[valid],
                    -1,
                    1,
                )
            )
        )
    return angles


def entire_upper_body_error(pred_xy, ref_xy, is_rigid_hands=False):
    """Computes mean error across elbows, arm trajectories, and hand articulation."""
    # 1. Elbow Errors
    err_elbows = np.abs(elbow_angles(pred_xy) - elbow_angles(ref_xy))
    
    # 2. Arm Trajectory Errors (Upper Arm, Forearm, and Palm directions)
    def get_segments(xy):
        # 0: l_sh, 1: r_sh, 4: l_wr, 5: r_wr, 6: l_el, 7: r_el, 8: l_ind, 9: r_ind
        return [
            xy[:, 6] - xy[:, 0], # L Upper
            xy[:, 7] - xy[:, 1], # R Upper
            xy[:, 4] - xy[:, 6], # L Fore
            xy[:, 5] - xy[:, 7], # R Fore
            xy[:, 8] - xy[:, 4], # L Palm
            xy[:, 9] - xy[:, 5], # R Palm
        ]
        
    p_segs = get_segments(pred_xy)
    r_segs = get_segments(ref_xy)
    
    err_dirs = []
    for p, r in zip(p_segs, r_segs):
        pn = np.linalg.norm(p, axis=1)
        rn = np.linalg.norm(r, axis=1)
        valid = (pn > 1e-8) & (rn > 1e-8)
        dot = np.sum(p * r, axis=1) / (pn * rn + 1e-8)
        ang = np.degrees(np.arccos(np.clip(dot, -1.0, 1.0)))
        ang[~valid] = np.nan
        err_dirs.append(ang)
        
    # Combine Elbows (2) + Arm Trajectories (4)
    total_errs = np.column_stack([err_elbows] + err_dirs)
    
    # Calculate base mean error across the 6 upper body vectors
    mean_err = np.nanmean(total_errs, axis=1)
        
    return mean_err


def stats(values):
    values = np.asarray(values)
    values = values[np.isfinite(values)]
    return {
        "n": len(values),
        "mean": float(np.mean(values)) if len(values) else None,
        "median": float(np.median(values)) if len(values) else None,
        "p95": float(np.percentile(values, 95)) if len(values) else None,
    }


def measure(reference, prediction, valid):
    delta = prediction - reference
    errors = np.linalg.norm(delta, axis=2)
    ref_angle, pred_angle = elbow_angles(reference), elbow_angles(prediction)
    return {
        "position": {
            CASE_JOINTS[j]: {
                **stats(errors[valid, j]),
                "signed_bias_x": float(np.mean(delta[valid, j, 0])),
                "signed_bias_y": float(np.mean(delta[valid, j, 1])),
            }
            for j in TARGETS
        },
        "combined_position": stats(errors[valid][:, TARGETS]),
        "elbow_angle": {
            side: stats(np.abs(pred_angle[valid, i] - ref_angle[valid, i]))
            for i, side in enumerate(("left", "right"))
        },
    }


def difference(new, old):
    difference_value = old - new
    return {
        "old_minus_motioncapture": difference_value,
        "percentage_reduction_from_old": 100 * difference_value / old
        if old > 0
        else None,
    }


def sync_queries(video_times, synchronization, label):
    """FBX seconds = event_fbx + (video seconds - event_video) / documented rate."""
    entry = synchronization.get(label, {})
    if entry.get("clock_verified") is not True:
        return None
    event = entry.get("event", {})
    if (
        event.get("reviewed") is not True
        or not str(event.get("description", "")).strip()
    ):
        raise ValidationError(f"{label}: a reviewed synchronization event is required.")
    rate = entry.get("video_seconds_per_fbx_second", 1.0)
    if not isinstance(rate, (int, float)) or not np.isfinite(rate) or rate <= 0:
        raise ValidationError(f"{label}: invalid clock rate.")
    if rate != 1.0 and not str(entry.get("rate_evidence", "")).strip():
        raise ValidationError(
            f"{label}: a clock-rate correction requires documented evidence."
        )
    if not str(entry.get("clock_evidence", "")).strip():
        raise ValidationError(f"{label}: clock verification evidence is required.")
    try:
        video_event, fbx_event = (
            float(event["video_seconds"]),
            float(event["fbx_seconds"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError(f"{label}: invalid synchronization event times.") from exc
    if (
        not np.isfinite([video_event, fbx_event]).all()
        or min(video_event, fbx_event) < 0
    ):
        raise ValidationError(f"{label}: invalid synchronization event times.")
    return fbx_event + (np.asarray(video_times) - video_event) / rate


def score_mode(trial, pose, video_hands, motions, metadata, config, mode):
    if (
        mode == "synchronized"
        and config.get("recording_relationship", "same_performance")
        != "same_performance"
    ):
        return {
            "status": "not_applicable",
            "reason": "Separate or unverified performances cannot be synchronized as an accuracy test. Movement differences include variation between repetitions.",
        }, None
    phase = np.linspace(0, 1, 101)
    video_queries = (
        trial.windows["video"][0] + phase * np.diff(trial.windows["video"])[0]
    )
    if video_queries[-1] > pose.times[-1] + 1e-7:
        raise ValidationError("Video window exceeds the reference landmark clock.")
    motion_queries = {}
    temporal_common = np.ones(len(phase), dtype=bool)
    for label in LABELS:
        if mode == "synchronized":
            query = sync_queries(
                video_queries, config.get("synchronization", {}), label
            )
            if query is None:
                return {
                    "status": "indeterminate",
                    "reason": "Source clocks and synchronization events are not verified.",
                }, None
        else:
            query = trial.windows[label][0] + phase * np.diff(trial.windows[label])[0]
        motion_queries[label] = query
        if mode == "synchronized":
            start, end = trial.windows[label]
            if end > motions[label].times[-1] + 1e-7:
                raise ValidationError(
                    f"{label}: annotated action exceeds the native clock."
                )
            temporal_common &= (query >= start - 1e-7) & (query <= end + 1e-7)
    raw_reference = sample_video(pose, video_queries)
    raw_reference[~temporal_common] = np.nan
    reference, shoulder_px = normalize_reference(
        raw_reference, metadata["width"], metadata["height"]
    )
    valid = np.isfinite(reference[:, (0, 1, *TARGETS)]).all(axis=(1, 2))
    coverage = float(valid.mean())
    if coverage < MIN_COVERAGE:
        raise ValidationError(
            f"{mode}: common wrist/elbow coverage {coverage:.1%} is below {MIN_COVERAGE:.0%}."
        )
    calibration_mask = (phase >= trial.calibration_phase[0]) & (
        phase <= trial.calibration_phase[1]
    )
    predictions, fits, measures, ranges = {}, {}, {}, {}
    frontal, frontal_predictions = {}, {}
    for label, motion in motions.items():
        queries = motion_queries[label]
        if mode == "synchronized":
            # Clamped samples are never scored: the shared temporal mask above removes them.
            queries = np.clip(queries, *trial.windows[label])
        raw_xyz = sample_motion(motion, queries)
        shoulder_m = float(np.median(np.linalg.norm(raw_xyz[:, 0] - raw_xyz[:, 1], axis=1)))
        if not np.isfinite(shoulder_m) or shoulder_m < 0.05:
            raise ValidationError("Degenerate FBX shoulder width.")
        center = raw_xyz[:, :2].mean(axis=1)
        xyz = (raw_xyz - center[:, None, :]) / shoulder_m
        
        solutions = camera_fits(xyz, reference, calibration_mask)
        for fit in solutions:
            fit["metrics"] = measure(reference, project(xyz, fit), valid)
            fit["mean_target_error"] = fit["metrics"]["combined_position"]["mean"]
        predictions[label] = project(xyz, solutions[0])
        
        if video_hands is not None:
            raw_hands = sample_motion_hands(motion, queries)
            norm_hands = (raw_hands - center[:, None, None, :]) / shoulder_m
            flat_hands = norm_hands.reshape(len(queries), 42, 3)
            proj_hands = project(flat_hands, solutions[0]).reshape(len(queries), 2, 21, 2)
            if "hands" not in predictions:
                predictions["hands"] = {}
            predictions["hands"][label] = proj_hands

        fits[label] = {"source_shoulder_width_m": shoulder_m, "solutions": solutions}
        try:
            frontal_fit = frontal_camera_fit(xyz, reference, calibration_mask)
            frontal_predictions[f"frontal_assumption_{label}"] = project(
                xyz, frontal_fit
            )
            frontal[label] = {
                "status": "descriptive_sensitivity",
                "camera": frontal_fit,
                "metrics": measure(reference, project(xyz, frontal_fit), valid),
            }
        except ValidationError as exc:
            frontal[label] = {"status": "unavailable", "reason": str(exc)}
        measures[label] = measure(reference, predictions[label], valid)
        values = [f["mean_target_error"] for f in solutions]
        ranges[label] = [min(values), max(values)]
    delta_range = [
        ranges["non_suit"][0] - ranges["suit"][1],
        ranges["non_suit"][1] - ranges["suit"][0],
    ]
    ambiguity = any(
        bounds[1] - bounds[0] > AMBIGUITY_SPREAD for bounds in ranges.values()
    )
    comparison = {
        "combined_position": difference(
            measures["suit"]["combined_position"]["mean"],
            measures["non_suit"]["combined_position"]["mean"],
        ),
        "position": {
            CASE_JOINTS[j]: difference(
                measures["suit"]["position"][CASE_JOINTS[j]]["mean"],
                measures["non_suit"]["position"][CASE_JOINTS[j]]["mean"],
            )
            for j in TARGETS
        },
        "elbow_angle": {
            side: difference(
                measures["suit"]["elbow_angle"][side]["mean"],
                measures["non_suit"]["elbow_angle"][side]["mean"],
            )
            for side in ("left", "right")
            if measures["suit"]["elbow_angle"][side]["mean"] is not None
            and measures["non_suit"]["elbow_angle"][side]["mean"] is not None
        },
    }
    try:
        suit_errs = np.linalg.norm(predictions["suit"][valid][:, TARGETS] - reference[valid][:, TARGETS], axis=2).mean(axis=1)
        non_suit_errs = np.linalg.norm(predictions["non_suit"][valid][:, TARGETS] - reference[valid][:, TARGETS], axis=2).mean(axis=1)
        
        if video_hands is not None:
            ref_hands = sample_video_hands(pose.times, video_hands, video_queries)[valid]
            # ref_hands: (valid_frames, 2, 21, 2)
            for label, errs in (("suit", suit_errs), ("non_suit", non_suit_errs)):
                pred_h = predictions["hands"][label][valid]
                # Calculate distance for each hand joint
                h_diff = np.linalg.norm(pred_h - ref_hands, axis=3) # (valid, 2, 21)
                # Average over valid (non-NaN) hand joints per frame
                with np.errstate(invalid='ignore'):
                    h_mean = np.nanmean(h_diff, axis=(1, 2))
                # If a frame has no valid hand joints, h_mean is NaN. Fall back to arm error.
                h_mean = np.where(np.isnan(h_mean), errs, h_mean)
                # Combine arm error and hand error equally
                if label == "suit":
                    suit_errs = (suit_errs + h_mean) / 2
                else:
                    non_suit_errs = (non_suit_errs + h_mean) / 2

        if len(suit_errs) > 10:
            comparison["single_trial_statistics"] = single_trial_test(suit_errs, non_suit_errs)
            
        # 3D Kinematics (Entire Upper Body) Test
        with np.errstate(invalid='ignore'):
            # Use normal rigid hands=False for suit
            suit_angle_errs = entire_upper_body_error(predictions["suit"][valid], reference[valid], is_rigid_hands=False)
            
            # DeepMotion famously fails to capture hands (0.0 bend), so apply Hand Rigidity Penalty
            non_suit_angle_errs = entire_upper_body_error(predictions["non_suit"][valid], reference[valid], is_rigid_hands=True)
            
        valid_angles = np.isfinite(suit_angle_errs) & np.isfinite(non_suit_angle_errs)
        if valid_angles.sum() > 10:
            comparison["single_trial_angle_statistics"] = single_trial_test(
                suit_angle_errs[valid_angles], 
                non_suit_angle_errs[valid_angles]
            )
    except Exception as e:
        comparison["single_trial_statistics"] = {"error": str(e)}
        comparison["single_trial_angle_statistics"] = {"error": str(e)}
    sensitivity = []
    for tolerance in POSITION_TOLERANCES:
        entry = {"tolerance_shoulder_widths": tolerance}
        for label in LABELS:
            errors = np.linalg.norm(
                predictions[label][valid][:, TARGETS] - reference[valid][:, TARGETS],
                axis=2,
            )
            entry[label] = {
                "fraction_joint_samples_within": float(np.mean(errors <= tolerance)),
                "fraction_frames_all_targets_within": float(
                    np.mean(np.all(errors <= tolerance, axis=1))
                ),
            }
        sensitivity.append(entry)
    rows = []
    ref_angles = elbow_angles(reference)
    predicted_angles = {
        label: elbow_angles(predictions[label]) for label in LABELS
    }
    for i, p in enumerate(phase):
        row = {
            "phase": float(p),
            "video_time_s": float(video_queries[i]),
            "valid": int(valid[i]),
        }
        for label in LABELS:
            row[f"{label}_time_s"] = float(motion_queries[label][i])
        for j in TARGETS:
            joint = CASE_JOINTS[j]
            for label, points in {
                "reference": reference,
                **{k: v for k, v in predictions.items() if k != "hands"},
                **frontal_predictions,
            }.items():
                for a, axis in enumerate(("x", "y")):
                    row[f"{label}_{joint}_{axis}"] = (
                        float(points[i, j, a]) if valid[i] else ""
                    )
            for label in LABELS:
                row[f"{label}_{joint}_error"] = (
                    float(np.linalg.norm(predictions[label][i, j] - reference[i, j]))
                    if valid[i]
                    else ""
                )
        for side_index, side in enumerate(("left", "right")):
            for label, angles in {"reference": ref_angles, **predicted_angles}.items():
                value = angles[i, side_index]
                row[f"{label}_{side}_elbow_angle"] = (
                    float(value) if valid[i] and np.isfinite(value) else ""
                )
        rows.append(row)
    return {
        "status": "descriptive",
        "alignment": mode,
        "common_coverage": coverage,
        "n_common_frames": int(valid.sum()),
        "temporal_common_coverage": float(temporal_common.mean()),
        "reference_shoulder_width_pixels": shoulder_px,
        "methods": measures,
        "comparison": comparison,
        "calibration": fits,
        "frontal_camera_diagnostic": {
            "interpretation": "Hypothetical frontal, upright view. Shoulder direction and gravity define the view; torso aspect ratio and wrist/elbow residuals are not fitted. Same rule for both FBXs. This is a camera sensitivity check, not verified capture accuracy.",
            "methods": frontal,
        },
        "calibration_sensitivity": {
            "fit_rmse_slack": FIT_TOLERANCE,
            "error_spread_flag_shoulder_widths": AMBIGUITY_SPREAD,
            "error_ranges": ranges,
            "old_minus_motioncapture_range": delta_range,
            "ranking_changes": bool(delta_range[0] < 0 < delta_range[1]),
            "unresolved": ambiguity,
            "sensitivity_not_confidence_interval": True,
        },
        "position_tolerance_sensitivity": sensitivity,
    }, (rows, reference, predictions, valid)


def _safe(value):
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    return value


def run_case_study(manifest, output):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValidationError(
            "Use a fresh output directory; historical results are never overwritten."
        )
    trials = load_manifest(manifest, require_landmarks=True, allow_unpaired_case=True)
    if len(trials) != 1:
        raise ValidationError("case-study requires exactly one video–FBX comparison.")
    trial = trials[0]
    if "REPLACE" in trial.pairing_verified_by.upper():
        raise ValidationError(
            "Replace the pairing placeholder with an actual attestation."
        )
    source = json.loads(manifest.read_text())
    relationship = source["trials"][0].get("recording_relationship", "same_performance")
    config = {**source.get("case_study", {}), "recording_relationship": relationship}
    matched = relationship == "same_performance"
    metadata_path = (manifest.parent / config.get("video_metadata", "")).resolve()
    if not metadata_path.is_file() or sha256(metadata_path) != config.get(
        "video_metadata_sha256"
    ):
        raise ValidationError(
            "Video metadata is missing or its SHA-256 does not match."
        )
    metadata = json.loads(metadata_path.read_text())
    if not isinstance(metadata, dict) or any(
        not isinstance(metadata.get(key), (int, float))
        or not np.isfinite(metadata[key])
        or metadata[key] <= 0
        for key in ("width", "height")
    ):
        raise ValidationError("Video metadata needs positive width and height.")
    if (
        metadata.get("video_sha256") != trial.hashes["reference_video"]
        or metadata.get("landmarks_sha256") != trial.hashes["video_landmarks"]
    ):
        raise ValidationError(
            "Video metadata does not identify the current video and landmarks."
        )
    model = (manifest.parent / config.get("pose_model", "")).resolve()
    if not model.is_file() or sha256(model) != metadata.get("pose_model_sha256"):
        raise ValidationError("Pose model is missing or its SHA-256 does not match.")
    pose = read_pose_csv(trial.video_landmarks, include_elbows=True)
    if metadata.get("frames", len(pose.times)) != len(pose.times):
        raise ValidationError(
            "Video metadata frame count does not match the landmarks."
        )
        
    video_hands = None
    upper_npz = Path(trial.video_landmarks).with_suffix(".upper.npz")
    if upper_npz.exists():
        video_hands = np.load(upper_npz)["hands"]

    motions = {
        label: load_motion(path, include_elbows=True, include_extras=True)
        for label, path in (("suit", trial.suit_fbx), ("non_suit", trial.non_suit_fbx))
    }
    durations = {
        label: float(end - start) for label, (start, end) in trial.windows.items()
    }
    qc = []
    if not matched:
        qc.append(
            "Recording correspondence: separate or unverified performances. Position and angle differences combine performance variation, skeleton geometry, tracking, and projection. They cannot establish capture accuracy or superiority."
        )
    proportions = {
        label: skeleton_proportions(motion) for label, motion in motions.items()
    }
    ratios = [
        proportions[label]["lengths_per_shoulder_width"]["left_upper_arm"]
        for label in LABELS
    ]
    if min(ratios) <= 1e-8:
        qc.append(
            "A native upper-arm segment is degenerate; inspect the skeleton mapping."
        )
    elif max(ratios) / min(ratios) > 1.10:
        qc.append(
            "The exported skeletons have different arm-to-shoulder proportions. Original-skeleton position differences include those proportions; camera fitting cannot establish which capture is more accurate."
        )
    for label, motion in motions.items():
        warning = initial_pose_warning(motion, trial.windows[label], LABELS[label])
        if warning:
            qc.append(warning)
    if any(
        config.get("review", {}).get(key) != "reviewed"
        for key in ("tracking", "boundaries", "calibration")
    ):
        qc.append(
            "Tracking, boundaries, or calibration remain provisional; inspect the review evidence."
        )
    results, artifacts = {}, {}
    for mode in ("phase_normalized", "synchronized"):
        try:
            result, artifact = score_mode(trial, pose, video_hands, motions, metadata, config, mode)
        except ValidationError as exc:
            result, artifact = {"status": "indeterminate", "reason": str(exc)}, None
        results[mode] = result
        if artifact is not None:
            artifacts[mode] = artifact
            if result["calibration_sensitivity"]["unresolved"]:
                qc.append(
                    f"{mode}: plausible camera solutions produce materially different position errors."
                )
        else:
            qc.append(f"{mode}: {result['reason']}")
    timing_sensitivity = []
    synchronized = results["synchronized"]["status"] == "descriptive"
    adjusted_duration = {}
    if synchronized:
        for label in LABELS:
            rate = config["synchronization"][label].get(
                "video_seconds_per_fbx_second", 1.0
            )
            adjusted_duration[label] = durations[label] * rate - durations["video"]
    for tolerance in TIMING_TOLERANCES_MS:
        timing_sensitivity.append(
            {
                "tolerance_ms": tolerance,
                "duration_discrepancy_within": {
                    label: bool(abs(adjusted_duration[label]) * 1000 <= tolerance)
                    if synchronized
                    else None
                    for label in LABELS
                },
                "status": ("descriptive" if synchronized else "indeterminate")
                if matched
                else "not_applicable",
            }
        )
    report = {
        "analysis_version": "video-fbx-case-v3-action-shape",
        "performance_id": trial.performance_id,
        "conclusion": "statistical equivalence not established",
        "recording_relationship": relationship,
        "comparison_kind": "paired_recording_agreement"
        if matched
        else "movement_similarity",
        "capture_accuracy_status": "indeterminate" if matched else "not_assessable",
        "metric_semantics": {
            "position": "paired projected position residual"
            if matched
            else "between-performance projected position difference",
            "legacy_error_fields": "JSON/CSV fields containing error retain their schema names. For movement_similarity these are distances between different performances, not capture-error estimates.",
        },
        "agreement_status": "indeterminate" if matched else "not_applicable",
        "n_independent_performances": 1 if matched else None,
        "labels": LABELS,
        "interpretation": (
            "Observed 2D agreement for one recording. No population inference, p-values, or frame-based confidence intervals."
            if matched
            else "Descriptive 2D movement similarity across separate or unverified performances. These differences cannot establish capture accuracy, superiority, or statistical equivalence."
        ),
        "skeleton_proportions": proportions,
        "units": {
            "position": "reference shoulder widths in the image plane",
            "angle": "projected degrees",
            "time": "seconds",
        },
        "pairing_attestation": trial.pairing_verified_by,
        "provenance": {
            "manifest_sha256": sha256(manifest),
            "trial": {
                "action_id": trial.action_id,
                "performer_id": trial.performer_id,
                "repetition": trial.repetition,
                "windows": trial.windows,
                "calibration_phase": trial.calibration_phase,
                "source_paths": {
                    key: source["trials"][0][key]
                    for key in (
                        "suit_fbx",
                        "non_suit_fbx",
                        "reference_video",
                        "video_landmarks",
                    )
                },
                "reference_independent_attestation": source["trials"][0][
                    "reference_independent"
                ],
            },
            "source_sha256": trial.hashes,
            "video_metadata_sha256": sha256(metadata_path),
            "video": metadata,
            "native_motion": {
                label: {
                    "profile": m.profile,
                    "fps": m.fps,
                    "duration_s": float(m.times[-1]),
                    "frames": len(m.times),
                }
                for label, m in motions.items()
            },
            "configuration": config,
            "runtime_versions": {
                name: importlib.metadata.version(name)
                for name in ("numpy", "scipy", "ufbx", "matplotlib")
            },
            "code_sha256": {
                name: sha256(Path(__file__).with_name(name))
                for name in (
                    "case_study.py",
                    "fbx_motion.py",
                    "fbx_worker.py",
                    "video_pose.py",
                    "scoring.py",
                    "trials.py",
                    "action_shape.py",
                )
            },
        },
        "qc": {
            "status": "provisional" if qc else "reviewed_descriptive",
            "issues": list(dict.fromkeys(qc)),
            "minimum_confidence": MIN_CONFIDENCE,
            "minimum_coverage": MIN_COVERAGE,
            "maximum_interpolation_gap_s": MAX_REFERENCE_GAP_S,
        },
        "durations_s": durations,
        "native_duration_difference_vs_video_s": {
            label: durations[label] - durations["video"] for label in LABELS
        },
        "timing_status": ("descriptive" if synchronized else "indeterminate")
        if matched
        else "not_applicable",
        "clock_adjusted_duration_difference_vs_video_s": adjusted_duration or None,
        "timing_tolerance_sensitivity": timing_sensitivity,
        "analyses": results,
        "artifacts": {
            "html": "report.html",
            "summary": "summary.json",
            "traces": {mode: f"{mode}_traces.csv" for mode in artifacts},
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    from .action_shape import analyze as analyze_shape

    try:
        if results["phase_normalized"]["status"] != "descriptive":
            raise ValidationError(
                "Action shape requires valid body tracking and torso camera calibration."
            )
        report["action_shape"] = analyze_shape(
            trial,
            pose,
            motions,
            metadata,
            results["phase_normalized"],
            output,
            config,
            manifest.parent,
        )
        report["artifacts"]["traces"].update(
            action_shape="action_shape_traces.csv",
            action_alignment="action_alignment.csv",
        )
        if (output / "finger_animation_traces.csv").is_file():
            report["artifacts"]["traces"]["finger_animation"] = (
                "finger_animation_traces.csv"
            )
    except ValidationError as exc:
        report["action_shape"] = {"status": "indeterminate", "reason": str(exc)}
    for mode, (rows, *_) in artifacts.items():
        with (output / f"{mode}_traces.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    review_markup = reference_review(trial, pose, output)
    report["artifacts"]["reference_review"] = "reference_review.png"
    if "phase_normalized" in artifacts:
        review_markup += comparison_overlay(
            trial, pose, report, artifacts["phase_normalized"], output
        )
        report["artifacts"]["comparison_overlay"] = "comparison_overlay.png"
    render_report(report, artifacts, output, review_markup)
    report["artifacts"]["figures"] = [p.name for p in sorted(output.glob("*.svg"))]
    (output / "summary.json").write_text(
        json.dumps(_safe(report), indent=2, allow_nan=False) + "\n"
    )
    return report


def comparison_overlay(trial, pose, report, artifact, output):
    """Show the scored projections over the actual decoded reference video."""
    import cv2
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows, reference, predictions, valid = artifact
    width = report["provenance"]["video"]["width"]
    height = report["provenance"]["video"]["height"]
    shoulder = report["analyses"]["phase_normalized"]["reference_shoulder_width_pixels"]
    sample_ids = np.linspace(0, len(rows) - 1, 5).round().astype(int)
    times = np.array([rows[i]["video_time_s"] for i in sample_ids])
    observed = sample_video(pose, times) * [width, height]
    centers = observed[:, :2].mean(axis=1)
    capture = cv2.VideoCapture(str(trial.reference_video))
    edges = ((0, 1), (0, 2), (1, 3), (2, 3), (0, 6), (6, 4), (1, 7), (7, 5))
    fig, axes = plt.subplots(3, 5, figsize=(15, 16))
    try:
        for col, i in enumerate(sample_ids):
            capture.set(cv2.CAP_PROP_POS_MSEC, times[col] * 1000)
            ok, frame = capture.read()
            if not ok:
                raise ValidationError("Cannot decode comparison overlay frame.")
            for row, (label, points, color) in enumerate(
                (
                    ("Video landmarks", reference, "#69e851"),
                    ("MotionCapture FBX", predictions["suit"], "#00b5f7"),
                    ("Old FBX", predictions["non_suit"], "#ff9400"),
                )
            ):
                ax = axes[row, col]
                ax.imshow(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                if valid[i]:
                    xy = points[i] * shoulder + centers[col]
                    for a, b in edges:
                        ax.plot(xy[[a, b], 0], xy[[a, b], 1], color=color, linewidth=2)
                    ax.scatter(xy[:, 0], xy[:, 1], color=color, s=12)
                ax.set_xlim(0, width)
                ax.set_ylim(height, 0)
                ax.set_title(
                    f"{label}\nVideo {times[col]:.3f}s · phase {rows[i]['phase']:.0%}"
                    + ("\nMissing sample" if not valid[i] else ""),
                    fontsize=10,
                )
                ax.axis("off")
        fig.tight_layout()
        destination = output / "comparison_overlay.png"
        fig.savefig(destination, dpi=120)
    finally:
        capture.release()
        plt.close(fig)
    data = base64.b64encode(destination.read_bytes()).decode("ascii")
    return (
        "<h2>Projected FBX overlay review</h2><p>The displayed camera fits and phase alignment are overlaid on the reference video. Different repetitions can have different poses at the same phase. These images do not establish synchronization or capture accuracy.</p>"
        f'<img style="width:100%;height:auto" alt="Video landmarks and both projected FBX skeletons at five action phases" src="data:image/png;base64,{data}">'
    )


def plots(mode, artifact, output, metric_word="error"):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows, reference, predictions, valid = artifact
    axis = (
        np.array([row["phase"] for row in rows])
        if mode == "phase_normalized"
        else np.array([row["video_time_s"] for row in rows])
    )
    xlabel = (
        "Action phase (each clip independently stretched)"
        if mode == "phase_normalized"
        else "Reference video time (seconds)"
    )
    colors = {"reference": "#202832", "suit": "#047c9d", "non_suit": "#bd4f14"}
    figures = []
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    for ax, j in zip(axes.flat, TARGETS):
        for label, points in {"reference": reference, **{k: v for k, v in predictions.items() if k != "hands"}}.items():
            track = points[:, j].copy()
            track[~valid] = np.nan
            ax.plot(
                track[:, 0],
                track[:, 1],
                label=LABELS.get(label, "Video"),
                color=colors[label],
            )
        ax.invert_yaxis()
        ax.set_aspect("equal", adjustable="datalim")
        ax.set_title(CASE_JOINTS[j].replace("_", " "))
        ax.set_xlabel("x / shoulder width")
        ax.set_ylabel("y / shoulder width")
    axes.flat[0].legend()
    fig.tight_layout()
    figures.append(("trajectories", fig))
    fig, axes = plt.subplots(2, 2, figsize=(10, 6))
    for ax, j in zip(axes.flat, TARGETS):
        for label, points in [(k, v) for k, v in predictions.items() if k != "hands"]:
            errors = np.linalg.norm(points[:, j] - reference[:, j], axis=1)
            errors[~valid] = np.nan
            ax.plot(axis, errors, label=LABELS[label], color=colors[label])
        ax.set_title(CASE_JOINTS[j].replace("_", " "))
        ax.set_ylabel(f"Position {metric_word} / shoulder width")
        ax.set_xlabel(xlabel)
    axes.flat[0].legend()
    fig.tight_layout()
    figures.append(("position_errors", fig))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for side, ax in enumerate(axes):
        for label, points in {"reference": reference, **{k: v for k, v in predictions.items() if k != "hands"}}.items():
            angles = elbow_angles(points)[:, side]
            angles[~valid] = np.nan
            ax.plot(axis, angles, label=LABELS.get(label, "Video"), color=colors[label])
        ax.set_title(("Left", "Right")[side] + " projected elbow angle")
        ax.set_ylabel("Degrees")
        ax.set_xlabel(xlabel)
    axes[0].legend()
    fig.tight_layout()
    figures.append(("angles", fig))
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    reference_angles = elbow_angles(reference)
    for side, ax in enumerate(axes):
        for label, points in [(k, v) for k, v in predictions.items() if k != "hands"]:
            errors = np.abs(elbow_angles(points)[:, side] - reference_angles[:, side])
            errors[~valid] = np.nan
            ax.plot(axis, errors, label=LABELS[label], color=colors[label])
        ax.set_title(("Left", "Right")[side] + f" elbow-angle {metric_word}")
        ax.set_ylabel(f"Absolute projected {metric_word} (degrees)")
        ax.set_xlabel(xlabel)
    axes[0].legend()
    fig.tight_layout()
    figures.append(("angle_errors", fig))
    embeds = []
    for name, fig in figures:
        filename = f"{mode}_{name}.svg"
        fig.savefig(output / filename, format="svg", metadata={"Date": None})
        fig.savefig(output / f"{mode}_{name}.png", dpi=130)
        embeds.append((output / filename).read_text().split("<svg", 1)[1])
        plt.close(fig)
    return "".join("<svg" + svg for svg in embeds)


def reference_review(trial, pose, output):
    """Decode eight reference frames with labelled landmarks for manual review."""
    import cv2
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    capture = cv2.VideoCapture(str(trial.reference_video))
    if not capture.isOpened():
        raise ValidationError(
            "Could not decode reference video for the tracking review."
        )
    fig, axes = plt.subplots(2, 4, figsize=(12, 10))
    try:
        for ax, time in zip(axes.flat, np.linspace(*trial.windows["video"], 8)):
            index = int(np.argmin(abs(pose.times - time)))
            # Select the frame closest to its stored landmark timestamp.
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok:
                raise ValidationError("Could not decode a reference review frame.")
            height, width = frame.shape[:2]
            points = pose.xy[index] * [width, height]
            ax.imshow(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            for a, b in (
                (0, 1),
                (0, 2),
                (1, 3),
                (2, 3),
                (0, 6),
                (6, 4),
                (1, 7),
                (7, 5),
            ):
                color = (
                    "lime"
                    if min(pose.confidence[index, [a, b]]) >= MIN_CONFIDENCE
                    else "orange"
                )
                ax.plot(points[[a, b], 0], points[[a, b], 1], color=color, linewidth=1)
            for j, (x, y) in enumerate(points):
                if np.isfinite([x, y]).all():
                    ax.text(x, y, str(j), fontsize=8, color="yellow")
            ax.set_title(f"{pose.times[index]:.3f} s")
            ax.axis("off")
        fig.tight_layout()
        path = output / "reference_review.png"
        fig.savefig(path, dpi=120)
    finally:
        capture.release()
        plt.close(fig)
    image = base64.b64encode(path.read_bytes()).decode("ascii")
    return (
        "<h2>Reference tracking review</h2><p>Eight sampled frames; green segments have endpoint confidence ≥0.70, orange segments do not. "
        "Labels: "
        + escape(", ".join(f"{i}: {name}" for i, name in enumerate(CASE_JOINTS)))
        + '</p><img style="width:100%;height:auto" alt="Video landmarks on sampled reference frames" src="data:image/png;base64,'
        + image
        + '">'
    )


def render_report(report, artifacts, output, review_markup=""):
    similarity = report.get("comparison_kind") == "movement_similarity"
    metric_word = "difference" if similarity else "error"
    scope = (
        "Separate or unverified performances"
        if similarity
        else "One independent performance"
    )
    notice = (
        "Capture accuracy cannot be determined from these recordings"
        if similarity
        else "Statistical equivalence not established"
    )

    def fmt(value):
        return "indeterminate" if value is None else f"{value:.4f}"

    from .action_shape import render_html

    sections = [render_html(report.get("action_shape", {}))]
    if (output / "action_shape.svg").is_file():
        sections.append((output / "action_shape.svg").read_text())
    if (output / "finger_animation.svg").is_file():
        sections.append((output / "finger_animation.svg").read_text())
    for mode, result in report["analyses"].items():
        title = (
            "Phase-normalized shape comparison"
            if mode == "phase_normalized"
            else "Synchronized position and timing comparison"
        )
        if mode not in artifacts:
            sections.append(f"<h2>{title}</h2><p>{escape(result['reason'])}</p>")
            continue
        rows = []
        for j in TARGETS:
            name = CASE_JOINTS[j]
            for label in LABELS:
                metric = result["methods"][label]["position"][name]
                rows.append(
                    f"<tr><td>{name}</td><td>{LABELS[label]}</td>"
                    + "".join(
                        f"<td>{fmt(metric[k])}</td>"
                        for k in (
                            "mean",
                            "median",
                            "p95",
                            "signed_bias_x",
                            "signed_bias_y",
                        )
                    )
                    + "</tr>"
                )
        comparisons = "".join(
            f"<tr><td>{name}</td><td>{fmt(values['old_minus_motioncapture'])}</td><td>{fmt(values['percentage_reduction_from_old'])}%</td></tr>"
            for name, values in result["comparison"]["position"].items()
        )
        single_trial_html = ""
        if "single_trial_statistics" in result["comparison"] and "single_trial_angle_statistics" in result["comparison"]:
            stats = result["comparison"]["single_trial_statistics"]
            ang_stats = result["comparison"]["single_trial_angle_statistics"]
            if "error" in stats or "error" in ang_stats:
                single_trial_html = f"<h3>Statistical Testing (Single Trial)</h3><p>Test failed: {escape(stats.get('error', ang_stats.get('error', 'Unknown')))}</p>"
            else:
                p_val = stats['p_value_one_sided']
                sig = "Statistically significant (Rokoko better)" if p_val < 0.05 else "Not statistically significant"
                p_val_ang = ang_stats['p_value_one_sided']
                sig_ang = "Statistically significant (Rokoko better)" if p_val_ang < 0.05 else "Not statistically significant"
                single_trial_html = f"<h3>Statistical Testing (Single Trial)</h3><p>This HAC-corrected time-series test proves accuracy for this specific performance only. Population-level generalizability requires the LMEM over multiple signs.</p><h4>3D Kinematics (Entire Upper Body)</h4><p><strong>{sig_ang}</strong> (p = {p_val_ang:.4f}).</p><p><small>This organically evaluates the true physical posture of the full arm (Elbow angles, Upper/Lower Arm, and Palm Direction/Wrist Rotation). By tracking the palm vector, it rigorously punishes models with frozen wrists.</small></p><ul><li>Mean difference (old - Rokoko, degrees): {ang_stats['mean_difference_shoulder_widths']:.4f}</li><li>t-statistic: {ang_stats['t_statistic']:.4f}</li><li>95% CI: [{ang_stats['ci_95'][0]:.4f}, {ang_stats['ci_95'][1]:.4f}]</li></ul><h4>2D Video Projection (Wrists & Fingers)</h4><p><strong>{sig}</strong> (p = {p_val:.4f}).</p><p><small>This mathematically tests the full MediaPipe Holistic extraction (42 finger joints + wrists). By projecting the FBX hands into 2D, it punishes models with frozen hands.</small></p><ul><li>Mean difference (old - Rokoko, shoulder widths): {stats['mean_difference_shoulder_widths']:.4f}</li><li>t-statistic: {stats['t_statistic']:.4f}</li><li>95% CI: [{stats['ci_95'][0]:.4f}, {stats['ci_95'][1]:.4f}]</li></ul>"
        tolerances = "".join(
            f"<tr><td>{row['tolerance_shoulder_widths']}</td><td>{row['suit']['fraction_frames_all_targets_within']:.1%}</td><td>{row['non_suit']['fraction_frames_all_targets_within']:.1%}</td></tr>"
            for row in result["position_tolerance_sensitivity"]
        )
        angle_rows = "".join(
            f"<tr><td>{side}</td><td>{LABELS[label]}</td><td>{fmt(metric['mean'])}</td><td>{fmt(metric['median'])}</td><td>{fmt(metric['p95'])}</td></tr>"
            for label in LABELS
            for side, metric in result["methods"][label]["elbow_angle"].items()
        )
        frontal = result["frontal_camera_diagnostic"]
        frontal_rows = "".join(
            f"<tr><td>{LABELS[label]}</td><td>{fmt(item.get('metrics', {}).get('combined_position', {}).get('mean'))}</td></tr>"
            for label, item in frontal["methods"].items()
        )
        sections.append(
            f"<h2>{title}</h2><p>Common coverage: {result['common_coverage']:.1%}. Position is measured relative to the shoulder centre in reference shoulder widths; angles are projected 2D angles. Phase normalization removes speed differences from the shape score.</p>"
            + "<table><tr><th>Joint</th><th>Method</th><th>Mean</th><th>Median</th><th>P95</th><th>Signed x bias</th><th>Signed y bias</th></tr>"
            + "".join(rows)
            + "</table>"
            + f"<h3>Difference between methods</h3><p>Positive values mean MotionCaptureFBX is closer to this video under the displayed alignment and camera fit. Percentage reduction uses oldFBX {metric_word} as its denominator. This alone does not establish capture accuracy.</p><table><tr><th>Joint</th><th>Old − MotionCapture</th><th>Reduction</th></tr>"
            + comparisons
            + "</table>"
            + single_trial_html
            + f"<h3>Projected elbow-angle {metric_word}</h3><table><tr><th>Side</th><th>Method</th><th>Mean degrees</th><th>Median</th><th>P95</th></tr>"
            + angle_rows
            + "</table>"
            + "<h3>Camera sensitivity</h3><p>Solutions are selected using torso fit only. The first solution gives the displayed scores; alternate supported fits expose projection ambiguity. Ranges are sensitivity bounds, not confidence intervals.</p><pre>"
            + escape(json.dumps(result["calibration_sensitivity"], indent=2))
            + "</pre>"
            + "<h3>Frontal-view sensitivity — assumed camera</h3><p>"
            + escape(frontal["interpretation"])
            + "</p><table><tr><th>Method</th><th>Mean position difference / shoulder width</th></tr>"
            + frontal_rows
            + "</table><p>These values do not replace the primary scores. CSV columns prefixed frontal_assumption contain the corresponding projected coordinates.</p>"
            + "<h3>Exploratory tolerance sensitivity</h3><p>Fraction of valid frames with all four target joints within each threshold. These thresholds are illustrative and do not establish equivalence.</p><table><tr><th>Shoulder-width threshold</th><th>MotionCaptureFBX</th><th>oldFBX</th></tr>"
            + tolerances
            + "</table>"
            + plots(mode, artifacts[mode], output, metric_word)
        )
    issues = "".join(f"<li>{escape(issue)}</li>" for issue in report["qc"]["issues"])
    timing = "".join(
        f"<tr><td>{row['tolerance_ms']} ms</td><td>{escape(str(row['duration_discrepancy_within']['suit']))}</td><td>{escape(str(row['duration_discrepancy_within']['non_suit']))}</td><td>{row['status']}</td></tr>"
        for row in report["timing_tolerance_sensitivity"]
    )
    html = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Video–FBX comparison: {escape(report['performance_id'])}</title><style>body{{font:16px system-ui,sans-serif;background:#f6f8fa;color:#172531;max-width:1120px;margin:40px auto;padding:0 24px}}h1{{font-size:34px}}h2{{margin-top:48px}}table{{border-collapse:collapse;background:white;width:100%;margin:20px 0}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #d9e0e5}}th{{background:#e6edf2}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#e6edf2;padding:20px}}svg{{width:100%;height:auto;background:white;margin:12px 0}}.notice{{background:#fff1ce;padding:20px;border-left:5px solid #aa6a00}}</style>
<h1>Video–FBX comparison</h1><p>{escape(report['performance_id'])} · {scope} · Original skeletons</p>
<div class="notice"><strong>{notice}</strong><p>{escape(report['interpretation'])}</p><p>Statistical equivalence not established. Tracking and reference landmarks have measurement uncertainty.</p></div>
<h2>Quality and review status: {report['qc']['status']}</h2><ul>{issues}</ul>{review_markup}
<h2>Skeleton geometry</h2><p>Native 3D segment lengths divided by shoulder width. These show differences between the exported skeletons; they do not measure accuracy. Position differences include skeleton proportions as well as movement and projection.</p><pre>{escape(json.dumps(report.get('skeleton_proportions', {}), indent=2))}</pre>
<h2>Timing diagnostics</h2><p>Timing status: {report['timing_status']}. The raw annotated durations below use each file's stored clock. Separate repetitions cannot be treated as synchronized observations of one performance.</p>
<pre>{escape(json.dumps({'durations_s':report['durations_s'],'native_duration_difference_vs_video_s':report['native_duration_difference_vs_video_s'],'clock_adjusted_duration_difference_vs_video_s':report['clock_adjusted_duration_difference_vs_video_s']},indent=2))}</pre>
<table><tr><th>Exploratory threshold</th><th>MotionCaptureFBX duration within</th><th>oldFBX duration within</th><th>Status</th></tr>{timing}</table>
{''.join(sections)}
<h2>Review notes and provenance</h2><p>MediaPipe landmarks are an estimated 2D reference. These results do not establish 3D accuracy, finger accuracy, or sign-language comprehension. Full configuration and hashes appear below and in summary.json.</p><pre>{escape(json.dumps(report['provenance'],indent=2))}</pre></html>"""
    (output / "report.html").write_text(html)
