import numpy as np
import pytest

from app.validation.case_study import (
    _handshape_errors,
    evaluate_functional_domain,
    intersection_union_decision,
    clip_level_certificate,
)
from app.services import analysis_service
from app.validation import case_study


@pytest.mark.parametrize('curve', [[], [np.nan, np.nan], [np.inf]])
def test_missing_domain_data_is_inconclusive(curve):
    result = evaluate_functional_domain(curve, .1, 'Handshape')
    assert result['status'] == 'INCONCLUSIVE'
    assert result['max_deviation'] is None
    assert result['valid_fraction'] == 0


def test_maximum_deviation_catches_short_severe_errors():
    result = evaluate_functional_domain([.01] * 100 + [.2], .1, 'Path')
    assert result['status'] == 'FAIL'
    assert result['mean_deviation'] < .1
    assert intersection_union_decision({'path': result}) == 'NOT EQUIVALENT'
    assert intersection_union_decision({}) == 'INCONCLUSIVE'


def test_handshape_removes_placement_and_scale_but_preserves_finger_errors():
    hand = np.stack((np.linspace(0, 1, 21), np.linspace(0, 2, 21)), axis=1)
    reference = np.broadcast_to(hand, (4, 2, 21, 2)).copy()
    prediction = reference * 3 + [200, -50]
    np.testing.assert_allclose(_handshape_errors(prediction, reference), 0, atol=1e-12)
    prediction[1, 0, 8] += [2, 0]
    assert _handshape_errors(prediction, reference)[1] > .1
    prediction[2, 1, 8] = np.nan
    assert np.isnan(_handshape_errors(prediction, reference)[2])


def test_legacy_eight_joint_data_marks_palm_unavailable():
    xy = np.ones((3, 8, 2))
    result = clip_level_certificate('legacy', xy, xy)
    assert result['domains']['palm_orientation']['status'] == 'INCONCLUSIVE'
    assert result['decision'] == 'INCONCLUSIVE'


def test_readiness_uses_dwpose_without_legacy_task_files(monkeypatch, tmp_path):
    monkeypatch.setattr(analysis_service.settings, 'analysis_pose_model', tmp_path / 'missing.task')
    seen = []
    def find_spec(name):
        seen.append(name)
        return object() if name != 'mediapipe' else None
    monkeypatch.setattr(analysis_service.importlib.util, 'find_spec', find_spec)
    assert analysis_service.readiness()['ready']
    assert 'rtmlib' in seen and 'onnxruntime' in seen
    assert 'mediapipe' not in seen


@pytest.mark.parametrize('yaw', [-150, -90, -30, 0, 45, 90, 170])
def test_front_projection_is_invariant_to_fbx_world_heading(yaw):
    from scipy.spatial.transform import Rotation
    from app.validation.case_study import primary_camera_fits, project
    body = np.array([
        [.5, 0, 0], [-.5, 0, 0], [.35, -1, 0], [-.35, -1, 0],
        [.7, -.3, .6], [-.7, -.2, .5], [.8, -.5, .3], [-.8, -.5, .4],
        [.75, -.25, .7], [-.75, -.15, .6],
    ])
    xyz = np.broadcast_to(body, (10, 10, 3)).copy()
    reference = xyz[..., :2] * [1, -1]
    rotation = Rotation.from_euler('y', yaw, degrees=True).as_matrix()
    rotated = xyz @ rotation.T
    fit = primary_camera_fits(rotated, reference, np.ones(10, dtype=bool), 'front')[0]
    np.testing.assert_allclose(project(rotated, fit), reference, atol=1e-12)
    # All 42 hand points use exactly the same fixed camera as the body.
    hands = np.broadcast_to([.75, -.3, .8], (10, 42, 3)).copy()
    np.testing.assert_allclose(project(hands @ rotation.T, fit), hands[..., :2] * [1, -1], atol=1e-12)
    assert fit['status'] == 'user_declared_front_view'


def test_declared_front_camera_does_not_fit_the_tested_arms(monkeypatch):
    from app.validation import case_study
    xyz = np.zeros((10, 10, 3))
    xyz[:, 0, 0], xyz[:, 1, 0] = .5, -.5
    reference = xyz[..., :2] * [1, -1]
    monkeypatch.setattr(case_study, 'camera_fits', lambda *args: pytest.fail('Free camera fitting should not run'))
    fit = case_study.primary_camera_fits(xyz, reference, np.ones(10, dtype=bool), 'front')[0]
    changed = reference.copy()
    changed[:, 4:] += 20
    other = case_study.primary_camera_fits(xyz, changed, np.ones(10, dtype=bool), 'front')[0]
    assert fit['rotation_vector_rad'] == other['rotation_vector_rad']
    assert fit['scale'] == other['scale']


def test_foreshortened_palm_is_unmeasured_not_a_180_degree_error():
    n = 40
    pred = np.zeros((n, 10, 2))
    pred[:, 0], pred[:, 1] = (-.5, 0), (.5, 0)
    pred[:, 4], pred[:, 5] = (-.5, 1), (.5, 1)
    pred[:, 8], pred[:, 9] = (-.5, 1.3), (.5, 1.3)
    ref = pred.copy()
    # Palm turned toward the camera: a few-pixel residual that points backwards.
    pred[-3:, 8] = (-.5, .99)
    left = case_study._direction_errors(pred[:, 8] - pred[:, 4], ref[:, 8] - ref[:, 4])
    assert np.all(np.isnan(left[-3:]))
    # The right palm stays measurable, so the frame verdict uses it alone.
    assert np.max(case_study._palm_orientation_errors(pred, ref)) < 1e-6


def test_mirrored_torso_yaw_pair_falls_back_to_front_view(monkeypatch):
    pair = [
        {"rotation_vector_rad": [0, np.radians(35), 0], "scale": 1.3, "torso_rmse": .03},
        {"rotation_vector_rad": [0, np.radians(-38), 0], "scale": 1.3, "torso_rmse": .034},
    ]
    monkeypatch.setattr(case_study, "camera_fits", lambda *args: pair)
    monkeypatch.setattr(case_study, "frontal_camera_fit", lambda *args: {
        "rotation_vector_rad": [0, 0, 0], "scale": 1.0,
    })
    xyz = np.zeros((10, 8, 3))
    fits = case_study.primary_camera_fits(xyz, xyz[..., :2], np.ones(10, bool))
    assert [f["status"] for f in fits] == ["automatic_yaw_unidentifiable_front_view"]
    assert not case_study._mirrored_yaw(pair[:1])
