"""Exploratory phase-curve analyses; never a substitute for the primary LMEM."""

from __future__ import annotations

import csv
import json
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np

from .mixed_effects import ValidationError

WAVEFORM_FIELDS = tuple(
    (side, axis) for side in ("left", "right") for axis in ("x", "y")
)


def _read_audit(directory: Path) -> list[dict]:
    try:
        source = json.loads((directory / "qc.json").read_text())
    except (OSError, ValueError) as exc:
        raise ValidationError(f"Cannot read scoring audit: {exc}") from exc
    return source["trials"]


def _read_trace(path: Path) -> dict[str, np.ndarray]:
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 101:
        raise ValidationError(f"{path}: expected the prespecified 101 phase samples.")
    arrays = {}
    for field in rows[0]:
        if field == "valid":
            arrays[field] = np.array([int(row[field]) for row in rows], dtype=bool)
        else:
            arrays[field] = np.array([float(row[field]) if row[field] else np.nan for row in rows])
    return arrays


def _shared_hand_dtw(reference: np.ndarray, method: np.ndarray,
                     max_warp_fraction: float = 0.10) -> dict:
    """One constrained warp path for both wrists, used only as sensitivity."""
    n = len(reference)
    if reference.shape != method.shape or reference.shape[1] != 4 or n < 10:
        raise ValidationError("DTW needs matched Nx4 left/right wrist coordinates.")
    radius = max(1, int(np.ceil(max_warp_fraction * n)))
    distance = np.linalg.norm(reference[:, None, :] - method[None, :, :], axis=2)
    cost = np.full((n + 1, n + 1), np.inf)
    cost[0, 0] = 0
    previous = np.zeros((n + 1, n + 1, 2), dtype=int)
    for i in range(1, n + 1):
        for j in range(max(1, i - radius), min(n, i + radius) + 1):
            candidates = (
                (cost[i - 1, j - 1], i - 1, j - 1),
                (cost[i - 1, j], i - 1, j),
                (cost[i, j - 1], i, j - 1),
            )
            best = min(candidates, key=lambda item: item[0])
            cost[i, j] = distance[i - 1, j - 1] + best[0]
            previous[i, j] = best[1:]
    if not np.isfinite(cost[n, n]):
        raise ValidationError("No path exists within the DTW warping limit.")
    indices = []
    i = j = n
    while i and j:
        indices.append((i - 1, j - 1))
        i, j = map(int, previous[i, j])
    indices.reverse()
    aligned = np.array([np.linalg.norm(
        reference[a].reshape(2, 2) - method[b].reshape(2, 2), axis=1
    ) for a, b in indices])
    return {
        "mean_wrist_error": float(np.mean(aligned)),
        "mean_absolute_phase_warp": float(np.mean([abs(a - b) for a, b in indices]) / (n - 1)),
        "path_length": len(indices),
    }


def constrained_dtw_sensitivity(directory: str | Path) -> dict:
    directory = Path(directory)
    results = []
    for item in _read_audit(directory):
        trace = _read_trace(directory / item["trace_file"])
        valid = trace["valid"]
        runs = np.split(np.flatnonzero(valid), np.where(np.diff(np.flatnonzero(valid)) != 1)[0] + 1)
        longest = max(runs, key=len)
        if len(longest) < 70:
            results.append({"performance_id": item["performance_id"],
                            "status": "insufficient_contiguous_phase_coverage"})
            continue
        reference = np.column_stack([
            trace[f"reference_{side}_{axis}"][longest] for side, axis in WAVEFORM_FIELDS
        ])
        record = {"performance_id": item["performance_id"], "status": "sensitivity",
                  "phase_start": int(longest[0]), "phase_end": int(longest[-1])}
        for method in ("suit", "non_suit"):
            generated = np.column_stack([
                trace[f"{method}_{side}_{axis}"][longest] for side, axis in WAVEFORM_FIELDS
            ])
            record[method] = _shared_hand_dtw(reference, generated)
        results.append(record)
    return {"method": "shared-left-and-right-wrist constrained DTW",
            "maximum_phase_warp": 0.10,
            "interpretation": "Spatial sensitivity only; original-time duration error stays separate.",
            "trials": results}


def functional_limits_of_agreement(directory: str | Path, *, bootstraps: int = 1000,
                                   seed: int = 20261003) -> dict:
    """Pointwise functional bias/LoA with whole-performer bootstrap intervals."""
    directory = Path(directory)
    if bootstraps < 100:
        raise ValidationError("At least 100 bootstrap draws are required.")
    by_action: dict[str, list[tuple[str, dict[str, np.ndarray]]]] = defaultdict(list)
    for item in _read_audit(directory):
        trace = _read_trace(directory / item["trace_file"])
        by_action[item["action_id"]].append((item["performer_id"], trace))
    rng = np.random.default_rng(seed)
    results = {}
    for action, entries in by_action.items():
        if len(entries) < 5:
            results[action] = {"status": "insufficient_trials", "n": len(entries)}
            continue
        clusters = sorted({performer for performer, _ in entries})
        if len(clusters) < 2:
            results[action] = {"status": "needs_multiple_performers", "n": len(entries)}
            continue
        action_result: dict[str, object] = {"status": "descriptive", "n": len(entries),
                                            "n_performers": len(clusters), "waveforms": {}}
        for method in ("suit", "non_suit"):
            for side, axis in WAVEFORM_FIELDS:
                key = f"{method}_{side}_{axis}"
                values = np.array([
                    trace[f"{method}_{side}_{axis}"] - trace[f"reference_{side}_{axis}"]
                    for _, trace in entries
                ])
                # Report only phases with adequate observed data across trials.
                coverage = np.isfinite(values).mean(axis=0)
                usable = coverage >= 0.8
                if usable.sum() < 70:
                    action_result["waveforms"][key] = {"status": "insufficient_phase_coverage"}
                    continue
                def limits(selected: np.ndarray) -> np.ndarray:
                    with warnings.catch_warnings(), np.errstate(invalid="ignore"):
                        warnings.simplefilter("ignore", RuntimeWarning)
                        average = np.nanmean(selected, axis=0)
                        spread = np.nanstd(selected, axis=0, ddof=1)
                    return np.stack((average, average - 1.96 * spread,
                                     average + 1.96 * spread))
                observed = limits(values)
                cluster_indexes = {performer: [i for i, (member, _) in enumerate(entries)
                                               if member == performer] for performer in clusters}
                draws = np.full((bootstraps, 3, 101), np.nan)
                for iteration in range(bootstraps):
                    sampled = rng.choice(clusters, size=len(clusters), replace=True)
                    indexes = [i for performer in sampled for i in cluster_indexes[performer]]
                    if len(indexes) >= 2:
                        draws[iteration] = limits(values[indexes])
                observed[:, ~usable] = np.nan
                low = np.full((3, 101), np.nan)
                high = np.full((3, 101), np.nan)
                with warnings.catch_warnings(), np.errstate(invalid="ignore"):
                    warnings.simplefilter("ignore", RuntimeWarning)
                    low[:, usable] = np.nanpercentile(draws[:, :, usable], 2.5, axis=0)
                    high[:, usable] = np.nanpercentile(draws[:, :, usable], 97.5, axis=0)
                action_result["waveforms"][key] = {
                    "status": "descriptive", "phase_coverage": coverage.tolist(),
                    "bias": observed[0].tolist(), "lower_loa": observed[1].tolist(),
                    "upper_loa": observed[2].tolist(),
                    "bootstrap_lower": low.tolist(), "bootstrap_upper": high.tolist(),
                }
        results[action] = action_result
    return {"method": "phase-indexed signed functional limits of agreement",
            "interpretation": "Describes reference-relative bias and spread; does not test superiority. "
                              "NaN phase values are omitted from JSON as null by the CLI.",
            "cluster_unit": "performer", "bootstrap_draws": bootstraps, "seed": seed,
            "actions": results}


def spm1d_paired_curves(directory: str | Path, *, alpha: float = 0.05) -> dict:
    """SPM1D paired error curves, averaging repetitions within performer/action."""
    try:
        import spm1d
    except ImportError as exc:
        raise ValidationError("Install spm1d from backend/requirements-validation-secondary.txt.") from exc
    directory = Path(directory)
    by_action: dict[str, dict[str, list[dict[str, np.ndarray]]]] = defaultdict(lambda: defaultdict(list))
    for item in _read_audit(directory):
        by_action[item["action_id"]][item["performer_id"]].append(
            _read_trace(directory / item["trace_file"])
        )
    results = {}
    for action, performers in by_action.items():
        if len(performers) < 5:
            results[action] = {"status": "requires_five_independent_performers",
                               "n_performers": len(performers)}
            continue
        curves = {}
        for method in ("suit", "non_suit"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                curves[method] = np.array([
                    np.nanmean([
                        (trace[f"{method}_left_error"] + trace[f"{method}_right_error"]) / 2
                        for trace in trials
                    ], axis=0)
                    for trials in performers.values()
                ])
        common = np.isfinite(curves["suit"]).all(axis=0) & np.isfinite(curves["non_suit"]).all(axis=0)
        # SPM1D expects a contiguous domain with the same measured phases for every pair.
        runs = np.split(np.flatnonzero(common), np.where(np.diff(np.flatnonzero(common)) != 1)[0] + 1)
        longest = max(runs, key=len)
        if len(longest) < 70:
            results[action] = {"status": "insufficient_contiguous_phase_coverage",
                               "longest_phase_samples": len(longest)}
            continue
        suit, non_suit = curves["suit"][:, longest], curves["non_suit"][:, longest]
        inference = spm1d.stats.ttest_paired(suit, non_suit).inference(
            alpha=alpha, two_tailed=True, interp=True
        )
        results[action] = {
            "status": "exploratory", "n_independent_performers": len(performers),
            "phase_start": int(longest[0]), "phase_end": int(longest[-1]),
            "paired_mean_difference": np.mean(suit - non_suit, axis=0).tolist(),
            "t_curve": np.asarray(inference.z).tolist(),
            "critical_threshold": float(inference.zstar),
            "clusters": [{"endpoints": list(map(float, cluster.endpoints)),
                          "p": float(cluster.P)} for cluster in inference.clusters],
        }
    return {"method": "SPM1D paired t-test on performer-averaged error curves",
            "interpretation": "Exploratory localization within a homologous action; multiple actions need "
                              "a prespecified multiplicity correction.",
            "alpha": alpha, "actions": results}
