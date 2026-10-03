"""Pilot-informed simulation for planning an independent held-out validation study."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .mixed_effects import PRIMARY_METRIC, ValidationError, analyse_csv, fit_primary_model


def simulate_power(pilot_scores: str, *, action_counts: tuple[int, ...] = (8, 16, 32, 48),
                   performers: int = 3, repetitions: int = 3,
                   assumed_true_reduction: float = 0.30,
                   meaningful_threshold: float = 0.20, simulations: int = 100,
                   seed: int = 20261003) -> dict:
    """Refit the same primary LMEM on crossed synthetic held-out study designs."""
    if not action_counts or min(action_counts) < 4 or performers < 2 or repetitions < 2:
        raise ValidationError("Use >=4 actions, >=2 performers, and >=2 repetitions per cell.")
    if simulations < 20 or not 0 < meaningful_threshold < assumed_true_reduction < 1:
        raise ValidationError(
            "Use >=20 simulations and 0 < meaningful threshold < assumed true reduction < 1."
        )
    _, pilot = analyse_csv(pilot_scores)
    variances = pilot["variance_components"]
    if "performer" not in variances:
        raise ValidationError("Power planning across performers needs a multi-performer pilot.")
    action_sd = math.sqrt(max(0.0, variances["action"]))
    performer_sd = math.sqrt(max(0.0, variances["performer"]))
    residual_sd = math.sqrt(max(0.0, pilot["residual_variance"]))
    rng = np.random.default_rng(seed)
    design_results = []
    for n_actions in action_counts:
        superiority = meaningful = convergence = 0
        for _ in range(simulations):
            action_effect = rng.normal(0, action_sd, size=n_actions)
            performer_effect = rng.normal(0, performer_sd, size=performers)
            rows = []
            for action in range(n_actions):
                for performer in range(performers):
                    for repetition in range(repetitions):
                        label = f"a{action}-p{performer}-r{repetition}"
                        log_ratio = (math.log1p(-assumed_true_reduction) + action_effect[action]
                                     + performer_effect[performer] + rng.normal(0, residual_sd))
                        rows.append({
                            "performance_id": label, "action_id": f"a{action}",
                            "performer_id": f"p{performer}", "reference_id": f"video-{label}",
                            "metric": PRIMARY_METRIC, "suit_error": math.exp(log_ratio),
                            "non_suit_error": 1.0, "log_ratio": log_ratio,
                        })
            try:
                fit = fit_primary_model(pd.DataFrame(rows), meaningful_reduction=meaningful_threshold)
            except ValidationError:
                continue
            convergence += int(fit["interval_diagnostics_valid"])
            superiority += int(fit["superiority_supported"])
            meaningful += int(fit["meaningful_improvement_supported"])
        design_results.append({
            "actions": n_actions, "performers": performers, "repetitions_per_action_performer": repetitions,
            "independent_performances": n_actions * performers * repetitions,
            "model_fit_and_interval_valid_fraction": convergence / simulations,
            "estimated_superiority_power": superiority / simulations,
            "estimated_meaningful_improvement_power": meaningful / simulations,
        })
    return {
        "analysis": "pilot-informed crossed-action-and-performer mixed-model simulation",
        "pilot_input_sha256": pilot["input_sha256"],
        "pilot_variance_components": variances,
        "pilot_residual_variance": pilot["residual_variance"],
        "simulated_true_reduction": assumed_true_reduction,
        "meaningful_improvement_threshold": meaningful_threshold,
        "simulations_per_design": simulations, "seed": seed,
        "caution": "Planning estimate, not a guarantee; pilot variance may be unstable.",
        "designs": design_results,
    }
