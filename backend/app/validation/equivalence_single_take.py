"""Equivalence of one FBX take against its simultaneous two-view video measurement.

With a single repetition the only replication is over time inside the take, and neighbouring
frames are strongly correlated (lag-1 r ~ 0.9 after the 6 Hz filter), leaving an effective sample
of only a handful of frames. Decisions use an AR(1) effective sample size with Kendall's small-
sample correction of r (Bretherton et al., 1999), which simulation showed holds the false-
equivalence rate at alpha; a circular block bootstrap under-covered badly at these sizes and is
reported only as a cross-check.
The claim supported is narrow: in this recording the two measurement systems agree within the
prespecified margin. It says nothing about other performers, signs or sessions.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.signal import butter, filtfilt
from scipy.stats import chi2, norm, t as student

from .mixed_effects import ValidationError
from .scoring import PHASE

MARGINS_FILE = Path(__file__).with_name("equivalence_margins.json")
EQUIVALENT = "EQUIVALENT"
NOT_EQUIVALENT = "NOT EQUIVALENT"
INCONCLUSIVE = "INCONCLUSIVE"
PARTIALLY_EQUIVALENT = "PARTIALLY EQUIVALENT"  # fixed-sequence testing confirmed some angles
SCOPE = (
    "Single take: FBX and two-view video agree within the margin for this recording only; "
    "not evidence of equivalence across performers, signs or sessions."
)


def load_margins(path: str | Path = MARGINS_FILE) -> dict[str, float]:
    """Margins are fixed in version control before any take is analysed."""
    try:
        source = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ValidationError(f"Cannot read equivalence margins: {exc}") from exc
    margins = {name: float(item["margin_deg"]) for name, item in source["angles"].items()}
    if not margins or min(margins.values()) <= 0:
        raise ValidationError("Every equivalence margin must be positive.")
    return margins


def automatic_block_length(series: np.ndarray) -> int:
    """Politis & White (2004) circular-block length, with the Patton et al. (2009) correction."""
    x = np.asarray(series, dtype=float)
    x = x[np.isfinite(x)] - np.nanmean(x)
    n = len(x)
    if n < 8:
        raise ValidationError("At least eight frames are needed to estimate dependence.")
    variance = float(x @ x) / n
    if variance <= 0:
        return 1
    lags_checked = max(5, int(np.ceil(np.log10(n))))
    max_lag = min(n - 1, int(np.ceil(np.sqrt(n))) + lags_checked)
    autocovariance = np.array([x[: n - k] @ x[k:] / n for k in range(max_lag + 1)])
    rho = autocovariance / variance
    threshold = 2.0 * np.sqrt(np.log10(n) / n)
    cutoff = max_lag
    for lag in range(max_lag - lags_checked + 1):
        if np.all(np.abs(rho[lag + 1 : lag + 1 + lags_checked]) < threshold):
            cutoff = lag
            break
    bandwidth = min(2 * max(cutoff, 1), max_lag)
    lags = np.arange(-bandwidth, bandwidth + 1)
    ratio = np.abs(lags) / bandwidth
    weights = np.where(ratio <= 0.5, 1.0, 2.0 * (1.0 - ratio))
    covariances = autocovariance[np.abs(lags)]
    g = float(np.sum(weights * np.abs(lags) * covariances))
    spectral = float(np.sum(weights * covariances))
    if spectral <= 0:
        return 1
    length = (2.0 * g**2 / (4.0 / 3.0 * spectral**2)) ** (1 / 3) * n ** (1 / 3)
    return int(np.clip(np.ceil(length), 1, max(1, n // 3)))


def block_indices(n: int, block: int, draws: int, rng: np.random.Generator) -> np.ndarray:
    """(draws, n) circular-block resampling indices."""
    blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(draws, blocks))
    offsets = np.arange(block)
    return ((starts[:, :, None] + offsets) % n).reshape(draws, -1)[:, :n]


def newey_west_se(series: np.ndarray, lags: int) -> float:
    x = series - series.mean()
    n = len(x)
    lags = min(lags, n - 1)
    value = x @ x / n
    for k in range(1, lags + 1):
        value += 2 * (1 - k / (lags + 1)) * (x[: n - k] @ x[k:]) / n
    return float(np.sqrt(max(value, 0.0) / n))


def effective_sample_size(series: np.ndarray) -> tuple[float, float]:
    """AR(1) effective n and the bias-corrected lag-1 autocorrelation it rests on."""
    x = series - series.mean()
    n = len(x)
    raw = float(x[:-1] @ x[1:] / (x @ x)) if x @ x > 0 else 0.0
    rho = float(np.clip(raw + (1 + 3 * raw) / n, 0.0, 0.99))  # Kendall (1954) bias correction
    return max(2.0, n * (1 - rho) / (1 + rho)), rho


def _trend(series: np.ndarray, fps: float, cutoff_hz: float) -> np.ndarray:
    """Zero-lag low-pass estimate of the systematic difference curve (last axis is time)."""
    nyquist = fps / 2
    if cutoff_hz >= nyquist:
        return series.copy()
    b, a = butter(2, cutoff_hz / nyquist)
    padding = min(3 * max(len(a), len(b)), series.shape[-1] - 1)
    return filtfilt(b, a, series, axis=-1, padlen=padding)


def _to_phase(values: np.ndarray) -> np.ndarray:
    native = np.linspace(0.0, 1.0, values.shape[-1])
    if values.ndim == 1:
        return np.interp(PHASE, native, values)
    return np.stack([np.interp(PHASE, native, row) for row in values])


def compare_angle(
    video: np.ndarray,
    fbx: np.ndarray,
    margin: float,
    fps: float,
    *,
    alpha: float = 0.05,
    draws: int = 5000,
    trend_cutoff_hz: float = 1.0,
    seed: int = 20261029,
) -> dict:
    """Mean-bias TOST (A) and RMS-error equivalence (B) for one angle trace.

    Both traces must already share the FBX clock and cover exactly the prespecified sign window.
    The constant joint-centre bias between the two skeletons is deliberately not removed.

    A alone could pass with large errors of opposite sign; B bounds the typical frame error and so
    covers time-varying disagreement. A whole-curve band is also reported, but only descriptively:
    with one take, slow detector noise and genuine slow disagreement share the same frequencies and
    cannot be told apart, so the band cannot carry a valid pointwise equivalence claim.
    """
    video = np.asarray(video, dtype=float)
    fbx = np.asarray(fbx, dtype=float)
    if video.shape != fbx.shape or video.ndim != 1:
        raise ValidationError("Video and FBX angle traces must be matching 1D arrays.")
    finite = np.isfinite(video) & np.isfinite(fbx)
    if finite.mean() < 0.9:
        raise ValidationError("More than 10% of the sign window lacks a valid angle.")
    native = np.arange(len(video))
    difference = np.interp(native, native[finite], (video - fbx)[finite])
    n = len(difference)
    block = automatic_block_length(difference)
    rng = np.random.default_rng(seed)
    indices = block_indices(n, block, draws, rng)

    n_eff, rho = effective_sample_size(difference)
    df = n_eff - 1

    # A: the take-average bias; two one-sided t-tests on the effective sample.
    mean = float(difference.mean())
    sd = float(difference.std(ddof=1))
    half = student.ppf(1 - alpha, df) * sd / np.sqrt(n_eff)
    mean_ci = (mean - half, mean + half)
    mean_pass = -margin < mean_ci[0] and mean_ci[1] < margin

    # B: H0 RMS error >= margin. RMS^2 = bias^2 + sd^2; each part gets a one-sided bound at
    # alpha/2 (Bonferroni), the sd through the chi-square law of the effective sample.
    rmse = float(np.sqrt(np.mean(difference**2)))
    bias_upper = abs(mean) + student.ppf(1 - alpha / 2, df) * sd / np.sqrt(n_eff)
    sd_upper = sd * np.sqrt(df / chi2.ppf(alpha / 2, df))
    rmse_upper = float(np.hypot(bias_upper, sd_upper))
    bias_lower = max(0.0, abs(mean) - student.ppf(1 - alpha / 2, df) * sd / np.sqrt(n_eff))
    sd_lower = sd * np.sqrt(df / chi2.ppf(1 - alpha / 2, df))
    rmse_lower = float(np.hypot(bias_lower, sd_lower))
    rmse_pass = rmse_upper < margin

    # Cross-checks only (they under-cover at these effective sizes).
    boot_means = difference[indices].mean(axis=1)
    lower, upper = np.quantile(boot_means - mean, [1 - alpha, alpha])
    bootstrap_ci = (mean - float(lower), mean - float(upper))
    hac_se = newey_west_se(difference, block)
    z = norm.ppf(1 - alpha)
    hac_ci = (mean - z * hac_se, mean + z * hac_se)

    # Descriptive: the slow difference curve with a simultaneous band from residual blocks.
    trend = _trend(difference, fps, trend_cutoff_hz)
    residual = difference - trend
    boot_trends = _trend(trend + residual[indices], fps, trend_cutoff_hz)
    deviation = boot_trends - trend
    # Separate one-sided simultaneous bounds keep each TOST tail at alpha.
    upper_q = np.quantile((-deviation).max(axis=1), 1 - alpha)
    lower_q = np.quantile(deviation.max(axis=1), 1 - alpha)
    curve = _to_phase(trend)
    band_lower = curve - lower_q
    band_upper = curve + upper_q
    band_within = bool(np.all(band_lower > -margin) and np.all(band_upper < margin))
    mean_outside = mean_ci[0] > margin or mean_ci[1] < -margin

    if mean_pass and rmse_pass:
        decision = EQUIVALENT
    elif mean_outside or rmse_lower > margin:
        decision = NOT_EQUIVALENT
    else:
        decision = INCONCLUSIVE
    spread = sd
    with np.errstate(invalid="ignore"):
        shape_r = float(np.corrcoef(video[finite], fbx[finite])[0, 1])
    return {
        "decision": decision,
        "margin_deg": margin,
        "alpha": alpha,
        "frames": n,
        "lag1_autocorrelation": rho,
        "effective_frames": n_eff,
        "block_length_frames": block,
        "mean_difference_deg": mean,
        "mean_ci_deg": list(mean_ci),
        "mean_bootstrap_ci_deg": list(bootstrap_ci),
        "mean_hac_ci_deg": list(hac_ci),
        "mean_tost_pass": bool(mean_pass),
        "rmse_deg": rmse,
        "rmse_ci_deg": [rmse_lower, rmse_upper],
        "rmse_tost_pass": bool(rmse_pass),
        "band_within_margin_descriptive": band_within,
        "curve_phase": PHASE.tolist(),
        "curve_deg": curve.tolist(),
        "band_lower_deg": band_lower.tolist(),
        "band_upper_deg": band_upper.tolist(),
        "max_abs_deg": float(np.max(np.abs(difference))),
        "bland_altman": {"bias_deg": mean, "loa_deg": [mean - 1.96 * spread, mean + 1.96 * spread]},
        "pearson_r": shape_r,
    }


def replicate_spm_tost(differences: np.ndarray, margin: float, *, alpha: float = 0.05) -> dict:
    """spm1d TOST over measurement replicates (e.g. test-time-augmented pose runs).

    Replicates share one performance, so this quantifies pose-estimator noise only and is a
    sensitivity analysis, never the primary claim.
    """
    try:
        import spm1d
    except ImportError as exc:  # pragma: no cover - optional validation extra
        raise ValidationError("Install requirements-validation-secondary.txt for spm1d.") from exc
    values = _to_phase(np.asarray(differences, dtype=float))
    if values.ndim != 2 or len(values) < 5:
        raise ValidationError("spm1d TOST needs at least five replicate curves.")
    below = spm1d.stats.ttest(margin - values).inference(alpha, two_tailed=False)
    above = spm1d.stats.ttest(values + margin).inference(alpha, two_tailed=False)
    passed = bool(np.all(below.z > below.zstar) and np.all(above.z > above.zstar))
    return {
        "evidence": "measurement-replicate",
        "replicates": int(len(values)),
        "pass": passed,
        "upper_zstar": float(below.zstar),
        "lower_zstar": float(above.zstar),
    }


def single_take_report(
    video_angles: dict[str, np.ndarray],
    fbx_angles: dict[str, np.ndarray],
    fps: float,
    margins: dict[str, float] | None = None,
    **options,
) -> dict:
    """Intersection-union across every prespecified angle: all must pass for EQUIVALENT."""
    margins = margins or load_margins()
    missing = sorted(set(margins) - (set(video_angles) & set(fbx_angles)))
    if missing:
        raise ValidationError(f"Missing prespecified angles: {missing}")
    angles = {
        name: compare_angle(video_angles[name], fbx_angles[name], margin, fps, **options)
        for name, margin in margins.items()
    }
    decisions = {item["decision"] for item in angles.values()}
    if decisions == {EQUIVALENT}:
        overall = EQUIVALENT
    elif NOT_EQUIVALENT in decisions:
        overall = NOT_EQUIVALENT
    else:
        overall = INCONCLUSIVE
    return {"decision": overall, "scope": SCOPE, "angles": angles}

