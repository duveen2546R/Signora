import csv
from pathlib import Path
import numpy as np
import pytest

from app.validation.single_pair_stats import (
    run_single_pair_validation,
    _run_ftost,
    _run_paired_ttest,
    POSITION_CHANNELS,
)


def _make_trace_csv(path: Path, fbx_curves: np.ndarray, ref_curves: np.ndarray):
    """Write a dummy phase_normalized_traces.csv with N channels over 101 phases."""
    rows = []
    for t in range(101):
        row = {"phase": t / 100.0, "valid": 1}
        for i, (fbx_col, ref_col, _) in enumerate(POSITION_CHANNELS):
            row[fbx_col] = fbx_curves[i, t]
            row[ref_col] = ref_curves[i, t]
        rows.append(row)

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_single_pair_stats_equivalent_when_close(tmp_path):
    """When FBX and Ref are within the delta boundary across all phases, fTOST should pass."""
    np.random.seed(42)
    t = np.linspace(0, 1, 101)
    base = np.sin(2 * np.pi * t)

    # 8 channels with small noise (well within delta=0.20)
    ref = np.array([base + 0.1 * i for i in range(8)])
    fbx = ref + np.random.normal(0, 0.02, size=ref.shape)

    csv_path = tmp_path / "phase_normalized_traces.csv"
    _make_trace_csv(csv_path, fbx, ref)

    result = run_single_pair_validation(
        tmp_path,
        sign_name="TestSign",
        position_delta=0.20,
        alpha=0.05,
    )

    assert result["status"] == "completed"
    assert result["verdict"] == "EQUIVALENT"
    assert result["ftost"]["is_equivalent"] is True
    assert result["ftost"]["equivalence_fraction"] == 1.0
    assert (tmp_path / "ftost_spm1d_result.png").is_file()


def test_single_pair_stats_not_equivalent_when_divergent(tmp_path):
    """When FBX diverges beyond delta, fTOST should fail."""
    np.random.seed(42)
    t = np.linspace(0, 1, 101)
    base = np.sin(2 * np.pi * t)

    ref = np.array([base + 0.1 * i for i in range(8)])
    # Add a huge shift (0.50 shoulder widths) in the middle phases
    fbx = ref.copy()
    fbx[:, 30:70] += 0.50

    csv_path = tmp_path / "phase_normalized_traces.csv"
    _make_trace_csv(csv_path, fbx, ref)

    result = run_single_pair_validation(
        tmp_path,
        sign_name="DivergentSign",
        position_delta=0.20,
        alpha=0.05,
    )

    assert result["status"] == "completed"
    assert result["verdict"] == "NOT EQUIVALENT"
    assert result["ftost"]["is_equivalent"] is False
    assert result["ftost"]["equivalence_fraction"] < 1.0
    assert len(result["ftost"]["failing_regions"]) > 0


def test_single_pair_stats_handles_missing_traces(tmp_path):
    """When trace file doesn't exist, gracefully report no_traces."""
    result = run_single_pair_validation(tmp_path)
    assert result["status"] == "no_traces"
