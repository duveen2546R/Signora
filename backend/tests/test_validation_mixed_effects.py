"""The primary analysis must preserve pairing and action/performer replication."""

import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from app.validation.mixed_effects import PRIMARY_METRIC, ValidationError, analyse_csv, load_scores
from app.validation.power import simulate_power


def write_scores(path, *, suit_ratio=0.70):
    rng = np.random.default_rng(17)
    performer_offsets = rng.normal(0, 0.05, size=3)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "performance_id", "action_id", "performer_id", "reference_id", "metric",
            "suit_error", "non_suit_error",
        ])
        writer.writeheader()
        for action in range(12):
            action_offset = rng.normal(0, 0.07)
            for performer in range(3):
                for repetition in range(3):
                    identifier = f"a{action}-p{performer}-r{repetition}"
                    baseline = float(0.10 + 0.01 * action + rng.uniform(0, 0.03))
                    ratio = suit_ratio * np.exp(
                        action_offset + performer_offsets[performer] + rng.normal(0, 0.04)
                    )
                    writer.writerow({
                        "performance_id": identifier, "action_id": f"a{action}",
                        "performer_id": f"p{performer}", "reference_id": f"video-{identifier}",
                        "metric": PRIMARY_METRIC, "suit_error": baseline * ratio,
                        "non_suit_error": baseline,
                    })


def test_model_recovers_known_suit_advantage_and_audits_pairing(tmp_path):
    path = tmp_path / "scores.csv"
    write_scores(path)
    rows, result = analyse_csv(path)
    assert len(rows) == 108
    assert result["n_actions"] == 12 and result["n_performers"] == 3
    assert 0.6 < result["paired_geometric_mean_error_ratio"] < 0.8
    assert result["superiority_supported"] is True
    assert result["meaningful_improvement_supported"] is True
    assert result["one_sided_ratio_upper_bound"] < 0.8
    assert len(result["input_sha256"]) == 64
    assert result["interval_diagnostics_valid"]


def test_reversing_methods_reverses_the_superiority_conclusion(tmp_path):
    path = tmp_path / "scores.csv"
    write_scores(path, suit_ratio=1.30)
    _, result = analyse_csv(path)
    assert result["paired_geometric_mean_error_ratio"] > 1
    assert result["superiority_supported"] is False
    assert result["meaningful_improvement_supported"] is False


@pytest.mark.parametrize("replacement,match", [
    ({"performance_id": "a0-p0-r0"}, "performance_id"),
    ({"reference_id": "video-a0-p0-r0"}, "reference video"),
    ({"suit_error": "0"}, "strictly positive"),
    ({"non_suit_error": "nan"}, "finite"),
    ({"metric": "pixel_error"}, "primary metric"),
])
def test_invalid_or_pseudoreplicated_pairs_are_rejected(tmp_path, replacement, match):
    path = tmp_path / "scores.csv"
    write_scores(path)
    rows = list(csv.DictReader(path.open(newline="")))
    rows[1].update(replacement)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValidationError, match=match):
        load_scores(path)


def test_missing_action_repetitions_are_rejected(tmp_path):
    path = tmp_path / "scores.csv"
    write_scores(path)
    rows = list(csv.DictReader(path.open(newline="")))
    rows = [row for row in rows if row["action_id"] != "a0" or row["performance_id"] == "a0-p0-r0"]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValidationError, match="two independent"):
        load_scores(path)


def test_cli_writes_auditable_report(tmp_path):
    scores = tmp_path / "scores.csv"
    output = tmp_path / "results"
    write_scores(scores)
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).parents[1] / "tools" / "validate_motion.py"),
         str(scores), "--output", str(output)],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((output / "primary_lmem.json").read_text())
    assert report["superiority_supported"] is True
    assert len(list(csv.DictReader((output / "paired_performance_scores.csv").open()))) == 108


def test_degenerate_constant_effect_refuses_superiority_claim(tmp_path):
    path = tmp_path / "scores.csv"
    write_scores(path)
    rows = list(csv.DictReader(path.open(newline="")))
    for row in rows:
        row["suit_error"] = "0.5"
        row["non_suit_error"] = "1.0"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValidationError, match="converge|uncertainty|fit failed"):
        analyse_csv(path)


def test_power_requires_effect_above_meaningful_threshold(tmp_path):
    path = tmp_path / "scores.csv"
    write_scores(path)
    with pytest.raises(ValidationError, match="meaningful threshold"):
        simulate_power(str(path), action_counts=(8,), performers=3, repetitions=3,
                       assumed_true_reduction=0.20, meaningful_threshold=0.20,
                       simulations=20)
