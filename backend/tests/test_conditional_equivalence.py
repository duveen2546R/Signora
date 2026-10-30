"""Combined single-take protocol: noise model, conservative bounds, end-to-end and API wiring."""

import json
import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import analysis
from app.services import analysis_service as service
from app.services.analysis_worker import single_take_summary
from app.validation.conditional_equivalence import (
    conditional_tost,
    estimate_keypoint_noise,
    evaluate_conditional,
    primary_claim,
    replicate_keypoint_noise,
    replicate_scalar_tost,
    still_mask,
)
from app.validation.equivalence_single_take import EQUIVALENT, INCONCLUSIVE, NOT_EQUIVALENT
from app.validation.fbx_motion import load_motion
from app.validation.mixed_effects import ValidationError
from app.validation.single_take_simulation import Scenario, simulate

ROOT = Path(__file__).resolve().parents[2]
QUIET = replace(Scenario(), noise_px=1.5, joint_offset_m=0.0, hold_s=1.0)


@pytest.fixture(scope="module")
def motion():
    return load_motion(ROOT / "MotionCaptureFbx/action.fbx", include_elbows=True)


def test_stillness_is_found_in_the_holds_and_not_during_the_sign(motion):
    sim = simulate(motion, replace(Scenario(), hold_s=1.0), seed=3)
    mask = still_mask(sim.first)
    held = sim.first.times < Scenario().video_lead_s + 0.8  # phone running, suit not yet moving
    assert mask[held].mean() > 0.7
    middle = len(mask) // 2
    assert not mask[middle - 10 : middle + 10].any()


def test_stillness_survives_heavy_detector_jitter(motion):
    """Regression: at 6 px the fixed 0.35 limit split real holds into fragments and the run failed."""
    sim = simulate(motion, replace(Scenario(), hold_s=1.0, noise_px=6.0), seed=1)
    masks = tuple(still_mask(view) for view in (sim.first, sim.second))
    estimate_keypoint_noise((sim.first, sim.second), masks)  # raises when stillness is missing
    middle = len(masks[0]) // 2
    assert not masks[0][middle - 10 : middle + 10].any()


def test_noise_model_bounds_detector_jitter_from_above(motion):
    sim = simulate(motion, replace(Scenario(), hold_s=1.0, noise_px=3.0), replicates=5, seed=4)
    rest = estimate_keypoint_noise((sim.first, sim.second), tuple(still_mask(v) for v in (sim.first, sim.second)))
    assert np.all(rest.sigma_px > 2.4) and np.median(rest.sigma_px) < 5.0  # 95% upper bound of 3 px
    assert np.median(rest.phi) == pytest.approx(0.7, abs=0.15)
    moving = replicate_keypoint_noise(sim.replicates)
    assert np.median(moving.sigma_px) == pytest.approx(1.5, rel=0.25)  # TTA spread is a lower bound
    assert np.all(rest.combine(moving).sigma_px >= rest.sigma_px)
    with pytest.raises(ValidationError, match="stillness"):
        estimate_keypoint_noise((sim.first, sim.second), (np.zeros(len(sim.first.times), bool),) * 2)


def test_rms_bound_stays_conservative_when_noise_is_overstated():
    """Regression: subtracting an overstated noise variance made RMS pass at the margin."""
    rng = np.random.default_rng(0)
    margin, n = 5.0, 90
    observed = margin + rng.normal(0, 0.3, n)  # true RMS sits exactly at the margin
    draws = observed + rng.normal(0, 4.0, (400, n))  # noise model 10x too pessimistic
    result = conditional_tost(observed, draws, margin)
    assert result["rms_decision"] != EQUIVALENT
    assert result["rms_ci_deg"][1] >= result["rms_deg"] >= margin - 0.2


def test_claims_decide_in_the_expected_direction():
    rng = np.random.default_rng(1)
    n = 90
    close = rng.normal(0, 0.4, n)
    draws = close + rng.normal(0, 0.4, (300, n))
    result = conditional_tost(close, draws, 5.0)
    assert result["mean_decision"] == result["rms_decision"] == result["curve_decision"] == EQUIVALENT
    far = close + 12.0
    result = conditional_tost(far, far + rng.normal(0, 0.4, (300, n)), 5.0)
    assert result["mean_decision"] == result["rms_decision"] == result["curve_decision"] == NOT_EQUIVALENT
    # Cancelling errors pass on the mean but not on RMS: why RMS is the primary claim.
    swing = 8.0 * np.sin(np.linspace(0, 2 * np.pi, n))
    result = conditional_tost(swing, swing + rng.normal(0, 0.4, (300, n)), 5.0)
    assert result["mean_decision"] == EQUIVALENT and result["rms_decision"] != EQUIVALENT
    assert primary_claim() == "rms"


def test_replicate_scalar_tost_needs_enough_replicates():
    assert replicate_scalar_tost(np.array([1.0, 1.2, 0.9, 1.1, 1.0]), 5.0, "rms")["pass"]
    assert not replicate_scalar_tost(np.array([4.8, 5.2, 5.1, 4.9, 5.0]), 5.0, "rms")["pass"]
    with pytest.raises(ValidationError):
        replicate_scalar_tost(np.ones(3), 5.0, "mean")


def test_end_to_end_passes_agreement_and_rejects_gross_error(motion):
    warnings.simplefilter("ignore", RuntimeWarning)
    options = dict(draws=60, calibration_refits=10)
    sim = simulate(motion, QUIET, replicates=5, seed=21)
    report = evaluate_conditional((sim.first, sim.second), None, sim.replicates, sim.K1, sim.K2, sim.motion, **options)
    assert report["decision"] == EQUIVALENT
    assert report["primary_claim"] == "rms"
    assert "Conditional on this performance" in report["scope"]
    assert report["noise_model"]["source"].startswith("max(still frames")
    sim = simulate(motion, QUIET, injected={"right": 20.0}, replicates=5, seed=22)
    report = evaluate_conditional((sim.first, sim.second), None, sim.replicates, sim.K1, sim.K2, sim.motion, **options)
    right = report["angles"]["right_elbow_flexion"]
    assert report["decision"] == NOT_EQUIVALENT and right["decision"] == NOT_EQUIVALENT
    assert right["mean_ci_deg"][0] > 10


def test_worker_summary_never_claims_more_than_the_report():
    angle = {
        "decision": INCONCLUSIVE, "margin_deg": 5.0, "mean_difference_deg": 1.0, "mean_ci_deg": [-1, 3],
        "mean_decision": EQUIVALENT, "rms_deg": 4.0, "rms_ci_deg": [2, 6], "rms_decision": INCONCLUSIVE,
        "curve_decision": INCONCLUSIVE, "max_band_abs_deg": 20.0, "measurement_sd_deg": [2, 5],
        "replicate_check": {"pass": False}, "pearson_r": 0.99, "curve_phase": [0.0],
        "max_abs_deg": 9.0, "fraction_outside_margin": 0.0,
    }
    report = {"decision": INCONCLUSIVE, "primary_claim": "rms", "scope": "Conditional on this performance.",
              "angles": {"left_elbow_flexion": angle}, "noise_model": {}, "diagnostics": {}}
    summary = single_take_summary(report, "Father")
    assert summary["equivalence_verdict"] == INCONCLUSIVE and summary["status"] == "inconclusive"
    assert "PROVEN" not in summary["message"] and "Conditional on this performance" in summary["message_detail"]
    assert "curve_phase" not in summary["single_take"]["angles"]["left_elbow_flexion"]
    assert summary["artifacts"]["figures"] == ["single_take_equivalence.png"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "analysis_dir", tmp_path / "analyses")
    monkeypatch.setattr(service, "readiness", lambda: {"ready": True, "message": "Ready"})
    monkeypatch.setattr(service, "run_job", lambda _: None)
    app = FastAPI()
    app.include_router(analysis.router)
    with TestClient(app) as client:
        yield client


def test_api_requires_two_views_of_the_same_performance(client):
    options = {"pairing_confirmed": True, "recording_relationship": "same_performance",
               "tolerance_profile": "statistical_equivalence"}
    base = {"motioncapture_fbx": ("take.fbx", b"fbx"), "reference_video": ("front.mp4", b"video")}
    post = lambda opts, **extra: client.post("/analyses", files={**base, **extra}, data={"options": json.dumps(opts)})
    assert "70–90°" in post(options).json()["detail"]
    assert "same performance" in post({**options, "recording_relationship": "unknown"}).json()["detail"]
    assert "both the front and the oblique" in post(
        options, oblique_video=("side.mov", b"video"), noise_front_video=("n.mp4", b"video")
    ).json()["detail"]
    accepted = post({**options, "focal_35mm": 26}, oblique_video=("side.mov", b"video"))
    assert accepted.status_code == 202
    stored = json.loads(next((service.settings.analysis_dir).glob("*/options.json")).read_text())
    assert stored["files"]["oblique_video"] == "oblique.mov" and "non_suit_fbx" not in stored["files"]
    assert stored["focal_35mm"] == 26


def test_simulated_motion_noise_rises_only_while_moving(motion):
    """Regression: the factor used to apply to the holds too, so still frames already saw it."""
    calm = simulate(motion, replace(QUIET, noise_px=2.0), seed=5)
    busy = simulate(motion, replace(QUIET, noise_px=2.0, motion_noise_factor=2.0), seed=5)
    hold = calm.first.times < Scenario().video_lead_s + 0.8
    still = lambda sim: estimate_keypoint_noise((sim.first, sim.second), tuple(still_mask(v) for v in (sim.first, sim.second)))
    assert np.median(still(busy).sigma_px) == pytest.approx(np.median(still(calm).sigma_px), rel=0.2)
    # Same seed, same unit noise draws: the two takes differ only where the factor applies.
    extra = np.nanmax(np.abs(busy.first.uv - calm.first.uv), axis=(1, 2))
    assert np.nanmax(extra[hold]) < 1e-9
    assert np.nanmedian(extra[len(extra) // 2 - 10 : len(extra) // 2 + 10]) > 1.0
