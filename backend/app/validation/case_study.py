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


# Exploratory tolerance profiles retained for compatibility, not validated
# equivalence bounds or evidence of sign-language intelligibility.
EQUIVALENCE_MARGINS = {
    "path_movement": 0.05,      # reference shoulder widths
    "arm_posture": 10.0,        # degrees
    "palm_orientation": 15.0,   # degrees
    "handshape": 0.10,          # hand scale (proportion)
}
INTELLIGIBILITY_MARGINS = {
    "path_movement": 0.20,
    "arm_posture": 22.5,
    "palm_orientation": 45.0,
    "handshape": 0.25,
}
TOLERANCE_PROFILES = {
    "replication": {"margins": EQUIVALENCE_MARGINS, "statistic": "max"},
    "intelligibility": {"margins": INTELLIGIBILITY_MARGINS, "statistic": "p95"},
}
# Minimum fraction of valid (non-NaN) frames required to issue a verdict
MINIMUM_VALID_FRACTION = MIN_COVERAGE


def evaluate_functional_domain(error_curve, margin, domain_name, statistic="max", times=None):
    """Descriptive threshold check; missing required measurements stay missing."""
    error_curve = np.asarray(error_curve, dtype=float)
    valid = np.isfinite(error_curve)
    weights = np.ones(error_curve.size)
    if times is not None and len(times) > 1:
        times = np.asarray(times)
        if times.shape != error_curve.shape or np.any(np.diff(times) <= 0):
            raise ValidationError("Assessment timestamps must match the curve and increase.")
        boundaries = np.r_[times[0], (times[1:] + times[:-1]) / 2, times[-1]]
        weights = np.diff(boundaries)
    valid_fraction = float(weights[valid].sum() / weights.sum()) if valid.size else 0.0
    if valid_fraction < MINIMUM_VALID_FRACTION:
        return {
            "status": "INCONCLUSIVE",
            "reason": f"Only {valid_fraction:.0%} of assessed time has valid data (need ≥{MINIMUM_VALID_FRACTION:.0%})",
            "domain": domain_name,
            "margin": margin,
            "valid_fraction": valid_fraction,
            "statistic": statistic,
            "tested_deviation": None,
            "max_deviation": None,
            "mean_deviation": None,
            "median_deviation": None,
        }
    observed = error_curve[valid]
    max_dev = float(np.max(observed))
    if statistic not in ("max", "p95"):
        raise ValidationError("Statistic must be max or p95.")
    ordered = np.argsort(observed)
    cumulative = np.cumsum(weights[valid][ordered]) / weights[valid].sum()
    p95 = float(observed[ordered][np.searchsorted(cumulative, .95)])
    tested = max_dev if statistic == "max" else p95
    return {
        "status": "PASS" if tested < margin else "FAIL",
        "domain": domain_name,
        "margin": margin,
        "statistic": statistic,
        "tested_deviation": tested,
        "max_deviation": max_dev,
        "mean_deviation": float(np.average(observed, weights=weights[valid])),
        "median_deviation": float(np.median(observed)),
        "valid_fraction": valid_fraction,
    }


def intersection_union_decision(domain_results):
    """Combine observed checks without making a statistical equivalence claim."""
    statuses = [r["status"] for r in domain_results.values()]
    if not statuses or "INCONCLUSIVE" in statuses:
        return "INCONCLUSIVE"
    elif "FAIL" in statuses:
        return "OBSERVED TOLERANCE EXCEEDED"
    else:
        return "OBSERVED TOLERANCE SATISFIED"


def clip_level_certificate(label, pred_xy, ref_xy, pred_hands_2d=None, ref_hands_2d=None, profile="replication", times=None):
    """Evaluate all four projected movement domains for one capture system.

    Returns a Clip-Level Tolerance Certificate with per-domain verdicts
    and their descriptive combined assessment.
    """
    n_frames = len(pred_xy)

    # --- Domain 1: Path Movement (wrist + elbow position in shoulder widths) ---
    # TARGETS = (4, 5, 6, 7) → left_wrist, right_wrist, left_elbow, right_elbow
    path_errors = np.max(np.linalg.norm(
        pred_xy[:, TARGETS] - ref_xy[:, TARGETS], axis=2
    ), axis=1)

    # --- Domain 2: Arm Posture (elbow bend + upper/forearm direction) ---
    arm_angle_errors = _arm_posture_errors(pred_xy, ref_xy)

    # --- Domain 3: Palm Orientation (wrist-to-index direction) ---
    palm_angle_errors = (
        _palm_orientation_errors(pred_xy, ref_xy)
        if pred_xy.shape[1] >= 10 and ref_xy.shape[1] >= 10
        else np.full(n_frames, np.nan)
    )

    # --- Domain 4: Handshape (finger positions if available) ---
    hand_errors = _handshape_errors(pred_hands_2d, ref_hands_2d) if (
        pred_hands_2d is not None and ref_hands_2d is not None
    ) else np.full(n_frames, np.nan)

    if profile not in TOLERANCE_PROFILES:
        raise ValidationError("Tolerance profile must be replication or intelligibility.")
    margins = TOLERANCE_PROFILES[profile]["margins"]
    statistic = TOLERANCE_PROFILES[profile]["statistic"]
    curves = {
        "path_movement": (path_errors, "Hand Location (Path)"),
        "arm_posture": (arm_angle_errors, "Arm Posture (Kinematics)"),
        "palm_orientation": (palm_angle_errors, "Projected wrist-to-index direction"),
        "handshape": (hand_errors, "Handshape (Fingers)"),
    }
    domains = {
        key: evaluate_functional_domain(curve, margins[key], name, statistic, times)
        for key, (curve, name) in curves.items()
    }
    decision = intersection_union_decision(domains)
    return {
        "label": label,
        "decision": decision,
        "required_joint_coverage": {
            CASE_JOINTS[j]: float(np.isfinite(pred_xy[:, j] - ref_xy[:, j]).all(axis=1).mean())
            for j in range(min(pred_xy.shape[1], len(CASE_JOINTS)))
        },
        "hand_coverage": {
            side: float(np.isfinite(pred_hands_2d[:, i] - ref_hands_2d[:, i]).all(axis=(1, 2)).mean())
            if pred_hands_2d is not None and ref_hands_2d is not None else 0.0
            for i, side in enumerate(("left", "right"))
        },
        "domains": domains,
        "margins": margins,
        "tolerance_profile": profile,
        "statistic": statistic,
        "assessment_kind": "observed_tolerance",
        "margin_status": "exploratory",
        "statistical_equivalence": {"status": "not_established", "reasons": [
            "Measurement uncertainty has not been independently calibrated.",
            "Tolerance margins lack validated movement-fidelity justification.",
            "A single projected recording cannot establish full 3D equivalence.",
        ]},
    }


# Heuristic visibility mask based on projected segment length. It is not a
# calibrated estimate of out-of-plane angle or measurement uncertainty.
MIN_FORESHORTENING = 0.40


def _in_plane(segment):
    """Frames whose projected length is a usable fraction of the clip's in-plane length."""
    length = np.linalg.norm(segment, axis=1)
    finite = np.isfinite(length)
    if not finite.any():
        return np.zeros(len(segment), dtype=bool)
    full = np.percentile(length[finite], 95)
    with np.errstate(invalid="ignore"):
        return finite & (length >= MIN_FORESHORTENING * full) & (length > 1e-8)


def _direction_errors(p, r):
    """Projected angle between two segments; foreshortened frames are missing."""
    valid = _in_plane(p) & _in_plane(r)
    pn = np.linalg.norm(p, axis=1)
    rn = np.linalg.norm(r, axis=1)
    dot = np.divide(np.sum(p * r, axis=1), pn * rn,
                    out=np.full(len(p), np.nan), where=valid)
    ang = np.degrees(np.arccos(np.clip(dot, -1.0, 1.0)))
    ang[~valid] = np.nan
    return ang


def _nanmax_rows(values):
    """Maximum requiring every component; a hidden side cannot pass via the other side."""
    result = np.full(len(values), np.nan)
    measured = np.isfinite(values).all(axis=1)
    result[measured] = np.max(values[measured], axis=1)
    return result


def _arm_posture_errors(pred_xy, ref_xy):
    """Per-frame max angular error across elbow bend + upper/forearm direction."""
    # Upper arm and forearm directional errors
    segments_pred = [
        pred_xy[:, 6] - pred_xy[:, 0],  # L upper arm
        pred_xy[:, 7] - pred_xy[:, 1],  # R upper arm
        pred_xy[:, 4] - pred_xy[:, 6],  # L forearm
        pred_xy[:, 5] - pred_xy[:, 7],  # R forearm
    ]
    segments_ref = [
        ref_xy[:, 6] - ref_xy[:, 0],
        ref_xy[:, 7] - ref_xy[:, 1],
        ref_xy[:, 4] - ref_xy[:, 6],
        ref_xy[:, 5] - ref_xy[:, 7],
    ]
    dir_errs = [_direction_errors(p, r) for p, r in zip(segments_pred, segments_ref)]

    # A projected elbow angle is only defined when both of its segments are in plane.
    elbow_err = np.abs(elbow_angles(pred_xy) - elbow_angles(ref_xy))  # (n, 2)
    for side in range(2):
        visible = np.isfinite(dir_errs[side]) & np.isfinite(dir_errs[side + 2])
        elbow_err[~visible, side] = np.nan

    # Stack: (n, 6); a frame needs both elbows and all four segment directions.
    return _nanmax_rows(np.column_stack([elbow_err] + dir_errs))


def _palm_orientation_errors(pred_xy, ref_xy):
    """Per-frame max angular error of the wrist-to-index-knuckle vector."""
    palm_errs = [
        _direction_errors(
            pred_xy[:, index_idx] - pred_xy[:, wrist_idx],
            ref_xy[:, index_idx] - ref_xy[:, wrist_idx],
        )
        for wrist_idx, index_idx in ((4, 8), (5, 9))
    ]
    return _nanmax_rows(np.column_stack(palm_errs))


def _handshape_errors(pred_hands_2d, ref_hands_2d):
    """Per-frame max Euclidean distance across all projected finger joints."""
    # pred_hands_2d / ref_hands_2d: (frames, 2, 21, 2) — 2 sides × 21 joints × xy
    if pred_hands_2d is None or ref_hands_2d is None:
        return np.full(pred_hands_2d.shape[0] if pred_hands_2d is not None else 1, np.nan)
    # Remove wrist placement and normalize each hand by its clip-level
    # wrist-to-middle-MCP length: the 0.10 margin is a proportion of hand scale.
    # A per-frame projected length collapses when the palm turns edge-on and
    # would inflate every finger offset by the foreshortening factor.
    normalized = []
    for hands in (pred_hands_2d, ref_hands_2d):
        local = hands - hands[:, :, :1]
        lengths = np.linalg.norm(local[:, :, 9], axis=2)
        scale = np.full(2, np.nan)
        for side in range(2):
            finite = lengths[np.isfinite(lengths[:, side]), side]
            if finite.size and np.percentile(finite, 95) > 1e-8:
                scale[side] = np.percentile(finite, 95)
        normalized.append(local / scale[None, :, None, None])
    diff = np.linalg.norm(normalized[0] - normalized[1], axis=3)
    # A missing finger must not disappear from a strict handshape comparison.
    return np.max(diff.reshape(diff.shape[0], 42), axis=1)

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



def primary_camera_fits(xyz, reference, calibration_mask, reference_view="automatic"):
    """Apply the declared camera view without fitting the evaluated arm motion."""
    if reference_view == "automatic":
        fits = camera_fits(xyz, reference, calibration_mask)
        if not _mirrored_yaw(fits):
            return fits
        # Shoulders and hips are nearly coplanar, so an orthographic torso fit
        # cannot tell a left turn from a right turn; the equally good ±yaw pair
        # only absorbs skeleton-proportion differences. Use the upright frontal
        # view rather than an arbitrary member of the pair.
        status = "automatic_yaw_unidentifiable_front_view"
    elif reference_view == "front":
        status = "user_declared_front_view"
    else:
        raise ValidationError("Reference view must be automatic or front.")
    alternatives = fits if reference_view == "automatic" else []
    fit = frontal_camera_fit(xyz, reference, calibration_mask)
    fit["status"] = status
    fit["orientation_policy"] = "Fixed upright frontal camera from anatomical shoulders and world up; no arm or finger fitting."
    valid = calibration_mask & np.isfinite(reference[:, :4]).all(axis=(1, 2))
    residual = project(xyz, fit)[valid, :4] - reference[valid, :4]
    fit["torso_rmse"] = float(np.sqrt(np.mean(residual**2))) if valid.any() else None
    return [fit, *alternatives]


MIRRORED_YAW_DEG = 10.0


def _mirrored_yaw(fits):
    """True when accepted torso fits turn the body materially left and right."""
    yaws = []
    for fit in fits:
        depth = Rotation.from_rotvec(fit["rotation_vector_rad"]).as_matrix()[2]
        yaws.append(np.degrees(np.arctan2(depth[0], abs(depth[2]))))
    return min(yaws) < -MIRRORED_YAW_DEG and max(yaws) > MIRRORED_YAW_DEG


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
        dot = np.divide(np.sum(p * r, axis=1), pn * rn,
                        out=np.full(len(p), np.nan), where=valid)
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
    # Union of source clocks keeps every native video and FBX sample, including
    # short spikes missed by a fixed 101-point phase grid. Other streams are
    # interpolated only under their existing coverage and maximum-gap rules.
    start, end = trial.windows["video"]
    clocks = [np.array([start, end]), pose.times[(pose.times >= start) & (pose.times <= end)]]
    for label, motion in motions.items():
        lo, hi = trial.windows[label]
        native = motion.times[(motion.times >= lo) & (motion.times <= hi)]
        if mode == "synchronized":
            sync = config.get("synchronization", {}).get(label, {})
            if sync_queries(np.array([start]), config.get("synchronization", {}), label) is None:
                return {"status": "indeterminate", "reason": "Source clocks and synchronization events are not verified."}, None
            event = sync["event"]
            clock = event["video_seconds"] + (native - event["fbx_seconds"]) * sync.get("video_seconds_per_fbx_second", 1.0)
        else:
            clock = start + (native - lo) / (hi - lo) * (end - start)
        clocks.append(clock[(clock >= start) & (clock <= end)])
    video_queries = np.unique(np.round(np.concatenate(clocks), 12))
    phase = (video_queries - start) / (end - start)
    if video_queries[-1] > pose.times[-1] + 1e-7:
        raise ValidationError("Video window exceeds the reference landmark clock.")
    motion_queries = {}
    temporal_common = np.ones(len(phase), dtype=bool)
    for label in motions:
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
    xyz_for_camera, hands_for_camera = {}, {}
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

        xyz_for_camera[label] = xyz
        solutions = primary_camera_fits(xyz, reference, calibration_mask, config.get("reference_view", "automatic"))
        for fit in solutions:
            fit["metrics"] = measure(reference, project(xyz, fit), valid)
            fit["mean_target_error"] = fit["metrics"]["combined_position"]["mean"]
        predictions[label] = project(xyz, solutions[0])

        if video_hands is not None:
            raw_hands = sample_motion_hands(motion, queries)
            norm_hands = (raw_hands - center[:, None, None, :]) / shoulder_m
            flat_hands = norm_hands.reshape(len(queries), 42, 3)
            hands_for_camera[label] = flat_hands
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
    ambiguity = any(
        bounds[1] - bounds[0] > AMBIGUITY_SPREAD for bounds in ranges.values()
    )
    delta_range, comparison = None, None
    if "non_suit" in motions:
        delta_range = [
            ranges["non_suit"][0] - ranges["suit"][1],
            ranges["non_suit"][1] - ranges["suit"][0],
        ]
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
    if comparison is None:
        comparison = {}
    try:
        # Prepare hand projections for the equivalence engine
        suit_hands_2d, non_suit_hands_2d = None, None
        ref_hands_2d = None
        if video_hands is not None:
            raw_ref_hands = sample_video_hands(pose.times, video_hands, video_queries)
            ref_pixels = raw_reference * [metadata["width"], metadata["height"]]
            ref_centers = ref_pixels[:, :2].mean(axis=1)
            ref_hands_2d = (
                raw_ref_hands * [metadata["width"], metadata["height"]]
                - ref_centers[:, None, None, :]
            ) / shoulder_px
            suit_hands_2d = predictions.get("hands", {}).get("suit")
            non_suit_hands_2d = predictions.get("hands", {}).get("non_suit")

        # --- Clip-Level Tolerance Certificates ---
        comparison["equivalence"] = {}
        for label in motions:
            pred = predictions[label].copy()
            pred[~valid] = np.nan
            ref = reference.copy()
            ref[~valid] = np.nan
            pred_h = suit_hands_2d.copy() if label == "suit" and suit_hands_2d is not None else (
                non_suit_hands_2d.copy() if label == "non_suit" and non_suit_hands_2d is not None else None
            )
            ref_h = ref_hands_2d.copy() if ref_hands_2d is not None else None
            if pred_h is not None:
                pred_h[~valid] = np.nan
            if ref_h is not None:
                ref_h[~valid] = np.nan
            profiles = {profile: clip_level_certificate(
                LABELS[label], pred, ref, pred_h, ref_h, profile, video_queries,
            ) for profile in TOLERANCE_PROFILES}
            comparison["equivalence"][label] = dict(profiles[config.get("tolerance_profile", "replication")])
            comparison["equivalence"][label]["profile_sensitivity"] = profiles
            cameras = []
            for fit in fits[label]["solutions"]:
                alt_pred = project(xyz_for_camera[label], fit)
                alt_pred[~valid] = np.nan
                alt_hands = None
                if label in hands_for_camera:
                    alt_hands = project(hands_for_camera[label], fit).reshape(len(video_queries), 2, 21, 2)
                    alt_hands[~valid] = np.nan
                cameras.append(clip_level_certificate(LABELS[label], alt_pred, ref, alt_hands, ref_h,
                    config.get("tolerance_profile", "replication"), video_queries))
            comparison["equivalence"][label]["camera_sensitivity"] = {
                "interpretation": "Admitted torso fits only; not confidence intervals. No fit selected by target error.",
                "decisions": [c["decision"] for c in cameras],
                "domain_ranges": {key: [min(values), max(values)] if values else None
                    for key in EQUIVALENCE_MARGINS
                    for values in [[c["domains"][key]["tested_deviation"] for c in cameras
                                    if c["domains"][key]["tested_deviation"] is not None]]},
            }
    except Exception as e:
        comparison["equivalence"] = {"error": str(e)}
    sensitivity = []
    for tolerance in POSITION_TOLERANCES:
        entry = {"tolerance_shoulder_widths": tolerance}
        for label in motions:
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
        label: elbow_angles(predictions[label]) for label in motions
    }
    for i, p in enumerate(phase):
        row = {
            "phase": float(p),
            "video_time_s": float(video_queries[i]),
            "valid": int(valid[i]),
        }
        for label in motions:
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
            for label in motions:
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
        "sampling_policy": "union_of_native_source_clocks",
        "n_assessed_samples": len(video_queries),
        "synchronization_evidence": "declared_or_estimated_not_independently_validated" if mode == "synchronized" else "phase_normalized_no_timing_agreement",
        "reference_view": config.get("reference_view", "automatic"),
        "tolerance_profile": config.get("tolerance_profile", "replication"),
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
            "ranking_changes": bool(delta_range[0] < 0 < delta_range[1]) if delta_range is not None else False,
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
    if metadata.get("pose_model") != "rtmlib_dwpose_wholebody":
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
    if metadata.get("upper_body") and not upper_npz.is_file():
        raise ValidationError("Upper-body reference file is missing.")
    if upper_npz.exists():
        upper_info = metadata.get("upper_body", {})
        if upper_info.get("file") != upper_npz.name or sha256(upper_npz) != upper_info.get("sha256"):
            raise ValidationError("Upper-body reference file hash does not match.")
        with np.load(upper_npz, allow_pickle=False) as data:
            video_hands = data["hands"].copy()
            if (video_hands.shape != (len(pose.times), 2, 21, 2)
                or data["times"].shape != pose.times.shape
                or not np.allclose(data["times"], pose.times, rtol=0, atol=1e-7)):
                raise ValidationError("Hand landmarks must match the video frame clock and contain 21 joints per hand.")

    motions = {"suit": load_motion(trial.suit_fbx, include_elbows=True, include_extras=True)}
    if trial.non_suit_fbx is not None:
        motions["non_suit"] = load_motion(trial.non_suit_fbx, include_elbows=True, include_extras=True)
    durations = {
        label: float(end - start) for label, (start, end) in trial.windows.items()
    }
    qc = ["Synchronization is declared or estimated; its uncertainty is not independently validated. Both tolerance profiles are exploratory."]
    if not matched:
        qc.append(
            "Recording correspondence: separate or unverified performances. Position and angle differences combine performance variation, skeleton geometry, tracking, and projection. They cannot establish capture accuracy or superiority."
        )
    proportions = {
        label: skeleton_proportions(motion) for label, motion in motions.items()
    }
    ratios = [
        proportions[label]["lengths_per_shoulder_width"]["left_upper_arm"]
        for label in motions
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
    alignment_sensitivity = {"status": "unavailable", "interpretation": "No usable synchronized assessment."}
    if results["synchronized"]["status"] == "descriptive":
        step = float(np.median(np.diff(pose.times)))
        scenarios = []
        for offset in (-step, 0.0, step):
            if offset == 0:
                assessment = results["synchronized"]
            else:
                alternative = json.loads(json.dumps(config))
                for sync in alternative.get("synchronization", {}).values():
                    if sync.get("event"):
                        sync["event"]["video_seconds"] += offset
                try:
                    assessment, _ = score_mode(trial, pose, video_hands, motions, metadata, alternative, "synchronized")
                except ValidationError as exc:
                    assessment = {"status": "indeterminate", "reason": str(exc)}
            scenarios.append({"video_event_offset_s": offset, "status": assessment["status"],
                "reason": assessment.get("reason"), "certificates": assessment.get("comparison", {}).get("equivalence", {})})
        alignment_sensitivity = {"status": "descriptive", "scenarios": scenarios,
            "interpretation": "Declared alignment plus/minus one native reference-frame interval. Resolution diagnostic only, not a calibrated uncertainty bound or independently verified timing. No scenario is chosen by target error."}
    timing_sensitivity = []
    synchronized = results["synchronized"]["status"] == "descriptive"
    adjusted_duration = {}
    if synchronized:
        for label in motions:
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
                    for label in motions
                },
                "status": ("descriptive" if synchronized else "indeterminate")
                if matched
                else "not_applicable",
            }
        )
    report = {
        "analysis_version": "video-fbx-case-v5-observed-agreement",
        "assessment_kind": "observed_tolerance",
        "reference_uncertainty": "unvalidated; legacy hand sidecars have no per-point confidence",
        "statistical_equivalence": {"status": "not_established", "reasons": [
            "No independently validated landmark, camera, or timing uncertainty model.",
            "Both tolerance profiles are exploratory, not justified equivalence margins.",
            "Measurements cover observable projected movement in one recording only.",
        ]},
        "primary_analysis": "synchronized" if synchronized else "phase_normalized",
        "reference_view": config.get("reference_view", "automatic"),
        "tolerance_profile": config.get("tolerance_profile", "replication"),
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
                    if key in source["trials"][0]
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
            label: durations[label] - durations["video"] for label in motions
        },
        "timing_status": ("descriptive" if synchronized else "indeterminate")
        if matched
        else "not_applicable",
        "clock_adjusted_duration_difference_vs_video_s": adjusted_duration or None,
        "timing_tolerance_sensitivity": timing_sensitivity,
        "analyses": results,
        "alignment_sensitivity": alignment_sensitivity,
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
    overlay_mode = report["primary_analysis"]
    if overlay_mode in artifacts:
        review_markup += comparison_overlay(
            trial, pose, report, artifacts[overlay_mode], output
        )
        report["artifacts"]["comparison_overlay"] = "comparison_overlay.png"
        try:
            if full_sequence_overlay(trial, pose, motions, report, output, video_hands):
                report["artifacts"]["full_sequence_overlay"] = "full_sequence_overlay.mp4"
                review_markup += '<p>Full sequence review: <a href="full_sequence_overlay.mp4">full_sequence_overlay.mp4</a> (local companion file). Points follow stored source timestamps; playback uses the nominal reference frame rate.</p>'
        except (ValidationError, KeyError) as exc:
            report["qc"]["issues"].append(f"Full-sequence overlay unavailable: {exc}")
            report["qc"]["status"] = "provisional"
    render_report(report, artifacts, output, review_markup)
    report["artifacts"]["figures"] = [p.name for p in sorted(output.glob("*.svg"))]
    (output / "summary.json").write_text(
        json.dumps(_safe(report), indent=2, allow_nan=False) + "\n"
    )
    return report


def full_sequence_overlay(trial, pose, motions, report, output, video_hands):
    """Sequentially decode all frames and draw both reference and FBX body/hands."""
    import cv2
    mode = report["primary_analysis"]
    result = report["analyses"][mode]
    metadata = report["provenance"]["video"]
    config = report["provenance"]["configuration"]
    capture = cv2.VideoCapture(str(trial.reference_video))
    writer = None
    destination = output / "full_sequence_overlay.mp4"
    edges = ((0, 1), (0, 2), (1, 3), (0, 6), (6, 4), (1, 7), (7, 5), (4, 8), (5, 9))
    count = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if count >= len(pose.times):
                raise ValidationError("Overlay frame count exceeds stored reference clock.")
            time = pose.times[count]
            reference = pose.xy[count] * [metadata["width"], metadata["height"]]
            center = reference[:2].mean(axis=0)
            tracks = [(reference, (80, 230, 80))]
            hands = []
            if video_hands is not None:
                hands.append((video_hands[count] * [metadata["width"], metadata["height"]], (80, 230, 80)))
            if trial.windows["video"][0] <= time <= trial.windows["video"][1] and np.isfinite(center).all():
                for label, motion in motions.items():
                    if mode == "synchronized":
                        queries = sync_queries(np.array([time]), config.get("synchronization", {}), label)
                    else:
                        phase = (time - trial.windows["video"][0]) / np.diff(trial.windows["video"])[0]
                        queries = np.array([trial.windows[label][0] + phase * np.diff(trial.windows[label])[0]])
                    if queries is None or not trial.windows[label][0] <= queries[0] <= trial.windows[label][1]:
                        continue
                    xyz = sample_motion(motion, queries)
                    origin = xyz[:, :2].mean(axis=1)
                    calibration = result["calibration"][label]
                    scale = calibration["source_shoulder_width_m"]
                    fit = calibration["solutions"][0]
                    pixels = result["reference_shoulder_width_pixels"]
                    color = (240, 180, 0) if label == "suit" else (0, 140, 250)
                    tracks.append((project((xyz - origin[:, None]) / scale, fit)[0] * pixels + center, color))
                    joints = sample_motion_hands(motion, queries)
                    projected = project(((joints - origin[:, None, None]) / scale).reshape(1, 42, 3), fit)
                    hands.append((projected.reshape(2, 21, 2) * pixels + center, color))
            for xy, color in tracks:
                for a, b in edges:
                    if max(a, b) < len(xy) and np.isfinite(xy[[a, b]]).all():
                        cv2.line(frame, tuple(np.round(xy[a]).astype(int)), tuple(np.round(xy[b]).astype(int)), color, 5)
            for points, color in hands:
                for hand in points:
                    for finger in range(5):
                        chain = [0, *range(1 + 4 * finger, 5 + 4 * finger)]
                        for a, b in zip(chain, chain[1:]):
                            if np.isfinite(hand[[a, b]]).all():
                                cv2.line(frame, tuple(np.round(hand[a]).astype(int)), tuple(np.round(hand[b]).astype(int)), color, 3)
            ratio = min(1.0, 960 / max(frame.shape[:2]))
            size = tuple(max(2, int(d * ratio) // 2 * 2) for d in (frame.shape[1], frame.shape[0]))
            frame = cv2.resize(frame, size)
            cv2.putText(frame, f"{time:.3f}s | green: video, blue: Rokoko | {mode}", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, .42, (255, 255, 255), 1)
            if writer is None:
                writer = cv2.VideoWriter(str(destination), cv2.VideoWriter_fourcc(*"avc1"), metadata["frame_rate"], size)
                if not writer.isOpened():
                    raise ValidationError("H.264 full-sequence overlay encoder unavailable.")
            writer.write(frame)
            count += 1
        if count != len(pose.times):
            raise ValidationError("Overlay frame count differs from stored reference clock.")
    finally:
        capture.release()
        if writer is not None:
            writer.release()
    return count > 0


def comparison_overlay(trial, pose, report, artifact, output):
    """Show the scored projections over the actual decoded reference video."""
    import cv2
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows, reference, predictions, valid = artifact
    width = report["provenance"]["video"]["width"]
    height = report["provenance"]["video"]["height"]
    shoulder = report["analyses"][report.get("primary_analysis", "phase_normalized")]["reference_shoulder_width_pixels"]
    sample_ids = np.linspace(0, len(rows) - 1, 5).round().astype(int)
    times = np.array([rows[i]["video_time_s"] for i in sample_ids])
    observed = sample_video(pose, times) * [width, height]
    centers = observed[:, :2].mean(axis=1)
    capture = cv2.VideoCapture(str(trial.reference_video))
    edges = ((0, 1), (0, 2), (1, 3), (2, 3), (0, 6), (6, 4), (1, 7), (7, 5))
    overlay_sources = [("Video landmarks", reference, "#69e851")]
    overlay_sources += [
        (LABELS[label], predictions[label], color)
        for label, color in (("suit", "#00b5f7"), ("non_suit", "#ff9400"))
        if label in predictions
    ]
    fig, axes = plt.subplots(len(overlay_sources), 5, figsize=(15, 5 * len(overlay_sources)), squeeze=False)
    try:
        for col, i in enumerate(sample_ids):
            capture.set(cv2.CAP_PROP_POS_MSEC, times[col] * 1000)
            ok, frame = capture.read()
            if not ok:
                raise ValidationError("Cannot decode comparison overlay frame.")
            for row, (label, points, color) in enumerate(overlay_sources):
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
        motions = result["methods"]
        method_headers = "".join(f"<th>{LABELS[label]}</th>" for label in motions)
        rows = []
        for j in TARGETS:
            name = CASE_JOINTS[j]
            for label in motions:
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
            for name, values in result["comparison"].get("position", {}).items()
        )
        certificate_html = "<h3>Observed tolerance checks</h3><p>Both profiles are exploratory. PASS means an observed threshold was satisfied, not statistical equivalence or intelligibility. All required sides and joints need at least 80% complete coverage.</p>"
        for label, certificate in result["comparison"].get("equivalence", {}).items():
            if label == "error":
                certificate_html += f"<p>{escape(str(certificate))}</p>"
                continue
            certificate_html += f"<h4>{LABELS[label]}: {escape(certificate['decision'])}</h4>"
            certificate_html += "<table><tr><th>Domain</th><th>Margin</th><th>Tested deviation</th><th>Coverage</th><th>Status</th></tr>"
            for domain in certificate["domains"].values():
                certificate_html += f"<tr><td>{escape(domain['domain'])}</td><td>{fmt(domain['margin'])}</td><td>{fmt(domain.get('tested_deviation', domain['max_deviation']))}</td><td>{domain['valid_fraction']:.1%}</td><td>{domain['status']}</td></tr>"
            certificate_html += "</table><details><summary>Both exploratory profiles</summary><pre>" + escape(json.dumps(certificate.get("profile_sensitivity", {}), indent=2)) + "</pre></details>"
        tolerances = "".join(
            f"<tr><td>{row['tolerance_shoulder_widths']}</td>"
            + "".join(f"<td>{row[label]['fraction_frames_all_targets_within']:.1%}</td>" for label in motions)
            + "</tr>"
            for row in result["position_tolerance_sensitivity"]
        )
        angle_rows = "".join(
            f"<tr><td>{side}</td><td>{LABELS[label]}</td><td>{fmt(metric['mean'])}</td><td>{fmt(metric['median'])}</td><td>{fmt(metric['p95'])}</td></tr>"
            for label in motions
            for side, metric in result["methods"][label]["elbow_angle"].items()
        )
        frontal = result["frontal_camera_diagnostic"]
        frontal_rows = "".join(
            f"<tr><td>{LABELS[label]}</td><td>{fmt(item.get('metrics', {}).get('combined_position', {}).get('mean'))}</td></tr>"
            for label, item in frontal["methods"].items()
        )
        sections.append(
            f"<h2>{title}</h2><p>Reference view: {escape(result.get('reference_view', 'automatic'))}. Common coverage: {result['common_coverage']:.1%}. Position is measured relative to the shoulder centre in reference shoulder widths; angles are projected 2D angles. Phase normalization removes speed differences from the shape score.</p>"
            + "<table><tr><th>Joint</th><th>Method</th><th>Mean</th><th>Median</th><th>P95</th><th>Signed x bias</th><th>Signed y bias</th></tr>"
            + "".join(rows)
            + "</table>"
            + f"<h3>Difference between methods</h3><p>Positive values mean MotionCaptureFBX is closer to this video under the displayed alignment and camera fit. Percentage reduction uses oldFBX {metric_word} as its denominator. This alone does not establish capture accuracy.</p><table><tr><th>Joint</th><th>Old − MotionCapture</th><th>Reduction</th></tr>"
            + comparisons
            + "</table>"
            + certificate_html
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
            + f"<h3>Exploratory tolerance sensitivity</h3><p>Fraction of valid frames with all four target joints within each threshold. These thresholds are illustrative and do not establish equivalence.</p><table><tr><th>Shoulder-width threshold</th>{method_headers}</tr>"
            + tolerances
            + "</table>"
            + plots(mode, artifacts[mode], output, metric_word)
        )
    issues = "".join(f"<li>{escape(issue)}</li>" for issue in report["qc"]["issues"])
    timing = "".join(
        f"<tr><td>{row['tolerance_ms']} ms</td><td>{escape(str(row['duration_discrepancy_within']['suit']))}</td><td>{escape(str(row['duration_discrepancy_within'].get('non_suit', 'Not uploaded')))}</td><td>{row['status']}</td></tr>"
        for row in report["timing_tolerance_sensitivity"]
    )
    html = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Video–FBX comparison: {escape(report['performance_id'])}</title><style>body{{font:16px system-ui,sans-serif;background:#f6f8fa;color:#172531;max-width:1120px;margin:40px auto;padding:0 24px}}h1{{font-size:34px}}h2{{margin-top:48px}}table{{border-collapse:collapse;background:white;width:100%;margin:20px 0}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #d9e0e5}}th{{background:#e6edf2}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#e6edf2;padding:20px}}svg{{width:100%;height:auto;background:white;margin:12px 0}}.notice{{background:#fff1ce;padding:20px;border-left:5px solid #aa6a00}}</style>
<h1>Video–FBX comparison</h1><p>{escape(report['performance_id'])} · {scope} · Original skeletons</p>
<div class="notice"><strong>{notice}</strong><p>{escape(report['interpretation'])}</p><p>Statistical equivalence not established. Tracking and reference landmarks have measurement uncertainty.</p></div>
<h2>Quality and review status: {report['qc']['status']}</h2><ul>{issues}</ul>{review_markup}
<h2>Skeleton geometry</h2><p>Native 3D segment lengths divided by shoulder width. These show differences between the exported skeletons; they do not measure accuracy. Position differences include skeleton proportions as well as movement and projection.</p><pre>{escape(json.dumps(report.get('skeleton_proportions', {}), indent=2))}</pre>
<h2>Alignment resolution sensitivity</h2><pre>{escape(json.dumps(report.get('alignment_sensitivity', {}), indent=2))}</pre>
<h2>Timing diagnostics</h2><p>Timing status: {report['timing_status']}. The raw annotated durations below use each file's stored clock. Separate repetitions cannot be treated as synchronized observations of one performance.</p>
<pre>{escape(json.dumps({'durations_s':report['durations_s'],'native_duration_difference_vs_video_s':report['native_duration_difference_vs_video_s'],'clock_adjusted_duration_difference_vs_video_s':report['clock_adjusted_duration_difference_vs_video_s']},indent=2))}</pre>
<table><tr><th>Exploratory threshold</th><th>MotionCaptureFBX duration within</th><th>oldFBX duration within</th><th>Status</th></tr>{timing}</table>
{''.join(sections)}
<h2>Review notes and provenance</h2><p>Video landmarks are an estimated 2D reference. These results do not establish 3D accuracy, finger accuracy, or sign-language comprehension. Full configuration and hashes appear below and in summary.json.</p><pre>{escape(json.dumps(report['provenance'],indent=2))}</pre></html>"""
    (output / "report.html").write_text(html)
