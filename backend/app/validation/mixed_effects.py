"""Paired mixed-effects comparison of suit and non-suit motion error.

One row is one independently recorded performance, evaluated against *one* video.
Taking the log error ratio within that row removes the shared performance/reference
effect before fitting action and performer random intercepts. Frames are never rows.
"""

from __future__ import annotations

import hashlib
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

REQUIRED_COLUMNS = (
    "performance_id", "action_id", "performer_id", "reference_id", "metric",
    "suit_error", "non_suit_error",
)
PRIMARY_METRIC = "wrist_position_error_2d_normalized"
ANALYSIS_VERSION = "paired-lmem-v1"


class ValidationError(ValueError):
    """The inputs or fitted model cannot support the requested inference."""


def load_scores(path: str | Path) -> pd.DataFrame:
    """Validate paired, action-level scores before any model is fitted."""
    path = Path(path)
    try:
        frame = pd.read_csv(path, dtype={key: str for key in REQUIRED_COLUMNS[:5]})
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValidationError(f"Cannot read paired score CSV: {exc}") from exc

    missing = set(REQUIRED_COLUMNS) - set(frame.columns)
    if missing:
        raise ValidationError(f"Missing columns: {', '.join(sorted(missing))}")
    if frame.empty:
        raise ValidationError("No paired performances were supplied.")

    for key in REQUIRED_COLUMNS[:5]:
        frame[key] = frame[key].astype("string").str.strip()
        if frame[key].isna().any() or frame[key].eq("").any():
            raise ValidationError(f"{key} must be present in every row.")

    if frame.performance_id.duplicated().any():
        raise ValidationError("Each performance_id must appear exactly once; frames are not independent rows.")
    if frame.reference_id.duplicated().any():
        raise ValidationError("Each reference video must identify one independent performance.")
    if set(frame.metric) != {PRIMARY_METRIC}:
        raise ValidationError(f"All rows must use the primary metric {PRIMARY_METRIC}.")

    for key in ("suit_error", "non_suit_error"):
        values = pd.to_numeric(frame[key], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.any(values <= 0):
            raise ValidationError(f"{key} must contain finite, strictly positive normalized errors.")
        frame[key] = values

    action_counts = frame.groupby("action_id", observed=True).size()
    if len(action_counts) < 4 or (action_counts < 2).any():
        raise ValidationError(
            "Mixed-effects inference needs at least four actions and two independent "
            "performances of each action. Record more matched performances first."
        )
    if frame.performer_id.nunique() > 1 and (
        frame.groupby("performer_id", observed=True).action_id.nunique() < 2
    ).any():
        raise ValidationError(
            "Each performer must contribute at least two actions to separate performer "
            "variation from action variation."
        )
    frame["log_ratio"] = np.log(frame.suit_error.to_numpy()) - np.log(frame.non_suit_error.to_numpy())
    return frame


def fit_primary_model(
    frame: pd.DataFrame, *, alpha: float = 0.05, meaningful_reduction: float = 0.20,
) -> dict:
    """Estimate the geometric mean suit/non-suit error ratio with crossed effects."""
    if not 0 < alpha < 0.5:
        raise ValidationError("alpha must be between 0 and 0.5.")
    if not 0 < meaningful_reduction < 1:
        raise ValidationError("meaningful_reduction must be between 0 and 1.")

    # Import here so the normal API does not require research-only dependencies.
    try:
        import statsmodels.api as sm
    except ImportError as exc:
        raise ValidationError(
            "Install backend/requirements-validation.txt to run mixed-effects analysis."
        ) from exc

    effects = {"action": "0 + C(action_id)"}
    n_performers = frame.performer_id.nunique()
    if n_performers > 1:
        effects["performer"] = "0 + C(performer_id)"

    # A constant grouping factor makes the variance components crossed rather than
    # accidentally nesting performer within action. Pairing was already consumed by
    # each performance's log(suit/non-suit) ratio.
    model = sm.MixedLM.from_formula(
        "log_ratio ~ 1", groups=np.ones(len(frame), dtype=int),
        vc_formula=effects, data=frame,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result = model.fit(reml=True, method="lbfgs", maxiter=2000, disp=False)
        except (ValueError, RuntimeError, np.linalg.LinAlgError) as exc:
            raise ValidationError(f"Mixed-effects fit failed: {exc}") from exc

    if not result.converged:
        raise ValidationError("Mixed-effects fit did not converge; no superiority claim can be made.")
    beta = float(result.fe_params.iloc[0])
    with warnings.catch_warnings(record=True) as extra_warnings:
        warnings.simplefilter("always")
        standard_error = float(result.bse_fe.iloc[0])
    if not np.isfinite([beta, standard_error]).all() or standard_error <= 0:
        raise ValidationError("The method effect or its uncertainty could not be estimated.")

    if (not np.isfinite(result.vcomp).all() or np.any(result.vcomp < 0)
            or not np.isfinite(result.scale) or result.scale <= 0):
        raise ValidationError("Variance components or residual variance are invalid.")

    warning_messages = list(dict.fromkeys(str(item.message) for item in [*caught, *extra_warnings]))
    reliable_interval = not any(
        "Hessian matrix at the estimated parameter values is not positive definite" in message
        for message in warning_messages
    )
    z_two_sided = norm.ppf(1 - alpha / 2)
    z_one_sided = norm.ppf(1 - alpha)
    ratio = math.exp(beta)
    ratio_ci = [math.exp(beta - z_two_sided * standard_error),
                math.exp(beta + z_two_sided * standard_error)]
    ratio_upper = math.exp(beta + z_one_sided * standard_error)
    margin = 1 - meaningful_reduction

    return {
        "analysis_version": ANALYSIS_VERSION,
        "metric": PRIMARY_METRIC,
        "unit": "reference shoulder widths (2D)",
        "model": "log(suit_error / non_suit_error) ~ 1 + (1 | action) + (1 | performer, if estimable)",
        "fit_method": "restricted maximum likelihood; crossed variance components; Wald intervals",
        "n_performances": len(frame),
        "n_actions": frame.action_id.nunique(),
        "n_performers": n_performers,
        "paired_geometric_mean_error_ratio": ratio,
        "relative_error_reduction": 1 - ratio,
        "ratio_confidence_interval": ratio_ci,
        "confidence_level": 1 - alpha,
        "one_sided_ratio_upper_bound": ratio_upper,
        "one_sided_alpha": alpha,
        "one_sided_p_suit_better": float(norm.cdf(beta / standard_error)),
        "meaningful_reduction_threshold": meaningful_reduction,
        "superiority_supported": bool(reliable_interval and ratio_upper < 1),
        "meaningful_improvement_supported": bool(reliable_interval and ratio_upper < margin),
        "interval_diagnostics_valid": reliable_interval,
        "warnings": warning_messages + (
            ["One performer was measured; findings do not establish between-performer generality."]
            if n_performers == 1 else []
        ),
        "variance_components": {
            key: float(value) for key, value in zip(sorted(effects), result.vcomp)
        },
        "residual_variance": float(result.scale),
        "interpretation_limit": (
            "A statistical bound is not a research conclusion until pairing, video independence, "
            "QC, prespecified margins, and held-out sampling are verified."
        ),
    }


def analyse_csv(path: str | Path, *, alpha: float = 0.05,
                meaningful_reduction: float = 0.20) -> tuple[pd.DataFrame, dict]:
    frame = load_scores(path)
    report = fit_primary_model(frame, alpha=alpha, meaningful_reduction=meaningful_reduction)
    report["input_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return frame, report
