"""
Single-pair fTOST + SPM1D statistical equivalence validation.

Uses multi-channel joint waveforms from one FBX + one reference video.
Each joint coordinate (left/right × wrist/elbow × x/y) provides a
separate measurement channel, enabling variance estimation without
multiple performers.

This is a per-performance assessment.  It does NOT generalise to the
population of all possible performances or performers.
"""

from __future__ import annotations

import csv
import warnings
from pathlib import Path

import numpy as np

try:
    import spm1d
except ImportError:
    spm1d = None

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# ---------------------------------------------------------------------------
# Channel definitions — (fbx_column, reference_column, display_label)
# ---------------------------------------------------------------------------

POSITION_CHANNELS = [
    ("suit_left_wrist_x", "reference_left_wrist_x", "Left Wrist X"),
    ("suit_left_wrist_y", "reference_left_wrist_y", "Left Wrist Y"),
    ("suit_right_wrist_x", "reference_right_wrist_x", "Right Wrist X"),
    ("suit_right_wrist_y", "reference_right_wrist_y", "Right Wrist Y"),
    ("suit_left_elbow_x", "reference_left_elbow_x", "Left Elbow X"),
    ("suit_left_elbow_y", "reference_left_elbow_y", "Left Elbow Y"),
    ("suit_right_elbow_x", "reference_right_elbow_x", "Right Elbow X"),
    ("suit_right_elbow_y", "reference_right_elbow_y", "Right Elbow Y"),
]

ANGLE_CHANNELS = [
    ("suit_left_elbow_angle", "reference_left_elbow_angle", "Left Elbow Angle"),
    ("suit_right_elbow_angle", "reference_right_elbow_angle", "Right Elbow Angle"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_trace(path: Path) -> dict[str, np.ndarray]:
    """Read a phase-normalised trace CSV into column arrays."""
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"Empty trace file: {path}")
    arrays: dict[str, np.ndarray] = {}
    for field in rows[0]:
        values: list[float] = []
        for row in rows:
            try:
                values.append(float(row[field]))
            except (ValueError, TypeError):
                values.append(np.nan)
        arrays[field] = np.array(values)
    return arrays


def _extract_channels(
    traces: dict[str, np.ndarray],
    channel_defs: list[tuple[str, str, str]],
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Return (fbx, ref, labels) for channels present in *traces*."""
    fbx_list, ref_list, labels = [], [], []
    for fbx_col, ref_col, label in channel_defs:
        if fbx_col in traces and ref_col in traces:
            fbx_list.append(traces[fbx_col])
            ref_list.append(traces[ref_col])
            labels.append(label)
    if not labels:
        return np.empty((0, 0)), np.empty((0, 0)), []
    return np.array(fbx_list), np.array(ref_list), labels


def _longest_valid_run(mask: np.ndarray) -> np.ndarray:
    """Indices of the longest contiguous block of True values."""
    indices = np.flatnonzero(mask)
    if len(indices) == 0:
        return np.array([], dtype=int)
    splits = np.where(np.diff(indices) != 1)[0] + 1
    runs = np.split(indices, splits)
    return max(runs, key=len)


def _idx_to_phase(endpoint: float, phase_pct: np.ndarray) -> float:
    """Map an SPM1D cluster endpoint (0-based index) to phase %."""
    if endpoint <= 0:
        return float(phase_pct[0])
    last = len(phase_pct) - 1
    if endpoint >= last:
        return float(phase_pct[-1])
    lo = int(endpoint)
    hi = min(lo + 1, last)
    frac = endpoint - lo
    return float(phase_pct[lo] * (1 - frac) + phase_pct[hi] * frac)


def _prevent_zero_variance(y1: np.ndarray, y2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """spm1d requires non-zero sample variance across channels at every node."""
    diff = y1 - y2
    zero_nodes = diff.var(axis=0) <= 1e-14
    if np.any(zero_nodes):
        rng = np.random.default_rng(2026)
        jitter = rng.normal(0, 1e-8, size=y1.shape)
        return y1 + jitter, y2
    return y1, y2


# ---------------------------------------------------------------------------
# Core statistical tests
# ---------------------------------------------------------------------------


def _run_ftost(
    fbx: np.ndarray,
    ref: np.ndarray,
    delta: float,
    alpha: float,
) -> dict:
    """
    Functional Two One-Sided Test via SPM1D.

    Parameters
    ----------
    fbx, ref : (N_channels, T) arrays
    delta    : equivalence margin (same units as data)
    alpha    : significance level

    Returns
    -------
    dict with t-curves, thresholds, equivalence verdict, failing regions.
    """
    # ------------------------------------------------------------------
    # Upper-bound test — H0: μ(FBX − Ref) ≥ δ
    #   Rewrite as testing μ((Ref + δ) − FBX) > 0  →  right-tailed
    # ------------------------------------------------------------------
    ya, yb = _prevent_zero_variance(ref + delta, fbx)
    t_upper = spm1d.stats.ttest_paired(ya, yb)
    inf_upper = t_upper.inference(alpha=alpha, two_tailed=False)
    upper_t = np.asarray(t_upper.z)
    upper_thresh = float(inf_upper.zstar)
    upper_rejects = upper_t > upper_thresh

    # ------------------------------------------------------------------
    # Lower-bound test — H0: μ(FBX − Ref) ≤ −δ
    #   Rewrite as testing μ(FBX − (Ref − δ)) > 0  →  right-tailed
    # ------------------------------------------------------------------
    ya, yb = _prevent_zero_variance(fbx, ref - delta)
    t_lower = spm1d.stats.ttest_paired(ya, yb)
    inf_lower = t_lower.inference(alpha=alpha, two_tailed=False)
    lower_t = np.asarray(t_lower.z)
    lower_thresh = float(inf_lower.zstar)
    lower_rejects = lower_t > lower_thresh

    # Both must reject at every time point for equivalence.
    both = upper_rejects & lower_rejects
    is_equivalent = bool(np.all(both))

    # Identify contiguous failing regions.
    failing_regions: list[dict] = []
    failing = ~both
    if np.any(failing):
        diffs = np.diff(failing.astype(int))
        starts = list(np.where(diffs == 1)[0] + 1)
        ends = list(np.where(diffs == -1)[0] + 1)
        if failing[0]:
            starts = [0] + starts
        if failing[-1]:
            ends = ends + [len(failing)]
        for s, e in zip(starts, ends):
            # Determine which bound(s) failed in this region
            reasons = []
            segment_upper = ~upper_rejects[s:e]
            segment_lower = ~lower_rejects[s:e]
            if np.any(segment_upper):
                reasons.append("FBX above upper bound (FBX > Ref + δ)")
            if np.any(segment_lower):
                reasons.append("FBX below lower bound (FBX < Ref − δ)")
            failing_regions.append({
                "timepoint_start": int(s),
                "timepoint_end": int(e - 1),
                "reasons": reasons,
            })

    return {
        "is_equivalent": is_equivalent,
        "equivalence_fraction": round(float(np.mean(both)), 4),
        "upper_t_curve": upper_t.tolist(),
        "lower_t_curve": lower_t.tolist(),
        "upper_critical_threshold": round(upper_thresh, 4),
        "lower_critical_threshold": round(lower_thresh, 4),
        "failing_regions": failing_regions,
    }


def _run_paired_ttest(
    fbx: np.ndarray,
    ref: np.ndarray,
    alpha: float,
) -> dict:
    """Exploratory two-tailed SPM1D paired t-test."""
    ya, yb = _prevent_zero_variance(fbx, ref)
    t_stat = spm1d.stats.ttest_paired(ya, yb)
    inf = t_stat.inference(alpha=alpha, two_tailed=True, interp=True)
    clusters: list[dict] = []
    if hasattr(inf, "clusters") and inf.clusters:
        for c in inf.clusters:
            clusters.append({
                "endpoints_idx": [float(e) for e in c.endpoints],
                "p_value": round(float(c.P), 6),
            })
    return {
        "t_curve": np.asarray(inf.z).tolist(),
        "critical_threshold": round(float(inf.zstar), 4),
        "significant_clusters": clusters,
        "any_significant_difference": len(clusters) > 0,
    }


# ---------------------------------------------------------------------------
# Plot generation
# ---------------------------------------------------------------------------


def _generate_plot(
    ftost: dict,
    paired: dict,
    mean_diff: np.ndarray,
    delta: float,
    n_channels: int,
    sign_name: str,
    phase_pct: np.ndarray,
    output: Path,
) -> str:
    """Create a three-panel validation figure and return the PNG filename."""
    is_eq = ftost["is_equivalent"]
    verdict = "EQUIVALENT" if is_eq else "NOT EQUIVALENT"
    verdict_colour = "#2e7d32" if is_eq else "#c62828"

    fig, axes = plt.subplots(3, 1, figsize=(12, 14))

    # ---- Panel 1: mean difference with equivalence band ----
    ax = axes[0]
    ax.fill_between(
        phase_pct, -delta, delta,
        alpha=0.12, color="green", label=f"Equivalence band (±{delta} SW)",
    )
    ax.plot(phase_pct, mean_diff, color="#1565c0", lw=2, label="Mean FBX − Reference")
    ax.axhline(0, color="grey", ls=":", alpha=0.5)
    for rgn in ftost["failing_regions"]:
        s, e = rgn["timepoint_start"], rgn["timepoint_end"]
        ax.axvspan(
            phase_pct[s], phase_pct[min(e, len(phase_pct) - 1)],
            alpha=0.18, color="red", label="_",
        )
    ax.set_title(
        f"fTOST Equivalence — {sign_name}\n"
        f"Verdict: {verdict}  "
        f"({ftost['equivalence_fraction'] * 100:.1f}% of phases within tolerance)",
        fontsize=13, fontweight="bold", color=verdict_colour,
    )
    ax.set_ylabel("Difference (shoulder widths)")
    # De-duplicate legend entries
    handles, labels = ax.get_legend_handles_labels()
    seen: set[str] = set()
    unique = [(h, l) for h, l in zip(handles, labels) if l not in seen and not seen.add(l)]
    if unique:
        ax.legend(*zip(*unique), loc="upper right")
    ax.grid(True, alpha=0.3)

    # ---- Panel 2: fTOST t-curves ----
    ax = axes[1]
    upper_t = np.array(ftost["upper_t_curve"])
    lower_t = np.array(ftost["lower_t_curve"])
    u_thr = ftost["upper_critical_threshold"]
    l_thr = ftost["lower_critical_threshold"]
    ax.plot(phase_pct, upper_t, color="#ef5350", lw=1.5, label="Upper-bound t")
    ax.plot(phase_pct, lower_t, color="#42a5f5", lw=1.5, label="Lower-bound t")
    ax.axhline(u_thr, color="#ef5350", ls="--", alpha=0.6,
               label=f"Critical threshold ({u_thr:.2f})")
    ax.axhline(l_thr, color="#42a5f5", ls="--", alpha=0.6)
    # Shade where each test rejects (above threshold)
    ax.fill_between(phase_pct, u_thr, np.maximum(upper_t, u_thr),
                     alpha=0.12, color="#ef5350")
    ax.fill_between(phase_pct, l_thr, np.maximum(lower_t, l_thr),
                     alpha=0.12, color="#42a5f5")
    ax.set_title(
        f"fTOST SPM1D t-statistics  (df = {n_channels - 1}, α = 0.05)",
        fontsize=12,
    )
    ax.set_ylabel("t-statistic")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)

    # ---- Panel 3: two-tailed paired t-test ----
    ax = axes[2]
    t_curve = np.array(paired["t_curve"])
    thr = paired["critical_threshold"]
    ax.plot(phase_pct, t_curve, color="#283593", lw=1.5, label="Paired t-statistic")
    ax.axhline(thr, color="#c62828", ls="--", alpha=0.6, label=f"±{thr:.2f}")
    ax.axhline(-thr, color="#c62828", ls="--", alpha=0.6)
    for cl in paired["significant_clusters"]:
        s_idx, e_idx = cl["endpoints_idx"]
        ax.axvspan(
            _idx_to_phase(s_idx, phase_pct),
            _idx_to_phase(e_idx, phase_pct),
            alpha=0.18, color="red",
        )
    n_cl = len(paired["significant_clusters"])
    ax.set_title(
        f"SPM1D Paired t-test (two-tailed) — {n_cl} significant cluster(s)",
        fontsize=12,
    )
    ax.set_xlabel("Phase (%)")
    ax.set_ylabel("t-statistic")
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    png_path = output / "ftost_spm1d_result.png"
    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    svg_path = output / "ftost_spm1d_result.svg"
    fig.savefig(svg_path, bbox_inches="tight")
    plt.close(fig)
    return png_path.name


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_single_pair_validation(
    results_dir: str | Path,
    *,
    sign_name: str = "Sign",
    position_delta: float = 0.20,
    alpha: float = 0.05,
) -> dict:
    """
    Run real fTOST + SPM1D on the case-study phase-normalised traces.

    Parameters
    ----------
    results_dir    : directory written by ``run_case_study``
    sign_name      : action / sign label used in plot titles
    position_delta : equivalence margin in shoulder widths (per coordinate)
    alpha          : significance level

    Returns
    -------
    dict suitable for embedding in the summary JSON under
    ``statistical_validation``.
    """
    if spm1d is None:
        return {
            "status": "unavailable",
            "reason": "spm1d is not installed.  pip install spm1d",
        }

    results_dir = Path(results_dir)
    trace_path = results_dir / "phase_normalized_traces.csv"
    if not trace_path.is_file():
        return {
            "status": "no_traces",
            "reason": (
                "Phase-normalised trace CSV not found; "
                "the descriptive case study may have failed."
            ),
        }

    traces = _read_trace(trace_path)

    # ---- extract position channels ----
    fbx_pos, ref_pos, pos_labels = _extract_channels(traces, POSITION_CHANNELS)
    if len(pos_labels) < 3:
        return {
            "status": "insufficient_channels",
            "reason": (
                f"Only {len(pos_labels)} position channel(s) found; "
                f"need at least 3 for a meaningful t-test."
            ),
            "channels_found": pos_labels,
        }

    # ---- find longest contiguous finite region ----
    valid_mask = (
        np.isfinite(fbx_pos).all(axis=0) & np.isfinite(ref_pos).all(axis=0)
    )
    run = _longest_valid_run(valid_mask)
    if len(run) < 50:
        return {
            "status": "insufficient_coverage",
            "reason": (
                f"Only {len(run)} contiguous valid phase samples (need ≥ 50)."
            ),
        }

    fbx_v = fbx_pos[:, run]
    ref_v = ref_pos[:, run]

    # Phase percentages for the valid region
    # (trace rows 0..100 already correspond to 0 %..100 %)
    phase_pct = run.astype(float)

    # ---- fTOST ----
    ftost = _run_ftost(fbx_v, ref_v, position_delta, alpha)

    # Annotate failing regions with phase %
    for rgn in ftost["failing_regions"]:
        s, e = rgn["timepoint_start"], rgn["timepoint_end"]
        rgn["phase_start_pct"] = round(float(phase_pct[s]), 2)
        rgn["phase_end_pct"] = round(float(phase_pct[min(e, len(phase_pct) - 1)]), 2)

    # ---- exploratory paired t-test ----
    paired = _run_paired_ttest(fbx_v, ref_v, alpha)

    # Convert cluster endpoints to phase %
    for cl in paired["significant_clusters"]:
        s_idx, e_idx = cl["endpoints_idx"]
        cl["phase_start_pct"] = round(_idx_to_phase(s_idx, phase_pct), 2)
        cl["phase_end_pct"] = round(_idx_to_phase(e_idx, phase_pct), 2)

    # ---- mean difference waveform ----
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean_diff = np.nanmean(fbx_v - ref_v, axis=0)

    # ---- supplementary: angle descriptive stats ----
    fbx_ang, ref_ang, ang_labels = _extract_channels(traces, ANGLE_CHANNELS)
    angle_desc: dict[str, dict] = {}
    for i, label in enumerate(ang_labels):
        ok = np.isfinite(fbx_ang[i]) & np.isfinite(ref_ang[i])
        if ok.sum() > 0:
            d = fbx_ang[i][ok] - ref_ang[i][ok]
            angle_desc[label] = {
                "mean_difference_deg": round(float(np.mean(d)), 2),
                "max_abs_difference_deg": round(float(np.max(np.abs(d))), 2),
                "p95_abs_difference_deg": round(
                    float(np.percentile(np.abs(d), 95)), 2
                ),
            }

    # ---- plot ----
    plot_name = _generate_plot(
        ftost, paired, mean_diff, position_delta,
        len(pos_labels), sign_name, phase_pct, results_dir,
    )

    verdict = "EQUIVALENT" if ftost["is_equivalent"] else "NOT EQUIVALENT"

    return {
        "status": "completed",
        "sign_name": sign_name,
        "verdict": verdict,
        "method": "Single-pair multi-channel fTOST + SPM1D",
        "interpretation": (
            "Each joint coordinate (wrist/elbow × left/right × x/y) is treated "
            "as a separate measurement channel.  fTOST tests whether the mean "
            "cross-channel difference lies within ±δ at every phase of the "
            "normalised movement.  This is a single-performance assessment, not "
            "population-level inference across performers."
        ),
        "parameters": {
            "position_delta_shoulder_widths": position_delta,
            "alpha": alpha,
            "n_position_channels": len(pos_labels),
            "degrees_of_freedom": len(pos_labels) - 1,
            "valid_phase_samples": len(run),
            "phase_start_pct": round(float(phase_pct[0]), 2),
            "phase_end_pct": round(float(phase_pct[-1]), 2),
        },
        "position_channels": pos_labels,
        "ftost": ftost,
        "paired_ttest": paired,
        "mean_difference_waveform": mean_diff.tolist(),
        "angle_descriptive": angle_desc,
        "artifacts": {
            "ftost_plot": plot_name,
            "ftost_plot_svg": plot_name.replace(".png", ".svg"),
        },
    }
