"""Research validation protects pairing, frame independence, and projection quality."""

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from app.validation.fbx_motion import Motion, load_motion
from app.validation.mixed_effects import ValidationError
from app.validation.scoring import PHASE, calibrate_camera, run_manifest, score_trial
from app.validation.secondary import (
    _shared_hand_dtw, constrained_dtw_sensitivity,
    functional_limits_of_agreement, spm1d_paired_curves,
)
from app.validation.trials import Trial, load_manifest, sha256
from app.validation.video_pose import COLUMNS, VideoPose, read_pose_csv


def _trial(tmp_path):
    files = {key: tmp_path / (key + suffix) for key, suffix in (
        ("suit_fbx", ".fbx"), ("non_suit_fbx", ".fbx"), ("reference_video", ".mp4"))}
    for path in files.values():
        path.write_bytes(path.name.encode())
    pose_file = tmp_path / "pose.csv"
    pose_file.write_text("video pose")
    item = {
        "performance_id": "trial-1", "action_id": "WAVE", "performer_id": "P1",
        "repetition": "1", "pairing_verified_by": "human reviewer",
        "reference_independent": True,
        **{key: path.name for key, path in files.items()},
        "video_landmarks": pose_file.name,
        "sha256": {**{key: sha256(path) for key, path in files.items()},
                   "video_landmarks": sha256(pose_file)},
        "windows": {key: [0, 1] for key in ("suit", "non_suit", "video")},
        "calibration_phase": [0, 0.2],
    }
    manifest = tmp_path / "trials.json"
    manifest.write_text(json.dumps({"schema_version": 1, "trials": [item]}))
    return manifest, item


def test_manifest_rejects_hash_mismatch_and_uncertain_or_duplicate_pairs(tmp_path):
    manifest, item = _trial(tmp_path)
    assert len(load_manifest(manifest, require_landmarks=True)) == 1
    item["reference_independent"] = False
    manifest.write_text(json.dumps({"schema_version": 1, "trials": [item]}))
    with pytest.raises(ValidationError, match="independent"):
        load_manifest(manifest)
    item["reference_independent"] = True
    item["sha256"]["suit_fbx"] = "0" * 64
    manifest.write_text(json.dumps({"schema_version": 1, "trials": [item]}))
    with pytest.raises(ValidationError, match="SHA-256"):
        load_manifest(manifest)
    item["sha256"]["suit_fbx"] = sha256(tmp_path / "suit_fbx.fbx")
    (tmp_path / "non_suit_fbx.fbx").write_bytes((tmp_path / "suit_fbx.fbx").read_bytes())
    item["sha256"]["non_suit_fbx"] = sha256(tmp_path / "non_suit_fbx.fbx")
    manifest.write_text(json.dumps({"schema_version": 1, "trials": [item]}))
    with pytest.raises(ValidationError, match="contents are duplicated"):
        load_manifest(manifest)
    (tmp_path / "non_suit_fbx.fbx").write_bytes(b"distinct motion")
    item["sha256"]["non_suit_fbx"] = sha256(tmp_path / "non_suit_fbx.fbx")
    manifest.write_text(json.dumps({"schema_version": 1, "trials": [item, item]}))
    with pytest.raises(ValidationError, match="Duplicate"):
        load_manifest(manifest)


def _motion(n=101):
    t = np.linspace(0, 1, n)
    joints = np.zeros((n, 6, 3))
    joints[:, 0] = (-0.2, 1.5, 0)
    joints[:, 1] = (0.2, 1.5, 0)
    joints[:, 2] = (-0.15, 1.0, 0)
    joints[:, 3] = (0.15, 1.0, 0)
    joints[:, 4, 0] = -0.35 + 0.1 * np.sin(2 * np.pi * t)
    joints[:, 4, 1] = 1.1 + 0.1 * np.cos(2 * np.pi * t)
    joints[:, 5, 0] = 0.35 + 0.1 * np.sin(2 * np.pi * t)
    joints[:, 5, 1] = 1.1 + 0.1 * np.cos(2 * np.pi * t)
    return joints


def test_fixed_projection_recovers_known_camera_and_rejects_axis_mismatch():
    xyz = _motion()
    xyz = (xyz - xyz[:, :2].mean(axis=1)[:, None]) / 0.4
    camera = Rotation.from_euler("x", 180, degrees=True).as_matrix()
    reference = (xyz @ camera.T)[..., :2] * 0.8
    rotation, scale, rmse = calibrate_camera(xyz, reference, (0, 0.2))
    assert rmse < 1e-5
    assert np.allclose((xyz @ Rotation.from_rotvec(rotation).as_matrix().T)[..., :2] * scale,
                       reference, atol=1e-3)
    bad_reference = reference.copy()
    bad_reference[:21, 2, 0] += 3
    with pytest.raises(ValidationError, match="calibration failed"):
        calibrate_camera(xyz, bad_reference, (0, 0.2))


def test_video_csv_preserves_missing_joints_and_rejects_partial_occlusion(tmp_path):
    path = tmp_path / "pose.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        for i in range(3):
            row = {"time_s": i / 30}
            for name in ("left_shoulder", "right_shoulder", "left_hip", "right_hip", "left_wrist", "right_wrist"):
                row.update({f"{name}_x": 0.2, f"{name}_y": 0.3, f"{name}_confidence": 0.9})
            if i == 1:
                row.update({"left_wrist_x": "", "left_wrist_y": "", "left_wrist_confidence": ""})
            writer.writerow(row)
    pose = read_pose_csv(path)
    assert np.isnan(pose.xy[1, 4]).all() and pose.confidence[1, 4] == 0
    content = path.read_text().replace(",,,", ",0.2,,", 1)
    path.write_text(content)
    with pytest.raises(ValidationError, match="partially missing"):
        read_pose_csv(path)


def test_paired_score_uses_same_visible_reference_phases(monkeypatch, tmp_path):
    manifest, _ = _trial(tmp_path)
    trial = load_manifest(manifest)[0]
    source = _motion()
    camera = Rotation.from_euler("x", 180, degrees=True).as_matrix()
    image = (source - source[:, :2].mean(axis=1)[:, None]) @ camera.T
    image = image[..., :2] * 0.2 / 0.4 + 0.5
    video = VideoPose(PHASE, image, np.ones((101, 6)))
    video.confidence[35:55, 4] = 0
    suit = source.copy()
    non_suit = source.copy()
    suit[:, 4:6, 0] += 0.012
    non_suit[:, 4:6, 0] += 0.048

    def loader(path):
        data = suit if path == trial.suit_fbx else non_suit
        return Motion(Path(path), "synthetic", 100, PHASE, data)

    monkeypatch.setattr("app.validation.scoring.load_motion", loader)
    monkeypatch.setattr("app.validation.scoring.read_pose_csv", lambda _: video)
    score, trace, audit = score_trial(trial)
    assert score["suit_error"] < score["non_suit_error"]
    assert 0.8 < audit["common_wrist_coverage"] < 1
    assert sum(row["valid"] for row in trace) < 101
    video.confidence[:30, 4] = 0
    with pytest.raises(ValidationError, match="both wrists"):
        score_trial(trial)


def test_observed_non_suit_profiles_preserve_native_frame_clocks():
    candidates = (
        (Path("/Users/duveen/Downloads/Action.fbx"), "newton_30", 30),
        (Path("/Users/duveen/Downloads/SignSaathi/Code/FBX Files/action.fbx"), "blender_25", 25),
    )
    for file, profile, fps in candidates:
        if not file.exists():
            continue
        motion = load_motion(file)
        assert motion.profile == profile and motion.fps == fps
        assert np.allclose(np.diff(motion.times), 1 / fps)
        assert motion.joints.shape[1:] == (6, 3)
    suit_files = list(Path("backend/data/uploads").glob("*/*_mixamo.fbx"))
    if suit_files:
        suit = load_motion(suit_files[0])
        assert suit.profile == "rokoko_mixamo_60" and suit.fps == 60


def test_secondary_curves_keep_performers_as_independent_units(tmp_path):
    import importlib.util

    entries = []
    rng = np.random.default_rng(92)
    for performer in range(6):
        for repetition in range(2):
            rows = []
            noise = rng.normal(0, 0.025, size=101)
            method_noise = rng.normal(0, 0.02, size=101)
            for phase in range(101):
                row = {"phase": phase / 100, "valid": 1}
                for side in ("left", "right"):
                    for axis in ("x", "y"):
                        row[f"reference_{side}_{axis}"] = 0.0
                        row[f"suit_{side}_{axis}"] = 0.10 + noise[phase]
                        row[f"non_suit_{side}_{axis}"] = 0.20 + noise[phase] + method_noise[phase]
                    row[f"suit_{side}_error"] = 0.10 + noise[phase]
                    row[f"non_suit_{side}_error"] = 0.20 + noise[phase] + method_noise[phase]
                rows.append(row)
            trace_path = tmp_path / f"p{performer}-r{repetition}.csv"
            with trace_path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            entries.append({"performance_id": f"p{performer}-r{repetition}",
                            "action_id": "WAVE", "performer_id": f"p{performer}",
                            "trace_file": trace_path.name})
    (tmp_path / "qc.json").write_text(json.dumps({"trials": entries}))
    floa = functional_limits_of_agreement(tmp_path, bootstraps=100)
    assert floa["actions"]["WAVE"]["n"] == 12
    assert floa["actions"]["WAVE"]["n_performers"] == 6
    assert floa["actions"]["WAVE"]["waveforms"]["suit_left_x"]["status"] == "descriptive"
    dtw = constrained_dtw_sensitivity(tmp_path)
    assert len(dtw["trials"]) == 12
    assert dtw["trials"][0]["suit"]["mean_wrist_error"] < dtw["trials"][0]["non_suit"]["mean_wrist_error"]
    if importlib.util.find_spec("spm1d"):
        spm = spm1d_paired_curves(tmp_path)
        assert spm["actions"]["WAVE"]["status"] == "exploratory"
        assert spm["actions"]["WAVE"]["n_independent_performers"] == 6


def test_dtw_uses_one_bounded_path_for_both_hands():
    phase = np.linspace(0, 1, 101)
    reference = np.column_stack((phase, np.sin(phase), -phase, np.cos(phase)))
    shifted = np.column_stack((phase + 0.03, np.sin(phase + 0.03),
                               -phase + 0.03, np.cos(phase + 0.03)))
    result = _shared_hand_dtw(reference, shifted)
    assert result["mean_absolute_phase_warp"] <= 0.10
    assert result["mean_wrist_error"] >= 0


def test_batch_scoring_emits_audit_overlay_and_never_overwrites(tmp_path, monkeypatch):
    manifest, _ = _trial(tmp_path)
    trial = load_manifest(manifest)[0]
    rows = []
    for phase in PHASE:
        row = {"phase": float(phase), "valid": 1}
        for side in ("left", "right"):
            for axis in ("x", "y"):
                row[f"reference_{side}_{axis}"] = float(phase)
                row[f"suit_{side}_{axis}"] = float(phase + 0.1)
                row[f"non_suit_{side}_{axis}"] = float(phase + 0.2)
            row[f"suit_{side}_error"] = 0.1
            row[f"non_suit_{side}_error"] = 0.2
        rows.append(row)
    score = {
        "performance_id": trial.performance_id, "action_id": trial.action_id,
        "performer_id": trial.performer_id, "reference_id": trial.hashes["reference_video"],
        "metric": "wrist_position_error_2d_normalized",
        "suit_error": 0.1, "non_suit_error": 0.2,
    }
    monkeypatch.setattr("app.validation.scoring.score_trial",
                        lambda _: (score, rows, {"performance_id": trial.performance_id}))
    output = tmp_path / "scores"
    report = run_manifest(manifest, output)
    assert report["n_trials"] == 1
    assert (output / "paired_scores.csv").is_file()
    assert next((output / "traces").glob("*.svg")).read_text().startswith("<svg")
    with pytest.raises(ValidationError, match="already contains results"):
        run_manifest(manifest, output)
