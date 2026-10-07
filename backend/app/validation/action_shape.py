"""Exploratory upper-body shape diagnostics with one bounded warp per method.

No timing-accuracy, anatomical 3D, or linguistic correctness claims. Camera fits
are inherited from torso calibration and never chosen using target residuals.
"""

from __future__ import annotations

import csv
from html import escape
from pathlib import Path

import numpy as np

from .mixed_effects import ValidationError
from .trials import sha256

METHODS = ("suit", "non_suit")
BODY_NAMES = (
    "Shoulder tilt",
    "Torso lean",
    "Left upper arm",
    "Right upper arm",
    "Left forearm",
    "Right forearm",
    "Left elbow bend",
    "Right elbow bend",
)
BAND = 0.10
MIN_COVERAGE = 0.80


def heading(vector):
    angle = np.degrees(np.arctan2(vector[..., 1], vector[..., 0]))
    return np.where(np.linalg.norm(vector, axis=-1) > 1e-6, angle, np.nan)


def circular_difference(a, b):
    return np.abs((a - b + 180) % 360 - 180)


def bend(a, b, c):
    x, y = a - b, c - b
    norm = np.linalg.norm(x, axis=-1) * np.linalg.norm(y, axis=-1)
    cosine = np.sum(x * y, axis=-1) / np.maximum(norm, 1e-12)
    return np.where(norm > 1e-8, np.degrees(np.arccos(np.clip(cosine, -1, 1))), np.nan)


def body_features(points):
    centre = points[:, :2].mean(axis=1)
    hips = points[:, 2:4].mean(axis=1)
    vectors = [
        points[:, 0] - points[:, 1],
        centre - hips,
        points[:, 6] - points[:, 0],
        points[:, 7] - points[:, 1],
        points[:, 4] - points[:, 6],
        points[:, 5] - points[:, 7],
    ]
    result = np.column_stack(
        [
            *(heading(v) for v in vectors),
            bend(points[:, 0], points[:, 6], points[:, 4]),
            bend(points[:, 1], points[:, 7], points[:, 5]),
        ]
    )
    lengths = np.column_stack([np.linalg.norm(v, axis=1) for v in vectors])
    result[:, :6][lengths < 0.05] = np.nan
    result[(lengths[:, 2] < 0.05) | (lengths[:, 4] < 0.05), 6] = np.nan
    result[(lengths[:, 3] < 0.05) | (lengths[:, 5] < 0.05), 7] = np.nan
    return result


def bounded_path(reference, prediction, band=BAND):
    """Monotone DTW; slopes 1, 1/2, 2; all frames included in expanded path.

    Each method uses ONE path for every region. Cost is four equally weighted
    arm-segment angular residuals. Missing reference frames cost 180 degrees;
    they are never counted as observations in the reported scores.
    """
    n, m = len(reference), len(prediction)
    cost = np.mean(
        circular_difference(reference[:, None, 2:6], prediction[None, :, 2:6]), axis=2
    )
    cost = np.where(np.isfinite(cost), cost, 180.0)
    allowed = (
        np.abs(np.linspace(0, 1, n)[:, None] - np.linspace(0, 1, m)[None, :])
        <= band + 1e-9
    )
    cost[~allowed] = np.inf
    distance = np.full((n, m), np.inf)
    previous = np.zeros((n, m), dtype=np.int8)
    distance[0, 0] = cost[0, 0]
    for i in range(n):
        for j in range(m):
            if (i == 0 and j == 0) or not allowed[i, j]:
                continue
            choices = []
            if i >= 1 and j >= 1:
                choices.append((distance[i - 1, j - 1] + cost[i, j], 1))
            if i >= 1 and j >= 2:
                choices.append(
                    (distance[i - 1, j - 2] + cost[i, j - 1] + cost[i, j], 2)
                )
            if i >= 2 and j >= 1:
                choices.append(
                    (distance[i - 2, j - 1] + cost[i - 1, j] + cost[i, j], 3)
                )
            if choices:
                distance[i, j], previous[i, j] = min(choices)
    if not np.isfinite(distance[-1, -1]):
        raise ValidationError("No admissible bounded action alignment.")
    i, j = n - 1, m - 1
    path = [(i, j)]
    while i or j:
        step = previous[i, j]
        if step == 1:
            i, j = i - 1, j - 1
        elif step == 2:
            path.append((i, j - 1))
            i, j = i - 1, j - 2
        elif step == 3:
            path.append((i - 1, j))
            i, j = i - 2, j - 1
        else:
            raise ValidationError("Broken action alignment path.")
        path.append((i, j))
    return np.array(path[::-1])


def per_reference_errors(reference, prediction, path):
    errors = np.full(reference.shape, np.nan)
    for i in range(len(reference)):
        matches = prediction[path[path[:, 0] == i, 1]]
        if len(matches):
            values = circular_difference(reference[i], matches)
            # A missing match is not silently dropped from an average.
            errors[i] = np.mean(values, axis=0)
    return errors


def summary(values):
    values = np.asarray(values)
    values = values[np.isfinite(values)]
    return (
        {
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "p95": float(np.percentile(values, 95)),
        }
        if len(values)
        else {"mean": None, "median": None, "p95": None}
    )


def hand_features(points):
    result, names = [], []
    for finger_index, finger in enumerate(
        ("thumb", "index", "middle", "ring", "pinky")
    ):
        base = 1 + 4 * finger_index
        chain = [0, *range(base, base + 4)]
        for joint in range(1, 4):
            result.append(
                bend(
                    points[:, chain[joint - 1]],
                    points[:, chain[joint]],
                    points[:, chain[joint + 1]],
                )
            )
            names.append(f"{finger} bend {joint}")
    result.extend(
        (
            heading(points[:, 9] - points[:, 0]),
            bend(points[:, 5], points[:, 0], points[:, 17]),
        )
    )
    names.extend(("palm direction", "palm spread"))
    return np.column_stack(result), names


def interpolate_extra(times, points, queries, max_gap=0.15):
    # Preserve missing observations; never bridge low-quality gaps.
    result = np.full((len(queries), *points.shape[1:]), np.nan)
    valid = np.isfinite(points).all(axis=tuple(range(1, points.ndim)))
    times, points = times[valid], points[valid]
    for i, q in enumerate(queries):
        j = np.searchsorted(times, q)
        if j < len(times) and np.isclose(times[j], q, atol=1e-7, rtol=0):
            result[i] = points[j]
        elif 0 < j < len(times) and times[j] - times[j - 1] <= max_gap:
            w = (q - times[j - 1]) / (times[j] - times[j - 1])
            result[i] = points[j - 1] * (1 - w) + points[j] * w
    return result


def analyze(trial, pose, motions, metadata, phase_result, output, config, model_root):
    from .case_study import (
        sample_video,
        sample_motion,
        normalize_reference,
        normalize_motion,
        project,
    )

    methods = tuple(label for label in METHODS if label in motions)
    output = Path(output)
    phase = np.linspace(0, 1, 101)
    queries = {
        key: bounds[0] + phase * (bounds[1] - bounds[0])
        for key, bounds in trial.windows.items()
    }
    reference, sw = normalize_reference(
        sample_video(pose, queries["video"]), metadata["width"], metadata["height"]
    )
    ref_features = body_features(reference)
    ref_valid = np.isfinite(ref_features).all(axis=1)
    if ref_valid.mean() < MIN_COVERAGE:
        raise ValidationError(
            "Upper-body action alignment requires at least 80% common torso and arm coverage."
        )
    predictions, paths, all_errors, diagnostics = {}, {}, {}, {}
    for label in methods:
        xyz, _ = normalize_motion(sample_motion(motions[label], queries[label]))
        fits = phase_result["calibration"][label]["solutions"]
        predictions[label] = [body_features(project(xyz, fit)) for fit in fits]
        path = paths[label] = bounded_path(ref_features, predictions[label][0])
        all_errors[label] = [
            per_reference_errors(ref_features, feature, path)
            for feature in predictions[label]
        ]
        diagnostics[label] = {
            "mean_phase_shift": float(np.mean(abs(path[:, 0] - path[:, 1]) / 100)),
            "max_phase_shift": float(np.max(abs(path[:, 0] - path[:, 1]) / 100)),
            "boundary_fraction": float(
                np.mean(abs(path[:, 0] - path[:, 1]) >= BAND * 100)
            ),
            "before_local_alignment_arm_mean_deg": summary(
                circular_difference(
                    ref_features[ref_valid, 2:6], predictions[label][0][ref_valid, 2:6]
                )
            )["mean"],
            "after_local_alignment_arm_mean_deg": summary(
                all_errors[label][0][ref_valid, 2:6]
            )["mean"],
        }
    regions = []
    trace_rows = []

    def add_region(name, refs, errors, columns, unit="degrees"):
        common = np.isfinite(refs[:, columns]).all(axis=1)
        for label in methods:
            for values in errors[label]:
                common &= np.isfinite(values[:, columns]).all(axis=1)
        coverage = float(common.mean())
        row = {
            "region": name,
            "unit": unit,
            "common_coverage": coverage,
            "status": "provisional_2d"
            if coverage >= MIN_COVERAGE
            else "insufficient_coverage",
            "methods": {},
        }
        for label in methods:
            selected = errors[label][0][:, columns]
            metrics = (
                summary(selected[common]) if coverage >= MIN_COVERAGE else summary([])
            )
            means = (
                [summary(e[common][:, columns])["mean"] for e in errors[label]]
                if coverage >= MIN_COVERAGE
                else []
            )
            row["methods"][label] = {
                **metrics,
                "camera_range": [min(means), max(means)] if means else None,
            }
            for i in range(len(phase)):
                trace_rows.append(
                    {
                        "region": name,
                        "method": label,
                        "video_time_s": queries["video"][i],
                        "reference_phase": phase[i],
                        "valid_common": int(common[i]),
                        "mean_angular_difference_deg": float(np.mean(selected[i]))
                        if common[i]
                        else "",
                    }
                )
        if coverage >= MIN_COVERAGE and len(methods) == 2:
            a, b = (row["methods"][k] for k in METHODS)
            row["old_minus_motioncapture"] = b["mean"] - a["mean"]
            row["camera_difference_range"] = [
                b["camera_range"][0] - a["camera_range"][1],
                b["camera_range"][1] - a["camera_range"][0],
            ]
            row["ranking_changes_with_camera"] = (
                row["camera_difference_range"][0]
                < 0
                < row["camera_difference_range"][1]
            )
        regions.append(row)

    for i, name in enumerate(BODY_NAMES):
        add_region(name, ref_features, all_errors, [i])
    upper_info = metadata.get("upper_body", {})
    hand_data = None
    hand_reason = "Hand landmarks were not extracted for this historical report."
    if upper_info:
        upper_path = trial.video_landmarks.parent / upper_info["file"]
        if not upper_path.is_file() or sha256(upper_path) != upper_info["sha256"]:
            raise ValidationError(
                "Upper-body reference file is missing or hash mismatched."
            )
        if upper_info.get("hand_model_available"):
            hand_model = (model_root / config.get("hand_model", "")).resolve()
            if metadata.get("pose_model") != "rtmlib_dwpose_wholebody" and (
                not hand_model.is_file() or sha256(hand_model) != upper_info.get(
                    "hand_model_sha256"
                )
            ):
                raise ValidationError("Hand model is missing or hash mismatched.")
            with np.load(upper_path, allow_pickle=False) as data:
                hand_data = {
                    "times": data["times"].copy(),
                    "hands": data["hands"].copy(),
                }
        else:
            hand_reason = "Hand model unavailable; no finger or palm measurements."
    hand_animation = {}
    finger_rows = []
    for label in methods:
        motion = motions[label]
        window = trial.windows[label]
        chosen = (motion.times >= window[0]) & (motion.times <= window[1])
        for side, side_name in enumerate(("left", "right")):
            if motion.extras is None or not chosen.any():
                continue
            hand = np.concatenate(
                (
                    motion.joints[chosen, 4 + side : 5 + side],
                    motion.extras[chosen, 3 + side * 20 : 23 + side * 20],
                ),
                axis=1,
            )
            flexion, names = hand_features(hand)
            excursions = [
                float(np.ptp(column)) if np.isfinite(column).all() else None
                for column in flexion[:, :15].T
            ]
            maximum = max((v for v in excursions if v is not None), default=None)
            hand_animation[f"{label}_{side_name}"] = {
                "native_3d_bend_excursions_deg": excursions,
                "bend_names": names[:15],
                "maximum_bend_excursion_deg": maximum,
                "effectively_fixed_bends": maximum < 1 if maximum is not None else None,
                "diagnostic_threshold_deg": 1.0,
                "interpretation": "Native 3D joint-bend range on native frames within the selected action. This measures articulation stored in the file, not accuracy against video. A 1-degree diagnostic threshold flags effectively fixed bends; it is not an accuracy tolerance.",
            }
            for time, values in zip(motion.times[chosen], flexion[:, :15]):
                for name, value in zip(names[:15], values):
                    finger_rows.append(
                        {
                            "method": label,
                            "side": side_name,
                            "native_time_s": time,
                            "bend": name,
                            "angle_degrees": float(value) if np.isfinite(value) else "",
                        }
                    )
    if finger_rows:
        with (output / "finger_animation_traces.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(finger_rows[0]))
            writer.writeheader()
            writer.writerows(finger_rows)
    if hand_data is not None:
        for side, side_name in enumerate(("Left", "Right")):
            hand_reference = interpolate_extra(
                hand_data["times"], hand_data["hands"][:, side], queries["video"]
            ) * [metadata["width"], metadata["height"]]
            # Small image segments cannot provide a useful projected bending angle.
            for finger in range(5):
                indices = list(range(1 + 4 * finger, 5 + 4 * finger))
                lengths = np.linalg.norm(
                    np.diff(hand_reference[:, indices], axis=1), axis=2
                )
                hand_reference[np.any(lengths < 3, axis=1)] = np.nan
            hand_ref_features, feature_names = hand_features(hand_reference)
            errors = {}
            for label in methods:
                motion = motions[label]
                if motion.extras is None:
                    native = np.full((len(phase), 20, 3), np.nan)
                else:
                    native = np.stack(
                        [
                            np.column_stack(
                                [
                                    np.interp(
                                        queries[label],
                                        motion.times,
                                        motion.extras[:, j, a],
                                    )
                                    for a in range(3)
                                ]
                            )
                            for j in range(3 + 20 * side, 23 + 20 * side)
                        ],
                        axis=1,
                    )
                sampled = sample_motion(motion, queries[label])
                wrist = sampled[:, 4 + side : 5 + side]
                hand = np.concatenate((wrist, native), axis=1)
                centre = sampled[:, :2].mean(axis=1)[:, None]
                width = np.median(np.linalg.norm(sampled[:, 0] - sampled[:, 1], axis=1))
                hand = (hand - centre) / width
                fits = phase_result["calibration"][label]["solutions"]
                features = [hand_features(project(hand, fit))[0] for fit in fits]
                errors[label] = [
                    per_reference_errors(hand_ref_features, f, paths[label])
                    for f in features
                ]
            for finger in range(5):
                add_region(
                    f'{side_name} {("thumb", "index", "middle", "ring", "pinky")[finger]} shape',
                    hand_ref_features,
                    errors,
                    list(range(finger * 3, finger * 3 + 3)),
                )
            add_region(f"{side_name} palm direction", hand_ref_features, errors, [15])
            add_region(f"{side_name} palm spread", hand_ref_features, errors, [16])
    else:
        for side in ("Left", "Right"):
            regions.append(
                {
                    "region": f"{side} fingers and palm",
                    "status": "not_assessed",
                    "reason": hand_reason,
                    "methods": {},
                    "common_coverage": 0,
                    "unit": "degrees",
                }
            )
    regions.extend(
        [
            {
                "region": "Head and neck",
                "status": "not_assessed",
                "reason": "Video ears/nose and FBX head/neck pivots are different anatomical points. A validated head-orientation mapping is required.",
                "methods": {},
                "common_coverage": None,
            },
            {
                "region": "Individual spine joints",
                "status": "not_assessed",
                "reason": "Single-view landmarks support torso lean, not separate spinal joint measurements.",
                "methods": {},
                "common_coverage": None,
            },
            {
                "region": "Wrist position / hand placement",
                "status": "available_in_position_report",
                "reason": "Existing position traces retain hand placement relative to the shoulders. Direction scores alone do not measure placement.",
                "methods": {},
                "common_coverage": None,
            },
        ]
    )
    with (output / "action_shape_traces.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(trace_rows[0]))
        writer.writeheader()
        writer.writerows(trace_rows)
    with (output / "action_alignment.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "method",
                "video_index",
                "fbx_index",
                "video_time_s",
                "fbx_time_s",
                "video_phase",
                "fbx_phase",
            ]
        )
        for label in methods:
            for i, j in paths[label]:
                writer.writerow(
                    [
                        label,
                        i,
                        j,
                        queries["video"][i],
                        queries[label][j],
                        phase[i],
                        phase[j],
                    ]
                )
    result = {
        "status": "exploratory",
        "regions": regions,
        "alignment_diagnostics": diagnostics,
        "method": "One bounded monotone alignment per FBX, shared by all regions; four arm directions set the path. Angles remove segment-length effects in the image plane. Each video sample has equal weight.",
        "limits": "2D projected shape only. Head/neck and individual spine joints are unassessed. Torso/shoulders also participate in camera calibration. Hands use estimated landmarks with provisional anatomical mapping and no per-point confidence. Camera and tracking uncertainty prevent a definitive accuracy ranking. No overall winner or statistical equivalence claim.",
        "alignment_policy": {
            "band_fraction": BAND,
            "steps": [[1, 1], [1, 2], [2, 1]],
            "grid_samples": 101,
            "camera_selected_by": "torso calibration only",
            "camera_sensitivity": "Same primary warp applied to alternative torso fits; not confidence intervals",
        },
        "hand_reference": upper_info,
        "hand_animation_diagnostics": hand_animation,
    }
    plot(result, trace_rows, paths, output)
    if finger_rows:
        plot_fingers(finger_rows, trial.windows, output)
    return result


def plot(result, rows, paths, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), constrained_layout=True)
    for label, color, name in (
        ("suit", "#126c9d", "MotionCapture"),
        ("non_suit", "#cb6031", "Old FBX"),
    ):
        if label not in paths:
            continue
        path = paths[label]
        axes[0].plot(path[:, 0] / 100, path[:, 1] / 100, color=color, label=name)
        for ax, region in zip(axes[1:], ("Left forearm", "Right forearm")):
            records = [
                r for r in rows if r["region"] == region and r["method"] == label
            ]
            ax.plot(
                [r["video_time_s"] for r in records],
                [
                    r["mean_angular_difference_deg"] if r["valid_common"] else np.nan
                    for r in records
                ],
                color=color,
                label=name,
            )
            ax.set(
                title=region + " projected direction difference",
                xlabel="Video time (seconds)",
                ylabel="Degrees",
            )
            ax.set_ylim(bottom=0)
    axes[0].plot([0, 1], [0, 1], "--", color="gray", label="No local time warping")
    axes[0].set(
        title="Shared action alignment (not timing accuracy)",
        xlabel="Video action phase",
        ylabel="FBX action phase",
    )
    for ax in axes:
        ax.legend()
        ax.grid(alpha=0.2)
    fig.savefig(output / "action_shape.svg")
    fig.savefig(output / "action_shape.png", dpi=140)
    plt.close(fig)


def render_html(result):
    if result.get("status") != "exploratory":
        return (
            "<h2>Upper-body action shape</h2><p>"
            + escape(result.get("reason", "Not assessed"))
            + "</p>"
        )
    rows = []
    for row in result["regions"]:
        cells = []
        for label in METHODS:
            value = row["methods"].get(label, {})
            cells.append(
                f"{value['mean']:.2f}° ({value['camera_range'][0]:.2f}–{value['camera_range'][1]:.2f})"
                if value.get("mean") is not None
                else "Not assessed"
            )
        coverage = (
            "—" if row["common_coverage"] is None else f"{row['common_coverage']:.0%}"
        )
        rows.append(
            "<tr><td>"
            + escape(row["region"])
            + "</td><td>"
            + "</td><td>".join(cells)
            + "</td><td>"
            + coverage
            + "</td><td>"
            + escape(row.get("reason", row["status"]))
            + "</td></tr>"
        )
    finger_rows = []
    for side in ("left", "right"):
        values = [
            result["hand_animation_diagnostics"]
            .get(f"{label}_{side}", {})
            .get("maximum_bend_excursion_deg")
            for label in METHODS
        ]
        cells = [
            "Not assessed" if value is None else f"{value:.4f}°" for value in values
        ]
        finger_rows.append(
            f"<tr><td>{side}</td><td>{cells[0]}</td><td>{cells[1]}</td></tr>"
        )
    return (
        "<h2>Upper-body action shape, allowing timing differences</h2><p>"
        + escape(result["method"])
        + "</p><p>"
        + escape(result["limits"])
        + "</p><h3>Finger articulation stored in the files</h3><p>Maximum native 3D joint-bend excursion within the selected action. More movement is not proof of accuracy; changes below 1° are flagged as effectively fixed for diagnosis only.</p><table><tr><th>Hand</th><th>MotionCapture</th><th>Old FBX</th></tr>"
        + "".join(finger_rows)
        + "</table><p>"
        + "</p><p>Lower angular difference is closer in the image plane. Parentheses show camera sensitivity ranges.</p><table><tr><th>Region</th><th>MotionCapture</th><th>Old FBX</th><th>Common coverage</th><th>Status</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def plot_fingers(rows, windows, output):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 5, figsize=(16, 7), constrained_layout=True)
    for side_index, side in enumerate(("left", "right")):
        for finger_index, finger in enumerate(
            ("thumb", "index", "middle", "ring", "pinky")
        ):
            ax = axes[side_index, finger_index]
            for label, color, name in (
                ("suit", "#126c9d", "MotionCapture"),
                ("non_suit", "#cb6031", "Old FBX"),
            ):
                data = [
                    r
                    for r in rows
                    if r["method"] == label
                    and r["side"] == side
                    and r["bend"] == f"{finger} bend 2"
                ]
                if label not in windows:
                    continue
                start, end = windows[label]
                ax.plot(
                    [(r["native_time_s"] - start) / (end - start) for r in data],
                    [
                        r["angle_degrees"] if r["angle_degrees"] != "" else np.nan
                        for r in data
                    ],
                    color=color,
                    label=name,
                )
            ax.set(
                title=f"{side.title()} {finger}",
                xlabel="Native action phase",
                ylabel="Middle bend (degrees)",
                ylim=(0, 185),
            )
            ax.grid(alpha=0.2)
    axes[0, 0].legend()
    fig.suptitle("Finger bending present in the FBX files — not accuracy against video")
    fig.savefig(output / "finger_animation.svg")
    fig.savefig(output / "finger_animation.png", dpi=140)
    plt.close(fig)
