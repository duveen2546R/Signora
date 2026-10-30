"""Single-take, two-view equivalence: geometry, sync, error control and gross-error detection."""

import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app.validation.angles3d import flexion, joint_angles
from app.validation.equivalence_single_take import (
    EQUIVALENT,
    compare_angle,
    load_margins,
    replicate_spm_tost,
)
from app.validation.fbx_motion import CASE_JOINTS, load_motion
from app.validation.mixed_effects import ValidationError
from app.validation.multiview import (
    _interpolate,
    estimate_lag,
    evaluate_take,
    reconstruct,
    self_calibrate,
)
from app.validation.single_take_simulation import Scenario, simulate

ROOT = Path(__file__).resolve().parents[2]
SLOW = bool(os.environ.get("SIGNSURE_SLOW"))


@pytest.fixture(scope="module")
def motion():
    return load_motion(ROOT / "MotionCaptureFbx/action.fbx", include_elbows=True)


def ar1(n, phi, sd, rng):
    noise = np.empty(n)
    noise[0] = rng.normal(0, sd)
    for i in range(1, n):
        noise[i] = phi * noise[i - 1] + rng.normal(0, sd * np.sqrt(1 - phi**2))
    return noise


def test_flexion_is_invariant_to_frame_scale_and_handedness():
    shoulder, elbow = np.zeros(3), np.array([0.3, 0.0, 0.0])
    assert flexion(shoulder, elbow, np.array([0.6, 0.0, 0.0])) == pytest.approx(0.0, abs=1e-6)
    assert flexion(shoulder, elbow, np.array([0.3, 0.25, 0.0])) == pytest.approx(90.0)
    rng = np.random.default_rng(0)
    xyz = rng.normal(size=(20, len(CASE_JOINTS), 3))
    mirror = Rotation.random(random_state=1).as_matrix() @ np.diag([1.0, 1.0, -1.0])
    moved = 3.7 * xyz @ mirror.T + np.array([1.0, -2.0, 5.0])
    for name, values in joint_angles(xyz).items():
        np.testing.assert_allclose(joint_angles(moved)[name], values, atol=1e-9)


def test_lag_estimate_is_subframe():
    t = np.arange(0, 4, 1 / 30)
    signal = lambda s: np.exp(-((s - 2.0) ** 2) / 0.05) + 0.5 * np.exp(-((s - 2.8) ** 2) / 0.02)
    # other(t) = signal(t + 0.123), so 0.123 s must be added to other's clock
    assert estimate_lag(signal(t), signal(t + 0.123), 30) == pytest.approx(0.123, abs=0.01)


def test_board_free_calibration_recovers_oblique_view(motion):
    """Through the real path (coarse sync, calibration, geometric sync refinement, re-fit)."""
    from app.validation.conditional_equivalence import session_calibration

    for oblique in (30.0, 45.0, 80.0):
        take = simulate(motion, replace(Scenario(), oblique_deg=oblique), seed=1)
        calibration, _, _, lags = session_calibration([(take.first, take.second)], take.K1, take.K2, refine_focal=False)
        # Narrow baselines leave depth less constrained, hence the 70-90 deg protocol.
        tolerance = 5.0 if oblique < 40 else 3.5
        assert calibration.diagnostics["baseline_angle_deg"] == pytest.approx(oblique, abs=tolerance)
        assert calibration.diagnostics["reprojection_rms_px"] < 4.0
        assert lags[0] == pytest.approx(Scenario().second_view_delay_s, abs=1 / 60)


def test_reconstruction_syncs_views_and_rejects_uncovered_window(motion):
    sim = simulate(motion, seed=2)
    first, second, K1, K2, padded = sim.first, sim.second, sim.K1, sim.K2, sim.motion
    take = reconstruct(first, second, K1, K2, refine_focal=False)
    assert take.diagnostics["view_lag_s"] == pytest.approx(Scenario().second_view_delay_s, abs=1 / 60)
    assert take.diagnostics["triangulated_fraction"] > 0.9
    cut = first.times < 2.0  # phone stopped mid-sign
    short = replace(first, times=first.times[cut], uv=first.uv[cut], confidence=first.confidence[cut])
    with pytest.raises(ValidationError, match="cover the whole sign window"):
        evaluate_take(short, second, K1, K2, padded, refine_focal=False)


def test_tost_false_equivalence_rate_is_held_at_alpha():
    """At the null boundaries with pose-like autocorrelation, at most ~5% may pass.

    The block bootstrap is checked on the same draws to document why it is not used for
    decisions: with ~5 effective frames it under-covers well beyond alpha.
    """
    n, phi, margin, runs = 90, 0.9, 5.0, 200
    fbx = 50 + 40 * np.sin(np.linspace(0, np.pi, n))
    rng = np.random.default_rng(7)
    nulls = {
        "bias at margin": lambda: margin + ar1(n, phi, 1.5, rng),
        "rms at margin": lambda: ar1(n, phi, margin, rng),
    }
    for label, draw in nulls.items():
        passed = bootstrap_passed = 0
        for seed in range(runs):
            result = compare_angle(fbx + draw(), fbx, margin, 30.0, draws=300, seed=seed)
            passed += result["decision"] == EQUIVALENT
            low, high = result["mean_bootstrap_ci_deg"]
            bootstrap_passed += -margin < low and high < margin
        assert passed / runs <= 0.06, label
        if label == "bias at margin":
            assert bootstrap_passed / runs > 0.08


def test_tost_has_power_when_noise_decorrelates():
    n, margin, runs = 150, 5.0, 100
    fbx = 50 + 40 * np.sin(np.linspace(0, np.pi, n))
    rng = np.random.default_rng(11)
    passed = sum(
        compare_angle(fbx + ar1(n, 0.7, 1.5, rng), fbx, margin, 30.0, draws=200, seed=k)["decision"]
        == EQUIVALENT
        for k in range(runs)
    )
    assert passed / runs >= 0.9


def test_gross_elbow_error_is_never_declared_equivalent(motion):
    for seed in (1, 2):
        sim = simulate(motion, injected={"right": 20.0}, seed=seed)
        first, second, K1, K2, padded = sim.first, sim.second, sim.K1, sim.K2, sim.motion
        report = evaluate_take(first, second, K1, K2, padded, refine_focal=False, draws=200)
        right = report["angles"]["right_elbow_flexion"]
        assert report["decision"] != EQUIVALENT
        assert right["decision"] != EQUIVALENT
        assert right["mean_difference_deg"] > 10.0
        assert report["diagnostics"]["fbx_lag_s"] == pytest.approx(-Scenario().video_lead_s, abs=1 / 30)


def test_replicate_spm_tost_is_measurement_only_sensitivity():
    rng = np.random.default_rng(3)
    close = rng.normal(0, 0.5, (12, 90)).cumsum(axis=1) * 0.05
    assert replicate_spm_tost(close, 5.0)["pass"]
    assert replicate_spm_tost(close + 5.0, 5.0)["pass"] is False
    assert replicate_spm_tost(close, 5.0)["evidence"] == "measurement-replicate"
    with pytest.raises(ValidationError):
        replicate_spm_tost(close[:3], 5.0)


def test_margins_are_prespecified_and_positive():
    margins = load_margins()
    from app.validation.angles3d import ANGLES

    assert set(margins) == set(ANGLES)  # the whole tracked upper body
    assert all(value > 0 for value in margins.values())


@pytest.mark.skipif(not SLOW, reason="set SIGNSURE_SLOW=1 for the full pipeline simulation")
def test_pipeline_false_equivalence_at_margin(motion):
    margin = load_margins()["right_elbow_flexion"]
    runs = 100
    passed = 0
    for seed in range(runs):
        sim = simulate(motion, injected={"right": margin}, seed=1000 + seed)
        first, second, K1, K2, padded = sim.first, sim.second, sim.K1, sim.K2, sim.motion
        report = evaluate_take(first, second, K1, K2, padded, refine_focal=False, draws=200)
        passed += report["angles"]["right_elbow_flexion"]["decision"] == EQUIVALENT
    assert passed / runs <= 0.05
