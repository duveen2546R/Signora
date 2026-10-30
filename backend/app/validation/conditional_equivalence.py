"""Single-take equivalence conditional on the performance (noise recording + pose replicates).

One take cannot show how a *new* performance would differ, but it can show whether the FBX and the
two-view video disagree by more than the video's own measurement error explains. That error is
characterised outside the sign:

1. Detector jitter in pixels, per view and joint, with its AR(1) memory, measured while the
   performer is still: in an optional noise recording made with the same unmoved phones (hold,
   then slow movement that also feeds calibration), or else in the holds before and after the
   sign in the sign videos themselves. The pixel noise, and the camera calibration re-fitted
   under that noise, are pushed through triangulation, filtering and the angle definitions of
   this exact sign by Monte Carlo (a parametric bootstrap of the whole measurement chain).
2. Pose-model replicates of the sign videos (test-time augmentation or several models): their
   spread checks that detector noise while moving is no larger than at rest, and their curves
   feed an spm1d TOST as an independent line of evidence.

The claim is conditional: for this recording the FBX equals the two-view measurement within the
margin. It is not evidence about other performers, signs or sessions.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass

import numpy as np
from scipy.stats import chi2, t as student

from .angles3d import joint_angles
from .equivalence_single_take import (
    EQUIVALENT,
    INCONCLUSIVE,
    MARGINS_FILE,
    NOT_EQUIVALENT,
    load_margins,
    replicate_spm_tost,
)
from .fbx_motion import CASE_JOINTS, Motion
from .mixed_effects import ValidationError
from .multiview import (
    Calibration,
    View,
    _interpolate,
    calibrate_pairs,
    estimate_lag,
    lowpass,
    sign_window,
    refine_lag,
    rest_window,
    synchronise,
    trim_glitches,
    triangulate_take,
    wrist_speed,
)
from .scoring import PHASE

SCOPE = (
    "Conditional on this performance: the FBX agrees with the two-view video measurement within "
    "the margin, beyond what the video's measured noise explains. Not evidence of equivalence "
    "across performers, signs or sessions."
)
MIN_STILL_S = 5.0  # dedicated noise recording
MIN_STILL_TOTAL_S = 1.0  # stillness inside the sign videos, before and after the sign
MIN_STILL_RUN_S = 0.4
STILL_SPEED = 0.35  # shoulder widths per second; holds measure ~0.1, signing 2-5
MIN_REPLICATES = 5
TREND_HZ = 0.3  # postural sway is removed before measuring detector jitter


@dataclass(frozen=True)
class KeypointNoise:
    sigma_px: np.ndarray  # (2 views, joints)
    phi: np.ndarray  # (2 views, joints) lag-1 autocorrelation per video frame
    source: str

    def combine(self, other: "KeypointNoise") -> "KeypointNoise":
        """Element-wise worst case of two estimates."""
        return KeypointNoise(
            np.maximum(self.sigma_px, other.sigma_px),
            np.maximum(self.phi, other.phi),
            f"max({self.source}, {other.source})",
        )


def ar1_noise(shape: tuple[int, ...], sigma, phi, rng: np.random.Generator) -> np.ndarray:
    """AR(1) along axis 0, stationary standard deviation `sigma`, both broadcast over the rest."""
    sigma = np.broadcast_to(sigma, shape[1:])
    phi = np.broadcast_to(phi, shape[1:])
    noise = np.empty(shape)
    noise[0] = rng.normal(0, 1, shape[1:]) * sigma
    innovation = sigma * np.sqrt(1 - phi**2)
    for frame in range(1, shape[0]):
        noise[frame] = phi * noise[frame - 1] + rng.normal(0, 1, shape[1:]) * innovation
    return noise


def _lag1(residual: np.ndarray) -> np.ndarray:
    """Lag-1 autocorrelation along axis 0, pooled over the last axis (x and y)."""
    finite = np.isfinite(residual[1:]) & np.isfinite(residual[:-1])
    a = np.where(finite, residual[1:], 0.0)
    b = np.where(finite, residual[:-1], 0.0)
    numerator = (a * b).sum(axis=(0, -1))
    denominator = np.sqrt((a * a).sum(axis=(0, -1)) * (b * b).sum(axis=(0, -1)))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.clip(np.nan_to_num(numerator / denominator), 0.0, 0.99)


def still_mask(view: View, *, speed_limit: float = STILL_SPEED, min_run_s: float = MIN_STILL_RUN_S) -> np.ndarray:
    """Frames where the whole body is near-motionless, in runs of at least `min_run_s`."""
    rate = 1.0 / np.median(np.diff(view.times))
    shoulders = [CASE_JOINTS.index("left_shoulder"), CASE_JOINTS.index("right_shoulder")]
    width = np.nanmedian(np.linalg.norm(view.uv[:, shoulders[0]] - view.uv[:, shoulders[1]], axis=-1))
    filled = np.stack([_interpolate(view.times, view.uv[:, :, axis], view.times) for axis in range(2)], -1)
    smooth = lowpass(filled, rate, 1.5)
    speed = np.nanmax(np.linalg.norm(np.gradient(smooth, view.times, axis=0), axis=-1), axis=1) / width
    # Heavy detector jitter makes a genuine hold look like slow movement, so the limit rises with
    # the take's own noise floor (twice its 10th-percentile speed), but never to a quarter of the
    # signing speed, which keeps real movement out.
    finite = speed[np.isfinite(speed)]
    if finite.size:
        floor = 2.0 * np.percentile(finite, 10)
        speed_limit = max(speed_limit, min(floor, 0.25 * np.percentile(finite, 95)))
    still = np.nan_to_num(speed, nan=np.inf) < speed_limit
    edges = np.flatnonzero(np.diff(np.concatenate([[0], still.astype(int), [0]])))
    mask = np.zeros(len(still), dtype=bool)
    for start, stop in zip(edges[::2], edges[1::2]):
        if view.times[stop - 1] - view.times[start] >= min_run_s:
            mask[start:stop] = True
    return mask


def _detrended(times: np.ndarray, track: np.ndarray) -> np.ndarray:
    """Remove postural sway: a 0.3 Hz trend for long runs, a straight line for short ones."""
    if times[-1] - times[0] >= 3.0:
        rate = 1.0 / np.median(np.diff(times))
        filled = np.stack([_interpolate(times, track[:, :, axis], times) for axis in range(2)], -1)
        return track - lowpass(filled, rate, TREND_HZ)
    out = np.full_like(track, np.nan)
    for joint in range(track.shape[1]):
        for axis in range(2):
            y = track[:, joint, axis]
            finite = np.isfinite(y)
            if finite.sum() >= 3:
                fit = np.polyfit(times[finite], y[finite], 1)
                out[finite, joint, axis] = y[finite] - np.polyval(fit, times[finite])
    return out


def estimate_keypoint_noise(
    views: tuple[View, View], masks: tuple[np.ndarray, np.ndarray], *, alpha: float = 0.05, source: str = "still frames"
) -> KeypointNoise:
    """Detector jitter while the performer is still, per view and joint.

    Sigma is reported at its one-sided (1 - alpha) upper confidence bound for the effective number
    of still frames, so a short stillness widens rather than narrows the final bands.
    """
    sigma, phi = [], []
    for view, mask in zip(views, masks):
        if view.times[mask].size < 2 or mask.sum() / (1.0 / np.median(np.diff(view.times))) < MIN_STILL_TOTAL_S:
            raise ValidationError(
                f"Need at least {MIN_STILL_TOTAL_S:.1f} s of stillness in every view (hold before and "
                "after the sign, or supply a noise recording)."
            )
        edges = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(int), [0]])))
        residual = np.concatenate([
            _detrended(view.times[start:stop], view.uv[start:stop]) for start, stop in zip(edges[::2], edges[1::2])
        ])
        point = np.sqrt(np.nanmean(residual**2, axis=(0, 2)))
        memory = _lag1(residual)
        count = 2 * np.isfinite(residual[..., 0]).sum(axis=0)
        effective = np.maximum(count * (1 - memory) / (1 + memory), 3.0)
        sigma.append(point * np.sqrt((effective - 1) / chi2.ppf(alpha, effective - 1)))
        phi.append(memory)
    return KeypointNoise(np.array(sigma), np.array(phi), source)


def recording_noise(views: tuple[View, View], still_s: tuple[float, float]) -> KeypointNoise:
    """Noise recording protocol: the performer holds still during `still_s` (own clocks)."""
    masks = tuple((view.times >= still_s[0]) & (view.times <= still_s[1]) for view in views)
    for view, mask in zip(views, masks):
        if mask.sum() < 2 or np.ptp(view.times[mask]) < MIN_STILL_S:
            raise ValidationError(f"The noise recording needs at least {MIN_STILL_S:.0f} s of stillness.")
    return estimate_keypoint_noise(views, masks, source="noise recording")


def replicate_keypoint_noise(replicates: tuple[tuple[View, View], ...]) -> KeypointNoise:
    """Spread of replicate pose runs during the sign itself (a lower bound on detector noise)."""
    if len(replicates) < MIN_REPLICATES:
        raise ValidationError(f"At least {MIN_REPLICATES} pose replicates are required.")
    sigma, phi = [], []
    for view in range(2):
        stack = np.stack([pair[view].uv for pair in replicates])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # joints missing in every replicate
            deviation = stack - np.nanmean(stack, axis=0)
        correction = np.sqrt(len(replicates) / (len(replicates) - 1))
        sigma.append(correction * np.sqrt(np.nanmean(deviation**2, axis=(0, 1, 3))))
        phi.append(np.mean([_lag1(d) for d in deviation], axis=0))
    return KeypointNoise(np.array(sigma), np.array(phi), "replicate spread")


def session_calibration(
    recordings: list[tuple[View, View]], K1: np.ndarray, K2: np.ndarray, *, refine_focal: bool = True
) -> tuple[Calibration, np.ndarray, np.ndarray, list[float]]:
    """Calibrate once from every recording made without moving the phones.

    View offsets start from wrist-speed cross-correlation, are refined geometrically against a
    first calibration, and the calibration is then re-fitted on the refined sync. Also returns
    the stacked, synced (2, frames, joints, 2) keypoints and confidences in recording order (so
    the calibration can be re-estimated under simulated noise) and each recording's view lag.
    """
    def stacked(lags):
        uv, confidence = [], []
        for (first, second), lag in zip(recordings, lags):
            _, uv2, conf2 = synchronise(first, second, lag=lag)
            uv.append(np.stack([first.uv, uv2]))
            confidence.append(np.stack([first.confidence, conf2]))
        return np.concatenate(uv, axis=1), np.concatenate(confidence, axis=1)

    lags = [synchronise(first, second)[0] for first, second in recordings]
    uv, confidence = stacked(lags)
    calibration = calibrate_pairs(uv, confidence, K1, K2, refine_focal=refine_focal)
    lags = [refine_lag(calibration.cameras, first, second, lag) for (first, second), lag in zip(recordings, lags)]
    uv, confidence = stacked(lags)
    calibration = calibrate_pairs(
        uv, confidence, K1, K2, refine_focal=refine_focal, initial=calibration.parameters
    )
    return calibration, uv, confidence, lags


def _differences(cameras, times, uv, confidence, motion, lag, fbx_angles):
    """Video minus FBX for every angle, over the whole FBX clock."""
    rate = 1.0 / np.median(np.diff(times))
    video = lowpass(triangulate_take(cameras, times, uv, confidence), rate)
    angles = joint_angles(_interpolate(times + lag, video, motion.times), names=tuple(fbx_angles))
    return {name: angles[name] - fbx_angles[name] for name in fbx_angles}


def _apply_offset(differences: dict, window: slice, rest: slice | None) -> tuple[dict, dict]:
    """Sign-window differences minus each angle's pre-sign-hold offset (zero without a rule)."""
    offsets = {
        name: float(np.nanmean(values[rest])) if rest is not None else 0.0
        for name, values in differences.items()
    }
    return {name: values[window] - offsets[name] for name, values in differences.items()}, offsets


def offset_rule(path=MARGINS_FILE) -> str | None:
    rule = json.loads(path.read_text()).get("offset_rule")
    if rule not in (None, "pre_sign_hold"):
        raise ValidationError(f"Unknown offset rule {rule!r}.")
    return rule


def _fill(values: np.ndarray) -> np.ndarray:
    """Linear fill across the last axis; callers have already required >= 90% coverage."""
    out = values.copy()
    index = np.arange(values.shape[-1])
    for row in out.reshape(-1, values.shape[-1]):
        finite = np.isfinite(row)
        if finite.sum() >= 2 and not finite.all():
            row[~finite] = np.interp(index[~finite], index[finite], row[finite])
    return out


def _decide(lower: np.ndarray, upper: np.ndarray, margin: float) -> str:
    if np.all(lower > -margin) and np.all(upper < margin):
        return EQUIVALENT
    if np.any(lower > margin) or np.any(upper < -margin):
        return NOT_EQUIVALENT
    return INCONCLUSIVE


def conditional_tost(observed: np.ndarray, draws: np.ndarray, margin: float, *, alpha: float = 0.05) -> dict:
    """Mean, RMS and whole-curve TOSTs for one angle from Monte Carlo replicates of the estimate.

    `draws` are the estimate recomputed under simulated measurement error; their deviation from
    `observed` stands in for the estimate's error around the truth (parametric bootstrap).

    - mean: the sign-average difference lies within +-margin.
    - rms: the root-mean-square difference over the sign is below margin. The reported RMS and
      its upper bound include measurement noise (conservative); see the bound below.
    - whole_curve: a band simultaneous over time (studentised maximum, alpha per tail) lies
      within +-margin at every phase. Strongest, and needs sub-degree frame noise to pass.
    """
    error = draws - observed
    bias = error.mean(axis=0)
    spread = np.maximum(error.std(axis=0, ddof=1), 1e-6)
    centred = (error - bias) / spread
    above = np.quantile(centred.max(axis=1), 1 - alpha)
    below = np.quantile((-centred).max(axis=1), 1 - alpha)
    corrected = observed - bias
    lower, upper = corrected - above * spread, corrected + below * spread

    mean_error = error.mean(axis=1)
    mean = float(observed.mean())
    mean_ci = (mean - float(np.quantile(mean_error, 1 - alpha)), mean - float(np.quantile(mean_error, alpha)))
    # Noise affects a squared difference in two ways. Its systematic part (flexion reads high under
    # noise, worst near a straight arm) shifts the curve and can shrink a negative error, so it is
    # removed first using the Monte Carlo bias. Its random part only inflates a mean square, so the
    # upper bound (the equivalence side) keeps it in: conservative even though the noise model is
    # itself an upper bound. The lower bound (only used to declare a difference) removes it too,
    # which is conservative in that direction.
    square = float(np.mean(corrected**2))
    draw_square = np.mean((draws - bias) ** 2, axis=1)
    fluctuation = draw_square - draw_square.mean()
    rms_upper = float(np.sqrt(max(square - np.quantile(fluctuation, alpha), 0.0)))
    rms_lower = float(np.sqrt(max(2 * square - np.quantile(draw_square, 1 - alpha), 0.0)))
    rms_corrected = float(np.sqrt(max(square, 0.0)))
    rms_decision = EQUIVALENT if rms_upper < margin else NOT_EQUIVALENT if rms_lower > margin else INCONCLUSIVE

    native = np.linspace(0.0, 1.0, len(observed))
    phase = lambda values: np.interp(PHASE, native, values).tolist()
    return {
        "curve_decision": _decide(lower, upper, margin),
        "mean_decision": _decide(np.array([mean_ci[0]]), np.array([mean_ci[1]]), margin),
        "rms_decision": rms_decision,
        "rms_deg": rms_corrected,
        "rms_ci_deg": [rms_lower, rms_upper],
        "margin_deg": margin,
        "alpha": alpha,
        "monte_carlo_draws": int(len(draws)),
        "mean_difference_deg": mean,
        "mean_ci_deg": list(mean_ci),
        "curve_phase": PHASE.tolist(),
        "curve_deg": phase(corrected),
        "band_lower_deg": phase(lower),
        "band_upper_deg": phase(upper),
        "max_band_abs_deg": float(np.max(np.abs(np.concatenate([lower, upper])))),
        "measurement_sd_deg": [float(spread.min()), float(spread.max())],
        "rmse_deg": float(np.sqrt(np.mean(observed**2))),
        "max_abs_deg": float(np.max(np.abs(observed))),
        "fraction_outside_margin": float(np.mean(np.abs(corrected) > margin)),
        "pearson_r": None,
    }


CLAIMS = ("rms", "mean", "whole_curve")


def primary_claim(path=MARGINS_FILE) -> str:
    claim = json.loads(path.read_text()).get("primary_claim", "rms")
    if claim not in CLAIMS:
        raise ValidationError(f"Unknown primary claim {claim!r}; use one of {CLAIMS}.")
    return claim


def replicate_scalar_tost(values: np.ndarray, margin: float, claim: str, *, alpha: float = 0.05) -> dict:
    """Method 2 for the scalar claims: one-sample t bounds over the replicate statistics."""
    values = np.asarray(values, dtype=float)
    if len(values) < MIN_REPLICATES:
        raise ValidationError(f"At least {MIN_REPLICATES} pose replicates are required.")
    half = student.ppf(1 - alpha, len(values) - 1) * values.std(ddof=1) / np.sqrt(len(values))
    centre = float(values.mean())
    passed = (centre + half < margin) if claim == "rms" else (-margin < centre - half and centre + half < margin)
    return {
        "evidence": "measurement-replicate", "statistic": claim, "replicates": int(len(values)),
        "pass": bool(passed), "bounds_deg": [centre - half, centre + half],
    }


def evaluate_conditional(
    sign: tuple[View, View],
    noise_recording: tuple[View, View] | None,
    replicates: tuple[tuple[View, View], ...],
    K1: np.ndarray,
    K2: np.ndarray,
    motion: Motion,
    *,
    still_s: tuple[float, float] = (0.5, 9.5),
    margins: dict[str, float] | None = None,
    claim: str | None = None,
    refine_focal: bool = True,
    draws: int = 1000,
    calibration_refits: int = 50,
    alpha: float = 0.05,
    seed: int = 20261029,
) -> dict:
    """Full combined protocol for one sign take; see the module docstring."""
    if motion.joints.shape[1] != len(CASE_JOINTS):
        raise ValidationError("Load the FBX with include_elbows=True.")
    motion, trimmed = trim_glitches(motion)
    margins = margins or load_margins()
    claim = claim or primary_claim()
    rng = np.random.default_rng(seed)

    # Measurement-error model, all from outside the FBX.
    if noise_recording is not None:
        rest = recording_noise(noise_recording, still_s)
    else:
        rest = estimate_keypoint_noise(sign, tuple(still_mask(view) for view in sign))
    moving = replicate_keypoint_noise(replicates)
    noise = rest.combine(moving)
    recordings = [sign] + ([noise_recording] if noise_recording is not None else [])
    calibration, session_uv, session_confidence, view_lags = session_calibration(
        recordings, K1, K2, refine_focal=refine_focal
    )

    # Observed estimate on the FBX clock, inside the FBX-defined sign window.
    first, second = sign
    view_lag, uv2, conf2 = synchronise(first, second, lag=view_lags[0])
    uv = np.stack([first.uv, uv2])
    confidence = np.stack([first.confidence, conf2])
    rate = 1.0 / np.median(np.diff(first.times))
    video = lowpass(triangulate_take(calibration.cameras, first.times, uv, confidence), rate)
    fbx_xyz = lowpass(motion.joints, motion.fps)
    lag = estimate_lag(
        wrist_speed(motion.times, fbx_xyz),
        wrist_speed(motion.times, _interpolate(first.times, video, motion.times)),
        motion.fps,
    )
    start, stop = sign_window(motion)
    window = slice(start, stop)
    hold = rest_window(motion, start) if offset_rule() == "pre_sign_hold" else None
    fbx_angles = joint_angles(fbx_xyz, names=tuple(margins))
    raw = _differences(calibration.cameras, first.times, uv, confidence, motion, lag, fbx_angles)
    for name, values in raw.items():
        for label, frames in (("sign window", window), ("pre-sign hold", hold)):
            if frames is not None and np.isfinite(values[frames]).mean() < 0.95:
                raise ValidationError(f"{name}: both videos must cover the whole {label}.")
    observed, offsets = _apply_offset(raw, window, hold)
    observed = {name: _fill(values) for name, values in observed.items()}
    fbx_angles = {name: values[window] for name, values in fbx_angles.items()}

    # Method 1: Monte Carlo of pixel noise through this exact sign. Calibration uncertainty is a
    # parametric bootstrap: the cameras are re-fitted on the same noisy keypoints a draw then
    # triangulates. (A linearised covariance understated the yaw error ~5x in simulation, because
    # depth is nearly ambiguous for one distant signer.) Later draws reuse the re-fitted pool.
    simulated = {name: [] for name in observed}
    simulated_offsets = {name: [] for name in observed}
    pool = []
    frames = uv.shape[1]  # the sign is the first recording in the session stack
    for index in range(draws):
        jitter = np.stack([
            ar1_noise(session_uv.shape[1:], noise.sigma_px[view][:, None], noise.phi[view][:, None], rng)
            for view in range(2)
        ])
        if index < calibration_refits:
            refit = calibrate_pairs(
                session_uv + jitter, session_confidence, K1, K2, refine_focal=refine_focal,
                initial=calibration.parameters,
            )
            pool.append(refit.cameras)
            cameras = refit.cameras
        else:
            cameras = pool[index % len(pool)]
        draw, draw_offsets = _apply_offset(
            _differences(cameras, first.times, uv + jitter[:, :frames], confidence, motion, lag,
                         joint_angles(fbx_xyz, names=tuple(margins))),
            window, hold,
        )
        for name, values in draw.items():
            simulated[name].append(values)
            simulated_offsets[name].append(draw_offsets[name])

    # Method 2: replicate curves through the same cameras, then spm1d TOST.
    replicate_curves = {name: [] for name in observed}
    for rep_first, rep_second in replicates:
        _, rep_uv2, rep_conf2 = synchronise(rep_first, rep_second, lag=view_lags[0])
        curves, _ = _apply_offset(
            _differences(
                calibration.cameras, rep_first.times, np.stack([rep_first.uv, rep_uv2]),
                np.stack([rep_first.confidence, rep_conf2]), motion, lag,
                joint_angles(fbx_xyz, names=tuple(margins)),
            ),
            window, hold,
        )
        for name, values in curves.items():
            replicate_curves[name].append(_fill(values))

    angles = {}
    for name, margin in margins.items():
        result = conditional_tost(observed[name], _fill(np.array(simulated[name])), margin, alpha=alpha)
        result["pearson_r"] = float(np.corrcoef(observed[name] + fbx_angles[name], fbx_angles[name])[0, 1])
        # Offset: basic-bootstrap 90% interval from its Monte Carlo re-estimates.
        shift = np.array(simulated_offsets[name]) - offsets[name]
        result["static_offset_deg"] = offsets[name]
        result["static_offset_ci_deg"] = [
            offsets[name] - float(np.nanquantile(shift, 1 - alpha)), offsets[name] - float(np.nanquantile(shift, alpha))
        ]
        uncorrected = _fill(raw[name][window])
        result["raw_rms_deg"] = float(np.sqrt(np.mean(uncorrected**2)))
        result["raw_mean_difference_deg"] = float(uncorrected.mean())
        native = np.linspace(0.0, 1.0, len(observed[name]))
        result["fbx_curve_deg"] = np.interp(PHASE, native, fbx_angles[name]).tolist()
        result["observed_deg"] = np.interp(PHASE, native, observed[name]).tolist()
        result["video_curve_deg"] = np.interp(PHASE, native, fbx_angles[name] + uncorrected).tolist()
        curves = np.array(replicate_curves[name])
        result["replicate_spm1d"] = replicate_spm_tost(curves, margin, alpha=alpha)
        result["replicate_check"] = (
            result["replicate_spm1d"] if claim == "whole_curve"
            else replicate_scalar_tost(
                np.sqrt(np.mean(curves**2, axis=1)) if claim == "rms" else curves.mean(axis=1),
                margin, claim, alpha=alpha,
            )
        )
        primary = result[{"whole_curve": "curve_decision", "mean": "mean_decision", "rms": "rms_decision"}[claim]]
        if primary == EQUIVALENT and not result["replicate_check"]["pass"]:
            primary = INCONCLUSIVE
        result["decision"] = primary
        angles[name] = result

    decisions = {item["decision"] for item in angles.values()}
    overall = (
        EQUIVALENT if decisions == {EQUIVALENT}
        else NOT_EQUIVALENT if NOT_EQUIVALENT in decisions
        else INCONCLUSIVE
    )
    return {
        "decision": overall,
        "primary_claim": claim,
        "scope": SCOPE,
        "angles": angles,
        "noise_model": {
            "source": noise.source,
            "still_sigma_px": rest.sigma_px.tolist(),
            "replicate_sigma_px": moving.sigma_px.tolist(),
            "used_sigma_px": noise.sigma_px.tolist(),
            "used_phi": noise.phi.tolist(),
            "calibration_refits": int(min(draws, calibration_refits)),
        },
        "diagnostics": {
            **calibration.diagnostics,
            "view_lag_s": float(view_lag),
            "fbx_lag_s": float(lag),
            "window_frames": [start, stop],
            "fbx_glitch_frames_trimmed": trimmed,
            "window_s": [float(motion.times[start]), float(motion.times[stop - 1])],
            "offset_rule": offset_rule(),
            "rest_window_s": None if hold is None else [float(motion.times[hold.start]), float(motion.times[hold.stop - 1])],
        },
    }
