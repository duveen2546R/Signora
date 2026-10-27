"""Landmark frames must satisfy the Unity runtime's contract exactly.

`CanonicalTrackingFrameV1.IsStructurallyValid` rejects a frame outright if the counts are wrong, and
`BodyRetargeter`/`HandRetargeter` bind to specific indices - so these tests encode the contract that
`SignoraAvatarTracking/Assets/Signora/Runtime/` actually enforces.
"""
import numpy as np
from dataclasses import replace

from app.ingest.landmarks import (
    HAND_LANDMARK_COUNT,
    POSE_LANDMARK_COUNT,
    to_landmarks,
)

# Indices BodyRetargeter lists as required.
BODY_REQUIRED = (11, 12, 13, 14, 15, 16, 23, 24)
# Indices HandRetargeter binds: palm basis 0/5/17, plus every finger chain.
HAND_REQUIRED = tuple(range(21))


def test_landmark_counts_match_the_unity_schema(hello_take):
    lt = to_landmarks(hello_take)
    assert lt.pose.shape == (hello_take.frame_count, POSE_LANDMARK_COUNT, 3)
    assert lt.left_hand.shape == (hello_take.frame_count, HAND_LANDMARK_COUNT, 3)
    assert lt.right_hand.shape == (hello_take.frame_count, HAND_LANDMARK_COUNT, 3)


def test_every_landmark_is_finite(hello_take):
    lt = to_landmarks(hello_take)
    for track in (lt.pose, lt.left_hand, lt.right_hand):
        assert np.all(np.isfinite(track))


def test_required_landmarks_are_never_degenerate(hello_take):
    """A zero-length direction makes RetargetingMath.TryDirection bail and the bone freeze."""
    lt = to_landmarks(hello_take)
    for index in BODY_REQUIRED:
        assert np.abs(lt.pose[:, index]).sum() > 0
    for hand in (lt.left_hand, lt.right_hand):
        for index in HAND_REQUIRED:
            assert np.all(np.isfinite(hand[:, index]))


def test_arm_chain_directions_are_well_formed(hello_take):
    """Shoulder->elbow and elbow->wrist must have real length in every frame."""
    lt = to_landmarks(hello_take)
    for a, b in ((11, 13), (13, 15), (12, 14), (14, 16)):
        length = np.linalg.norm(lt.pose[:, b] - lt.pose[:, a], axis=1)
        assert length.min() > 0.05, f"landmark {a}->{b} collapses to {length.min():.4f}m"


def test_limb_lengths_are_anatomically_plausible(hello_take):
    lt = to_landmarks(hello_take)
    upper = np.linalg.norm(lt.pose[:, 13] - lt.pose[:, 11], axis=1).mean()
    fore = np.linalg.norm(lt.pose[:, 15] - lt.pose[:, 13], axis=1).mean()
    span = np.linalg.norm(lt.pose[:, 12] - lt.pose[:, 11], axis=1).mean()
    assert 0.20 < upper < 0.45
    assert 0.20 < fore < 0.40
    assert 0.25 < span < 0.55


def test_finger_phalanges_shorten_towards_the_tip(hello_take):
    """Sanity on the synthesised tip: a distal phalanx is shorter than the one before it."""
    lt = to_landmarks(hello_take)
    for base in (5, 9, 13, 17):   # index, middle, ring, pinky MCPs
        lengths = [
            np.linalg.norm(lt.right_hand[:, base + i + 1] - lt.right_hand[:, base + i], axis=1).mean()
            for i in range(3)
        ]
        assert lengths[0] > lengths[1] > lengths[2], f"finger at {base}: {lengths}"


def test_fingertip_is_a_real_extension_not_a_duplicate(hello_take):
    """The tip must sit beyond the distal joint, or the last finger bone has no direction."""
    lt = to_landmarks(hello_take)
    for tip, distal in ((8, 7), (12, 11), (16, 15), (20, 19), (4, 3)):
        gap = np.linalg.norm(lt.right_hand[:, tip] - lt.right_hand[:, distal], axis=1)
        assert gap.min() > 0.005, f"tip {tip} collapses onto joint {distal}"


def test_palm_basis_is_non_degenerate(hello_take):
    """HandRetargeter builds the palm basis from wrist/index-MCP/pinky-MCP; they must not be collinear."""
    lt = to_landmarks(hello_take)
    for hand in (lt.left_hand, lt.right_hand):
        right = hand[:, 5] - hand[:, 0]
        up = hand[:, 17] - hand[:, 0]
        area = np.linalg.norm(np.cross(right, up), axis=1)
        assert area.min() > 1e-4, "palm landmarks are collinear"


def test_payload_is_json_serialisable_and_compact(hello_take):
    import json
    payload = to_landmarks(hello_take).to_payload()
    blob = json.dumps(payload)
    assert payload["frameCount"] == hello_take.frame_count
    assert payload["fps"] == 30
    per_second = len(blob) / (hello_take.frame_count / payload["fps"])
    assert per_second < 400_000, f"{per_second:.0f} bytes/second is too heavy to stream"


def test_hips_are_the_origin(hello_take):
    """Recentred on the hip midpoint, as MediaPipe world landmarks are."""
    lt = to_landmarks(hello_take)
    midpoint = (lt.pose[:, 23] + lt.pose[:, 24]) / 2.0
    assert np.abs(midpoint).max() < 1e-9


def test_phase_metadata_survives_landmark_preparation(hello_take):
    from app.ingest.compose import prepare
    from app.ingest.landmarks import LandmarkSkeleton, LandmarkTake

    authored = replace(
        to_landmarks(hello_take),
        sign_start_s=0.8,
        sign_end_s=1.8,
        phase_source="authored-ui",
        phase_reviewed=True,
    )
    prepared = prepare(authored, LandmarkSkeleton.from_takes(authored))
    payload = prepared.to_payload()
    restored = LandmarkTake.from_payload(payload)
    assert restored.sign_start_s == prepared.sign_start_s
    assert restored.sign_end_s == prepared.sign_end_s
    assert restored.phase_source == "authored-ui"
    assert restored.phase_reviewed is True


def test_original_csv_clock_survives_payload_and_slicing(hello_take):
    from dataclasses import replace
    from app.ingest.landmarks import LandmarkTake, to_landmarks, slice_frames
    times = hello_take.times.copy()
    times[10] += 0.003
    raw = to_landmarks(replace(hello_take, times=times))
    restored = LandmarkTake.from_payload(raw.to_payload())
    np.testing.assert_array_equal(restored.times, times)
    cropped = slice_frames(restored, 10, 40)
    np.testing.assert_array_equal(cropped.times, times[10:40] - times[10])
