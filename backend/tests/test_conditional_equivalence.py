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
    sequential_decision,
    still_mask,
    testing_order as prespecified_order,
)
from app.validation.angles3d import ANGLES
from app.validation.equivalence_single_take import EQUIVALENT, INCONCLUSIVE, NOT_EQUIVALENT, PARTIALLY_EQUIVALENT
from app.validation.fbx_motion import CASE_JOINTS, EXTRA_BONES, KNUCKLE_FINGERS, knuckle_centre, load_motion
from app.validation.mixed_effects import ValidationError
from app.validation.single_take_simulation import Scenario, simulate

ROOT = Path(__file__).resolve().parents[2]
QUIET = replace(Scenario(), noise_px=1.5, joint_offset_m=0.0, hold_s=1.0)


@pytest.fixture(scope="module")
def motion():
    return load_motion(ROOT / "MotionCaptureFbx/action.fbx", include_extras=True)


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
    # The error starts at sign onset; one already present in the hold is a definition offset.
    from app.validation.multiview import sign_window
    from app.validation.single_take_simulation import padded

    start, _ = sign_window(padded(motion, QUIET.hold_s))
    gross = np.zeros(len(padded(motion, QUIET.hold_s).times))
    gross[start:] = 20.0
    sim = simulate(motion, QUIET, injected={"right": gross}, replicates=5, seed=22)
    report = evaluate_conditional((sim.first, sim.second), None, sim.replicates, sim.K1, sim.K2, sim.motion, **options)
    right = report["angles"]["right_elbow_flexion"]
    assert right["decision"] == NOT_EQUIVALENT and right["mean_ci_deg"][0] > 10
    # Fixed sequence: trunk and shoulders are tested first and stay confirmed; testing stops at
    # the elbow pair and never reaches the wrists.
    sequence = report["sequence"]
    assert report["decision"] == PARTIALLY_EQUIVALENT
    assert sequence["stopped_at"] == ["left_elbow_flexion", "right_elbow_flexion"]
    assert "trunk_twist" in sequence["confirmed"] and "right_wrist_deviation" in sequence["untested"]
    assert report["angles"]["right_wrist_deviation"]["tested_in_sequence"] is False


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
    # Still runs reach the onset of movement, so a little motion noise leaks in (conservative).
    assert np.median(still(busy).sigma_px) == pytest.approx(np.median(still(calm).sigma_px), rel=0.3)
    # Same seed, same unit noise draws: the two takes differ only where the factor applies.
    extra = np.nanmax(np.abs(busy.first.uv - calm.first.uv), axis=(1, 2))
    assert np.nanmax(extra[hold]) < 1e-9
    assert np.nanmedian(extra[len(extra) // 2 - 10 : len(extra) // 2 + 10]) > 1.0


def test_fbx_edge_glitch_is_trimmed_and_interior_glitch_refused(motion):
    """Regression: a Rokoko export ended on a frame snapping 240 mm back to a reference pose,
    which became the peak speed and stretched the sign window to the end of the file."""
    from app.validation.multiview import sign_window, trim_glitches

    base, dropped = trim_glitches(motion)
    assert dropped == [0]  # the bundled action.fbx itself starts on a snapped reference frame
    clean = replace(base, joints=np.concatenate([np.repeat(base.joints[:1], 30, 0), base.joints,
                                                 np.repeat(base.joints[-1:], 30, 0)]))
    clean = replace(clean, times=np.arange(len(clean.joints)) / clean.fps)
    glitched = clean.joints.copy()
    glitched[-1] += 0.24
    broken = replace(clean, joints=glitched)
    trimmed, dropped = trim_glitches(broken)
    assert dropped == [len(glitched) - 1]
    assert sign_window(trimmed) == sign_window(clean)
    assert trim_glitches(clean)[1] == []
    inside = clean.joints.copy()
    inside[len(inside) // 2] += 0.24
    with pytest.raises(ValidationError, match="inside the take"):
        trim_glitches(replace(clean, joints=inside))


def test_static_offset_is_measured_in_the_hold_and_removed(motion):
    """A definition offset present from the first frame (e.g. elbow carrying angle) must not count
    as disagreement, while the raw RMS still reports it."""
    from app.validation.multiview import rest_window, sign_window

    sim = simulate(motion, QUIET, injected={"right": 12.0}, replicates=5, seed=31)
    start, _ = sign_window(sim.motion)
    rest = rest_window(sim.motion, start)
    assert rest.stop <= start and (rest.stop - rest.start) / sim.motion.fps >= 0.4
    report = evaluate_conditional((sim.first, sim.second), None, sim.replicates, sim.K1, sim.K2, sim.motion,
                                  draws=60, calibration_refits=10)
    right = report["angles"]["right_elbow_flexion"]
    assert right["static_offset_deg"] == pytest.approx(12.0, abs=3.0)
    assert right["raw_rms_deg"] > 9.0 and right["rms_deg"] < 6.0
    assert report["diagnostics"]["offset_rule"] == "pre_sign_hold"


def test_sign_onset_ignores_a_single_frame_above_threshold(motion):
    from app.validation.multiview import sign_window, trim_glitches

    base, _ = trim_glitches(motion)
    held = replace(base, joints=np.concatenate([np.repeat(base.joints[:1], 60, 0), base.joints]))
    held = replace(held, times=np.arange(len(held.joints)) / held.fps)
    twitch = held.joints.copy()
    twitch[1, 4:6] += 0.01  # one-frame wrist twitch in the hold
    assert sign_window(replace(held, joints=twitch))[0] == sign_window(held)[0] > 50


ORDER = [["trunk"], ["left_a", "right_a"], ["left_b", "right_b"], ["wrist"]]


def test_fixed_sequence_keeps_angles_confirmed_before_the_first_failure():
    """Regression: one late, hard-to-measure angle used to make the whole take INCONCLUSIVE."""
    decisions = dict.fromkeys(["trunk", "left_a", "right_a", "left_b", "right_b"], EQUIVALENT)
    result = sequential_decision({**decisions, "wrist": INCONCLUSIVE}, ORDER)
    assert result["decision"] == PARTIALLY_EQUIVALENT
    assert result["confirmed"] == ["trunk", "left_a", "right_a", "left_b", "right_b"]
    assert result["stopped_at"] == ["wrist"] and result["untested"] == []
    assert sequential_decision({**decisions, "wrist": EQUIVALENT}, ORDER)["decision"] == EQUIVALENT


def test_fixed_sequence_stops_at_a_pair_with_one_failing_side():
    decisions = dict.fromkeys(["trunk", "left_a", "left_b", "right_b", "wrist"], EQUIVALENT)
    result = sequential_decision({**decisions, "right_a": INCONCLUSIVE}, ORDER)
    assert result["confirmed"] == ["trunk"] and result["stopped_at"] == ["left_a", "right_a"]
    assert result["untested"] == ["left_b", "right_b", "wrist"]  # later passes cannot be claimed


def test_fixed_sequence_without_any_confirmation_reports_the_first_group():
    decisions = dict.fromkeys(["left_a", "right_a", "left_b", "right_b", "wrist"], EQUIVALENT)
    assert sequential_decision({**decisions, "trunk": NOT_EQUIVALENT}, ORDER)["decision"] == NOT_EQUIVALENT
    assert sequential_decision({**decisions, "trunk": INCONCLUSIVE}, ORDER)["decision"] == INCONCLUSIVE


def test_fixed_sequence_ignores_order_entries_without_a_result():
    result = sequential_decision({"left_b": EQUIVALENT, "right_b": EQUIVALENT, "wrist": INCONCLUSIVE}, ORDER)
    assert result["order"] == [["left_b", "right_b"], ["wrist"]] and result["confirmed"] == ["left_b", "right_b"]


def test_testing_order_is_prespecified_for_every_angle():
    order = prespecified_order()
    assert sorted(name for group in order for name in group) == sorted(ANGLES)
    assert order[0] == ["trunk_twist"] and order[-1] == ["right_wrist_deviation"]
    from app.validation.equivalence_single_take import MARGINS_FILE

    assert json.loads(MARGINS_FILE.read_text())["hand_point"] == "knuckle_centre"  # what the code computes


def test_fbx_hand_point_is_the_four_knuckle_centre(motion):
    centred = knuckle_centre(motion)
    for side in ("Left", "Right"):
        columns = [EXTRA_BONES.index(f"{side}Hand{finger}1") for finger in KNUCKLE_FINGERS]
        expected = motion.extras[:, columns].mean(axis=1)
        assert np.allclose(centred.joints[:, CASE_JOINTS.index(f"{side.lower()}_index")], expected)
    assert knuckle_centre(centred) is centred
    with pytest.raises(ValidationError):
        knuckle_centre(replace(motion, extras=None))


def test_video_hand_point_uses_the_same_knuckles_on_both_hands():
    from app.validation.video_replicates import KNUCKLES, MIRROR, WHOLEBODY

    # COCO-WholeBody hands start at 91 (left) and 112 (right); MCPs are hand points 5, 9, 13, 17.
    assert KNUCKLES == {"left_index": (96, 100, 104, 108), "right_index": (117, 121, 125, 129)}
    assert WHOLEBODY[MIRROR["left_index"]] == KNUCKLES["right_index"]


def test_worker_summary_lists_confirmed_angles_for_a_partial_result():
    angle = {"decision": EQUIVALENT, "margin_deg": 15.0, "tested_in_sequence": True}
    sequence = sequential_decision(
        {"trunk_twist": EQUIVALENT, "right_wrist_deviation": INCONCLUSIVE},
        [["trunk_twist"], ["right_wrist_deviation"]],
    )
    report = {"decision": PARTIALLY_EQUIVALENT, "primary_claim": "rms", "scope": "Conditional on this performance.",
              "sequence": sequence, "noise_model": {}, "diagnostics": {},
              "angles": {"trunk_twist": angle, "right_wrist_deviation": {**angle, "decision": INCONCLUSIVE}}}
    summary = single_take_summary(report, "After")
    assert summary["status"] == "partial" and "1 of 2 angles (trunk twist)" in summary["message"]
    assert "stopped at right wrist deviation" in summary["message"]
    assert summary["single_take"]["angles"]["trunk_twist"]["tested_in_sequence"] is True


def test_simulation_summary_counts_refused_takes_as_not_equivalent(tmp_path, capsys):
    """Regression: one refused simulated take crashed a whole simulation chunk."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("simtool", ROOT / "backend/tools/simulate_conditional_equivalence.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    row = {"noise_px": 3.0, "scenario": "s", "seed": 0, "angle": "right_elbow_flexion", "margin": 15.0,
           "true_mean": 0.0, "true_rms": 15.0, "true_max": 15.0, "mean_ci": [-1, 1], "rms_ci": [10, 16],
           "decisions": {"mean": EQUIVALENT, "rms": EQUIVALENT, "whole_curve": INCONCLUSIVE}}
    rows = [row, {"noise_px": 3.0, "scenario": "s", "seed": 1, "refused": "hold not covered"}]
    path = tmp_path / "sims.jsonl"
    path.write_text("".join(json.dumps(item) + "\n" for item in rows))
    tool.summary(path)
    output = capsys.readouterr().out
    assert "1 refused" in output and "  2  " in output and "0.500" in output  # n = 2, P(EQ) = 1/2
