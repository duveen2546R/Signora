"""Regression cases for measurement integrity and descriptive assessment."""
import json
from pathlib import Path

import numpy as np
import pytest

from app.validation import case_study
from app.validation.fbx_motion import Motion
from app.validation.mixed_effects import ValidationError
from app.validation.trials import load_manifest, sha256
from tests.test_validation_case_study import synthetic_case
from tests.test_validation_pipeline import _trial


def test_all_required_sides_and_joints_must_be_observed():
    xy = np.zeros((101, 10, 2))
    xy[:, 0], xy[:, 1] = (-.5, 0), (.5, 0)
    xy[:, 6], xy[:, 7] = (-.7, .5), (.7, .5)
    xy[:, 4], xy[:, 5] = (-.5, 1), (.5, 1)
    xy[:, 8], xy[:, 9] = (-.5, 1.3), (.5, 1.3)
    pred = xy.copy()
    pred[:, 8] = np.nan
    certificate = case_study.clip_level_certificate('Rokoko', pred, xy)
    assert certificate['domains']['palm_orientation']['status'] == 'INCONCLUSIVE'
    assert certificate['required_joint_coverage']['left_index'] == 0
    assert certificate['statistical_equivalence']['status'] == 'not_established'
    pred[:, 4] = np.nan
    certificate = case_study.clip_level_certificate('Rokoko', pred, xy)
    assert certificate['domains']['path_movement']['status'] == 'INCONCLUSIVE'
    assert certificate['domains']['arm_posture']['status'] == 'INCONCLUSIVE'


def test_missing_reference_hashes_cannot_bypass_manifest_validation(tmp_path):
    manifest, item = _trial(tmp_path)
    item.pop('sha256')
    manifest.write_text(json.dumps({'schema_version': 1, 'trials': [item]}))
    with pytest.raises(ValidationError, match='SHA-256'):
        load_manifest(manifest)


@pytest.mark.parametrize('field', ['video_sha256', 'landmarks_sha256'])
def test_metadata_must_identify_both_current_sources(tmp_path, monkeypatch, field):
    trial, _, _, metadata = synthetic_case(tmp_path)
    metadata.update(video_sha256=trial.hashes['reference_video'], landmarks_sha256=trial.hashes['video_landmarks'])
    metadata[field] = '0' * 64
    meta = tmp_path / 'metadata.json'
    meta.write_text(json.dumps(metadata))
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'trials': [{}], 'case_study': {'video_metadata': meta.name, 'video_metadata_sha256': sha256(meta)}}))
    monkeypatch.setattr(case_study, 'load_manifest', lambda *a, **k: [trial])
    with pytest.raises(ValidationError, match='current video and landmarks'):
        case_study.run_case_study(manifest, tmp_path / 'results')


def test_native_clock_union_catches_between_phase_sample_spike(tmp_path):
    trial, pose, motions, metadata = synthetic_case(tmp_path)
    motion = motions['suit']
    times = np.insert(motion.times, 1, .005)
    xyz = np.insert(motion.joints, 1, (motion.joints[0] + motion.joints[1]) / 2, axis=0)
    xyz[1, 4, 0] += .5
    spiked = Motion(Path('spike.fbx'), 'synthetic', 1000, times, xyz)
    result, artifact = case_study.score_mode(trial, pose, None, {'suit': spiked}, metadata, {'reference_view': 'front'}, 'phase_normalized')
    assert result['n_assessed_samples'] == 102
    spike = next(row for row in artifact[0] if row['video_time_s'] == .005)
    assert spike['suit_left_wrist_error'] > .5
    certificate = result['comparison']['equivalence']['suit']
    assert certificate['domains']['path_movement']['status'] == 'FAIL'
    assert set(certificate['profile_sensitivity']) == {'replication', 'intelligibility'}
    json.dumps(result, allow_nan=False)


def test_time_weighting_does_not_treat_dense_clock_samples_as_replications():
    # A dense burst of low errors cannot overwhelm a longer high-error interval.
    times = np.r_[np.linspace(0, .01, 100), 1]
    result = case_study.evaluate_functional_domain(np.r_[np.zeros(100), 1], .2, 'Path', 'p95', times)
    assert result['tested_deviation'] == 1
    assert result['status'] == 'FAIL'
    assert case_study.intersection_union_decision({'path': {'status': 'PASS'}}) == 'OBSERVED TOLERANCE SATISFIED'


def test_hand_extraction_rejects_low_confidence_and_out_of_image_fingers(tmp_path, monkeypatch):
    import sys
    import types
    import cv2
    from app.validation.video_pose import extract_video_pose

    class Capture:
        frame = 0

        def isOpened(self):
            return True

        def get(self, key):
            return {cv2.CAP_PROP_FPS: 30, cv2.CAP_PROP_FRAME_WIDTH: 100,
                    cv2.CAP_PROP_FRAME_HEIGHT: 100,
                    cv2.CAP_PROP_POS_MSEC: (self.frame - 1) * 1000 / 30}[key]

        def read(self):
            self.frame += 1
            return (True, np.zeros((100, 100, 3), dtype=np.uint8)) if self.frame <= 2 else (False, None)

        def release(self):
            pass

    points = np.full((1, 133, 2), 50., dtype=float)
    scores = np.full((1, 133), .99)
    scores[0, 99] = .05  # high average confidence must not rescue the left index tip
    points[0, 120] = (150, 50)  # right index tip lies outside the image
    fake = types.ModuleType('rtmlib')
    fake.Wholebody = lambda **kwargs: lambda frame: (points, scores)
    monkeypatch.setitem(sys.modules, 'rtmlib', fake)
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *args: Capture())
    video = tmp_path / 'reference.mp4'
    video.write_bytes(b'fake video')
    output = tmp_path / 'pose.csv'
    meta = extract_video_pose(video, tmp_path / 'unused.task', output, include_elbows=True)
    with np.load(output.with_suffix('.upper.npz')) as data:
        assert np.isnan(data['hands'][:, 0, 8]).all()
        assert np.isnan(data['hands'][:, 1, 8]).all()
        assert np.isfinite(data['hands'][:, :, 9]).all()
    assert meta['upper_body']['hand_observed_frame_fraction'] == [0, 0]
