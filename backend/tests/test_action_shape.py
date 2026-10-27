import numpy as np

from app.validation.action_shape import (
    body_features,
    bounded_path,
    circular_difference,
    hand_features,
    interpolate_extra,
    per_reference_errors,
)


def test_known_angles_and_circular_wrap():
    points = np.array(
        [[[1.0, 0], [-1, 0], [1, 2], [-1, 2], [2, 1], [-2, 1], [1, 1], [-1, 1]]]
    )
    features = body_features(points)[0]
    np.testing.assert_allclose(
        features[[0, 2, 3, 4, 5, 6, 7]], [0, 90, 90, 0, 180, 90, 90]
    )
    assert circular_difference(179, -179) == 2


def test_arm_shape_invariant_to_individual_segment_length():
    first = np.array(
        [[[1.0, 0], [-1, 0], [1, 2], [-1, 2], [2, 1], [-2, 1], [1, 1], [-1, 1]]]
    )
    second = first.copy()
    second[:, 6, 1] = 3
    second[:, 4] = [5, 3]
    np.testing.assert_allclose(body_features(first), body_features(second))


def test_local_speed_change_aligns_without_erasing_wrong_shape():
    phase = np.linspace(0, 1, 101)
    ref = np.zeros((101, 8))
    pred = ref.copy()
    ref[:, 2:6] = (70 * np.sin(2 * np.pi * phase))[:, None]
    pred[:, 2:6] = (70 * np.sin(2 * np.pi * (phase + 0.07 * np.sin(np.pi * phase))))[
        :, None
    ]
    path = bounded_path(ref, pred)
    assert tuple(path[0]) == (0, 0) and tuple(path[-1]) == (100, 100)
    assert max(abs(path[:, 0] - path[:, 1])) <= 10
    assert set(path[:, 0]) == set(range(101)) and set(path[:, 1]) == set(range(101))
    before = circular_difference(ref[:, 2:6], pred[:, 2:6]).mean()
    after = per_reference_errors(ref, pred, path)[:, 2:6].mean()
    assert after < before * 0.5
    wrong = pred.copy()
    wrong[:, 2:6] += 90
    assert (
        per_reference_errors(ref, wrong, bounded_path(ref, wrong))[:, 2:6].mean() > 35
    )


def test_reversed_order_not_freely_matched():
    ref = np.zeros((101, 8))
    ref[:, 2:6] = np.linspace(-80, 80, 101)[:, None]
    rev = ref[::-1]
    assert per_reference_errors(ref, rev, bounded_path(ref, rev))[:, 2:6].mean() > 50


def test_reference_samples_equal_weight_and_no_missing_imputation():
    reference = np.zeros((3, 8))
    pred = np.ones((3, 8)) * 10
    reference[1] = np.nan
    errors = per_reference_errors(
        reference, pred, np.array([[0, 0], [0, 1], [1, 1], [2, 2]])
    )
    assert np.isnan(errors[1]).all()
    np.testing.assert_allclose(errors[[0, 2]], 10)
    points = np.zeros((4, 21, 2))
    points[1:3] = np.nan
    assert np.isnan(interpolate_extra(np.arange(4) * 0.1, points, [0.15])).all()


def test_missing_hand_does_not_become_zero_error():
    values, names = hand_features(np.full((101, 21, 2), np.nan))
    assert len(names) == 17 and np.isnan(values).all()


def test_native_finger_bends_ignore_rigid_hand_rotation():
    from scipy.spatial.transform import Rotation

    hand = np.zeros((21, 3))
    for f in range(5):
        base = 1 + f * 4
        hand[base : base + 4] = [
            [f + 1, 1, 0],
            [f + 1, 2, 0],
            [f + 1, 2.8, 0.6],
            [f + 1, 3.2, 1.5],
        ]
    rotations = Rotation.from_euler("xyz", [[0, 0, 0], [45, 80, -20]], degrees=True)
    moving = np.stack([rotation.apply(hand) for rotation in rotations])
    values, _ = hand_features(moving)
    np.testing.assert_allclose(values[0, :15], values[1, :15], atol=1e-6)
    moving[1, 3] += [1, -1, 0]
    articulated, _ = hand_features(moving)
    assert abs(articulated[1, 1] - articulated[0, 1]) > 1


def test_foreshortened_segment_has_no_direction_score():
    points = np.array(
        [[[1.0, 0], [-1, 0], [1, 2], [-1, 2], [2, 1], [-2, 1], [1, 0.001], [-1, 1]]]
    )
    result = body_features(points)
    assert np.isnan(result[0, 2]) and np.isnan(result[0, 6])
