"""Case-level measurements preserve clocks, units, provenance, and uncertainty."""

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from app.validation.case_study import (
    camera_fits,
    difference,
    elbow_angles,
    frontal_camera_fit,
    initial_pose_warning,
    measure,
    normalize_reference,
    project,
    run_case_study,
    sample_video,
    score_mode,
    sync_queries,
)
from app.validation.fbx_motion import CASE_JOINTS, Motion, load_motion
from app.validation.mixed_effects import ValidationError
from app.validation.trials import Trial, sha256, load_manifest
from app.validation.video_pose import VideoPose


def test_initial_pose_jump_is_flagged_without_trimming_real_motion():
    xyz = np.zeros((10, 8, 3))
    xyz[:, 0, 0], xyz[:, 1, 0] = -0.2, 0.2
    xyz[0, 4:8, 1] = 0.4
    motion = Motion(Path("capture.fbx"), "test", 30, np.arange(10) / 30, xyz)
    assert "export preparation pose" in initial_pose_warning(
        motion, [0, 0.3], "Capture"
    )
    assert initial_pose_warning(motion, [1 / 30, 0.3], "Capture") is None
    xyz[0, 4:8, 1] = 0.01
    assert initial_pose_warning(motion, [0, 0.3], "Capture") is None


def test_pixel_aspect_ratio_and_missing_shoulder_normalization():
    pixels = (
        np.broadcast_to(
            np.array(
                [
                    [100, 100],
                    [200, 100],
                    [100, 200],
                    [200, 200],
                    [80, 150],
                    [220, 150],
                    [80, 100],
                    [220, 100],
                ]
            ),
            (101, 8, 2),
        )
        .copy()
        .astype(float)
    )
    a, width = normalize_reference(pixels / [800, 400], 800, 400)
    b, other = normalize_reference(pixels / [1600, 400], 1600, 400)
    assert width == other == 100
    np.testing.assert_allclose(a, b)
    np.testing.assert_allclose(a[0, 2] - a[0, 0], [0, 1])
    pixels[0, 0] = np.nan
    c, _ = normalize_reference(pixels / [800, 400], 800, 400)
    assert np.isnan(c[0]).all()


def test_frontal_diagnostic_recovers_upright_view_without_using_arms_or_hip_ratio(
    tmp_path,
):
    _, _, motions, _ = synthetic_case(tmp_path)
    xyz = motions["suit"].joints.copy()
    expected = xyz[:, :, :2] * [-1, -1]
    mask = np.ones(len(xyz), dtype=bool)
    fit = frontal_camera_fit(xyz, expected, mask)
    np.testing.assert_allclose(project(xyz, fit), expected, atol=1e-12)
    changed = xyz.copy()
    changed[:, 2:4, 1] *= 2
    changed[:, 4:] += [1, 2, 3]
    other = frontal_camera_fit(changed, expected, mask)
    np.testing.assert_allclose(other["rotation_vector_rad"], fit["rotation_vector_rad"])


def test_position_bias_angle_and_percentage_metrics():
    reference = np.zeros((101, 8, 2))
    reference[:, 0] = [0, 1]
    reference[:, 4] = [1, 0]
    reference[:, 6] = [0, 0]
    reference[:, 1] = [0, 1]
    reference[:, 5] = [1, 0]
    reference[:, 7] = [0, 0]
    assert np.allclose(elbow_angles(reference), 90)
    shifted = reference + [0.3, 0.4]
    metrics = measure(reference, shifted, np.ones(101, dtype=bool))
    assert metrics["position"]["left_wrist"]["mean"] == pytest.approx(0.5)
    assert metrics["position"]["left_wrist"]["signed_bias_x"] == pytest.approx(0.3)
    assert metrics["elbow_angle"]["left"]["mean"] == pytest.approx(0)
    assert difference(0.1, 0.2)["percentage_reduction_from_old"] == pytest.approx(50)
    assert difference(0.1, 0)["percentage_reduction_from_old"] is None
    assert np.isnan(elbow_angles(np.zeros((5, 8, 2)))).all()


def test_synchronization_offset_rate_and_evidence():
    sync = {
        "suit": {
            "clock_verified": True,
            "clock_evidence": "original clock reviewed",
            "event": {
                "reviewed": True,
                "description": "LED flash",
                "video_seconds": 2,
                "fbx_seconds": 0.5,
            },
        }
    }
    np.testing.assert_allclose(sync_queries(np.array([2, 3]), sync, "suit"), [0.5, 1.5])
    sync["suit"]["video_seconds_per_fbx_second"] = 2
    with pytest.raises(ValidationError, match="rate correction"):
        sync_queries([2, 4], sync, "suit")
    sync["suit"]["rate_evidence"] = "documented half-speed export"
    np.testing.assert_allclose(sync_queries([2, 4], sync, "suit"), [0.5, 1.5])
    assert sync_queries([1, 2], {}, "suit") is None
    sync["suit"]["event"]["reviewed"] = False
    with pytest.raises(ValidationError, match="reviewed synchronization"):
        sync_queries([2], sync, "suit")


def test_reference_sampling_does_not_bridge_long_gaps_or_use_low_confidence():
    pose = VideoPose(np.array([0, 0.1, 0.2, 0.5]), np.zeros((4, 8, 2)), np.ones((4, 8)))
    pose.confidence[1, 4] = 0.5
    pose.xy[2, 5] = np.nan
    result = sample_video(pose, np.array([0.05, 0.15, 0.35]))
    assert np.isfinite(result[0, 0]).all()
    assert np.isnan(result[0, 4]).all()  # .2 second gap exceeds .15
    assert np.isnan(result[1, 5]).all()
    assert np.isnan(result[2]).all()


def synthetic_case(tmp_path):
    t = np.linspace(0, 1, 101)
    xyz = np.zeros((101, len(CASE_JOINTS), 3))
    xyz[:, 0] = [-0.2, 0, 0]
    xyz[:, 1] = [0.2, 0, 0]
    xyz[:, 2] = [-0.15, -0.5, 0]
    xyz[:, 3] = [0.15, -0.5, 0]
    xyz[:, 6] = [-0.3, -0.25, 0]
    xyz[:, 7] = [0.3, -0.25, 0]
    xyz[:, 4, 0] = -0.3 + 0.1 * np.sin(t * 6)
    xyz[:, 4, 1] = -0.4 + 0.1 * np.cos(t * 6)
    xyz[:, 5, 0] = 0.3 + 0.1 * np.sin(t * 6)
    xyz[:, 5, 1] = -0.4 + 0.1 * np.cos(t * 6)
    xyz[:, 8] = xyz[:, 4] + [0.03, 0, 0]
    xyz[:, 9] = xyz[:, 5] + [0.03, 0, 0]
    xy = xyz[:, :, :2] * [1, -1] + [0.5, 0.2]
    pose = VideoPose(t, xy, np.ones((101, len(CASE_JOINTS))))
    paths = {
        key: tmp_path / name
        for key, name in {
            "suit_fbx": "new.fbx",
            "non_suit_fbx": "old.fbx",
            "reference_video": "video.mp4",
            "video_landmarks": "pose.csv",
        }.items()
    }
    for path in paths.values():
        path.write_bytes(path.name.encode())
    with paths["video_landmarks"].open("w", newline="") as stream:
        columns = [
            "time_s",
            *(
                f"{joint}_{field}"
                for joint in CASE_JOINTS
                for field in ("x", "y", "confidence")
            ),
        ]
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for i, time in enumerate(t):
            row = {"time_s": time}
            for j, name in enumerate(CASE_JOINTS):
                row.update(
                    {
                        f"{name}_x": xy[i, j, 0],
                        f"{name}_y": xy[i, j, 1],
                        f"{name}_confidence": 1,
                    }
                )
            writer.writerow(row)
    hashes = {key: sha256(path) for key, path in paths.items()}
    trial = Trial(
        "case",
        "ACTION",
        "P01",
        "01",
        paths["suit_fbx"],
        paths["non_suit_fbx"],
        paths["reference_video"],
        paths["video_landmarks"],
        hashes,
        {"suit": (0, 1), "non_suit": (0, 1), "video": (0, 1)},
        (0, 0.2),
        "user attestation",
    )
    motions = {}
    for label, offset in (("suit", 0.01), ("non_suit", 0.04)):
        data = xyz.copy()
        data[:, 4:, 0] += offset
        motions[label] = Motion(
            paths["suit_fbx" if label == "suit" else "non_suit_fbx"],
            "synthetic",
            100,
            t,
            data,
        )
    metadata = {"width": 800, "height": 400}
    return trial, pose, motions, metadata


def test_case_shape_uses_common_frames_and_unknown_clocks_remain_indeterminate(
    tmp_path,
):
    trial, pose, motions, metadata = synthetic_case(tmp_path)
    pose.confidence[:10, 4] = 0
    result, artifact = score_mode(
        trial, pose, None, motions, metadata, {}, "phase_normalized"
    )
    assert result["n_common_frames"] == 91
    assert result["comparison"]["combined_position"]["old_minus_motioncapture"] > 0
    assert sum(row["valid"] for row in artifact[0]) == 91
    result, artifact = score_mode(trial, pose, None, motions, metadata, {}, "synchronized")
    assert result["status"] == "indeterminate" and artifact is None
    pose.confidence[:30, 4] = 0
    with pytest.raises(ValidationError, match="coverage"):
        score_mode(trial, pose, None, motions, metadata, {}, "phase_normalized")


def test_camera_ambiguity_is_not_hidden_by_best_torso_fit():
    xyz = np.zeros((101, len(CASE_JOINTS), 3))
    xyz[:, 0] = [-0.5, 0, 0]
    xyz[:, 1] = [0.5, 0, 0]
    xyz[:, 2] = [-0.4, -1, 0]
    xyz[:, 3] = [0.4, -1, 0]
    xyz[:, 4] = [-0.7, -0.5, 1]
    xyz[:, 5] = [0.7, -0.5, 1]
    known = {"rotation_vector_rad": [np.pi + 0.5, 0, 0], "scale": 1}
    reference = project(xyz, known)
    solutions = camera_fits(xyz, reference, np.ones(101, dtype=bool))
    assert len(solutions) >= 2
    errors = [
        np.linalg.norm(project(xyz, s)[:, 4:6] - reference[:, 4:6], axis=2).mean()
        for s in solutions
    ]
    assert max(errors) - min(errors) > 0.1


def test_real_native_profiles_complete_without_lifetime_crash():
    root = Path(__file__).resolve().parents[2]
    for relative, profile, fps in [
        ("MotionCaptureFbx/action.fbx", "mixamo_30", 30),
        ("oldfbx/action.fbx", "blender_25", 25),
    ]:
        motion = load_motion(root / relative, include_elbows=True)
        assert motion.profile == profile and motion.fps == fps
        assert motion.joints.shape[1:] == (len(CASE_JOINTS), 3)
        assert np.isfinite(motion.joints).all()
        np.testing.assert_allclose(np.diff(motion.times), 1 / fps, atol=1e-6)


def test_end_to_end_report_provenance_and_fresh_output(tmp_path, monkeypatch):
    monkeypatch.setattr("app.validation.case_study.reference_review", lambda *args: "")
    monkeypatch.setattr(
        "app.validation.case_study.comparison_overlay", lambda *args: ""
    )
    trial, pose, motions, metadata = synthetic_case(tmp_path)
    model = tmp_path / "model.task"
    model.write_bytes(b"model")
    metadata.update(
        video_sha256=trial.hashes["reference_video"],
        landmarks_sha256=trial.hashes["video_landmarks"],
        pose_model_sha256=sha256(model),
    )
    metadata_file = tmp_path / "metadata.json"
    metadata_file.write_text(json.dumps(metadata))
    entry = {
        key: str(getattr(trial, key).name)
        for key in ("suit_fbx", "non_suit_fbx", "reference_video", "video_landmarks")
    }
    entry.update(
        performance_id="case",
        action_id="ACTION",
        performer_id="P01",
        repetition="01",
        pairing_verified_by="user attestation",
        reference_independent=True,
        sha256=trial.hashes,
        windows={key: list(value) for key, value in trial.windows.items()},
        calibration_phase=[0, 0.2],
    )
    manifest = tmp_path / "manifest.json"
    configuration = {
        "schema_version": 1,
        "trials": [entry],
        "case_study": {
            "video_metadata": metadata_file.name,
            "video_metadata_sha256": sha256(metadata_file),
            "pose_model": model.name,
        },
    }
    manifest.write_text(json.dumps(configuration))
    monkeypatch.setattr(
        "app.validation.case_study.load_motion",
        lambda p, **_: motions["suit" if p == trial.suit_fbx else "non_suit"],
    )
    output = tmp_path / "report"
    report = run_case_study(manifest, output)
    assert report["conclusion"] == "statistical equivalence not established"
    assert report["timing_status"] == "indeterminate"
    assert report["provenance"]["manifest_sha256"] == sha256(manifest)
    assert (output / "report.html").is_file() and (
        output / "phase_normalized_traces.csv"
    ).is_file()
    assert (
        "Statistical equivalence not established"
        in (output / "report.html").read_text()
    )
    assert "\\" not in report["artifacts"]["traces"]["phase_normalized"]
    with pytest.raises(ValidationError, match="fresh output"):
        run_case_study(manifest, output)
    configuration["trials"][0]["recording_relationship"] = "separate_repetitions"
    manifest.write_text(json.dumps(configuration))
    with pytest.raises(ValidationError, match="cannot enter matched accuracy"):
        load_manifest(manifest)
    separate = run_case_study(manifest, tmp_path / "separate-report")
    assert separate["comparison_kind"] == "movement_similarity"
    assert separate["capture_accuracy_status"] == "not_assessable"
    assert separate["n_independent_performances"] is None
    assert separate["timing_status"] == "not_applicable"
    assert separate["analyses"]["phase_normalized"]["status"] == "descriptive"
    assert separate["analyses"]["synchronized"]["status"] == "not_applicable"
    assert (
        "Capture accuracy cannot be determined"
        in (tmp_path / "separate-report" / "report.html").read_text()
    )
    configuration["case_study"]["video_metadata_sha256"] = "0" * 64
    manifest.write_text(json.dumps(configuration))
    with pytest.raises(ValidationError, match="metadata"):
        run_case_study(manifest, tmp_path / "other")
    configuration["case_study"]["video_metadata_sha256"] = sha256(metadata_file)
    configuration["trials"][0]["sha256"]["suit_fbx"] = "0" * 64
    manifest.write_text(json.dumps(configuration))
    with pytest.raises(ValidationError, match="SHA-256"):
        run_case_study(manifest, tmp_path / "other")


def test_synchronized_shorter_action_keeps_duration_discrepancy_visible(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    trial, pose, motions, metadata = synthetic_case(tmp_path)
    trial = replace(
        trial, windows={"suit": (0, 0.8), "non_suit": (0, 1), "video": (0, 1)}
    )
    entry = {
        "clock_verified": True,
        "clock_evidence": "unaltered native clocks reviewed",
        "event": {
            "reviewed": True,
            "description": "same onset",
            "video_seconds": 0,
            "fbx_seconds": 0,
        },
    }
    result, artifact = score_mode(
        trial,
        pose,
        None,
        motions,
        metadata,
        {"synchronization": {"suit": entry, "non_suit": entry}},
        "synchronized",
    )
    assert result["n_common_frames"] == 81
    assert result["temporal_common_coverage"] == pytest.approx(81 / 101)
    assert artifact[0][-1]["valid"] == 0
    assert artifact[0][-1]["suit_time_s"] == pytest.approx(1)
    assert artifact[0][-1]["suit_left_wrist_error"] == ""
    assert trial.windows["suit"][1] - trial.windows["video"][1] == pytest.approx(-0.2)


def test_invalid_native_source_reports_validation_error(tmp_path):
    source = tmp_path / "bad.fbx"
    source.write_bytes(b"not an FBX")
    with pytest.raises(ValidationError, match="worker failed"):
        load_motion(source, include_elbows=True)
