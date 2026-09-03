"""The contract with the Signora Unity runtime, checked without Unity.

`BodyRetargeter` and `HandRetargeter` bind each bone to a *pair of landmark indices* and drive it by
`Quaternion.FromToRotation(referenceDirection, currentDirection) * bindWorldRotation`. Two things
therefore have to hold, and neither is visible from the Python side unless it is asserted here:

  1. Each landmark pair really does correspond to the bone it drives. Mis-numbering index 17 and 19,
     say, would silently swap a finger for a thumb and still produce smooth, wrong motion.
  2. The calibration pose's directions match the avatar's bind pose, so the reference maps to
     identity and signs play at their true orientation rather than offset by the difference between
     the performer's resting pose and the avatar's T-pose.

The bindings below mirror the C# in SignoraAvatarTracking/Assets/Signora/Runtime/Retargeting/.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.extract_bind_pose import build, read_gltf, world_positions  # noqa: E402

GLB = Path(
    "/Users/duveen/Projects/ SignSure/SignoraAvatarTracking/Assets/Models/Avaturn/"
    "SignoraNewAvatar.glb"
)

# (bone, fromLandmark, toLandmark, childBone or None when the landmark is a synthesised tip)
BODY_BINDINGS = [
    ("LeftArm", 11, 13, "LeftForeArm"),
    ("LeftForeArm", 13, 15, "LeftHand"),
    ("RightArm", 12, 14, "RightForeArm"),
    ("RightForeArm", 14, 16, "RightHand"),
]

FINGER_LANDMARKS = {
    "Thumb": [1, 2, 3, 4], "Index": [5, 6, 7, 8], "Middle": [9, 10, 11, 12],
    "Ring": [13, 14, 15, 16], "Pinky": [17, 18, 19, 20],
}


def hand_bindings(side):
    out = []
    for finger, marks in FINGER_LANDMARKS.items():
        for segment in range(3):
            child = f"{side}Hand{finger}{segment + 2}" if segment < 2 else None
            out.append((f"{side}Hand{finger}{segment + 1}", marks[segment], marks[segment + 1], child))
    return out


def unit(v):
    return v / np.linalg.norm(v)


def angle_between(a, b):
    return float(np.degrees(np.arccos(np.clip(np.dot(unit(a), unit(b)), -1.0, 1.0))))


@pytest.fixture(scope="module")
def rig():
    if not GLB.exists():
        pytest.skip("avatar GLB not present")
    gltf = read_gltf(GLB)
    return world_positions(gltf), build(gltf)


def test_body_landmark_pairs_match_the_bones_they_drive(rig):
    positions, payload = rig
    pose = np.array(payload["pose"][0])
    for bone, a, b, child in BODY_BINDINGS:
        bind_dir = positions[child] - positions[bone]
        landmark_dir = pose[b] - pose[a]
        off = angle_between(bind_dir, landmark_dir)
        assert off < 1.0, f"{bone}: landmarks {a}->{b} are {off:.1f} deg off the bone direction"


def test_finger_landmark_pairs_match_the_bones_they_drive(rig):
    positions, payload = rig
    for side, key in (("Left", "leftHand"), ("Right", "rightHand")):
        hand = np.array(payload[key][0])
        for bone, a, b, child in hand_bindings(side):
            if child is None:
                continue   # tip is synthesised; covered by the test below
            off = angle_between(positions[child] - positions[bone], hand[b] - hand[a])
            assert off < 1.0, f"{bone}: landmarks {a}->{b} are {off:.1f} deg off the bone direction"


def test_synthesised_fingertips_continue_their_finger(rig):
    """The last bone of each finger is driven by distal->tip, so the tip must extend it."""
    _positions, payload = rig
    for key in ("leftHand", "rightHand"):
        hand = np.array(payload[key][0])
        for marks in FINGER_LANDMARKS.values():
            previous = hand[marks[2]] - hand[marks[1]]
            tip = hand[marks[3]] - hand[marks[2]]
            assert np.linalg.norm(tip) > 1e-4
            assert angle_between(previous, tip) < 1.0


def test_palm_basis_is_non_degenerate_in_the_calibration_pose(rig):
    """HandRetargeter builds the palm from wrist/index-MCP/pinky-MCP via TryBasis."""
    _positions, payload = rig
    for key in ("leftHand", "rightHand"):
        hand = np.array(payload[key][0])
        right = unit(hand[5] - hand[0])
        up_seed = unit(hand[17] - hand[0])
        forward = np.cross(right, up_seed)
        # TryBasis bails when the cross product collapses.
        assert np.linalg.norm(forward) > 1e-3


def test_calibration_pose_is_the_avatar_t_pose(rig):
    """The reference must be the avatar's bind pose, not the performer's resting pose."""
    _positions, payload = rig
    pose = np.array(payload["pose"][0])
    left_arm = unit(pose[13] - pose[11])
    right_arm = unit(pose[14] - pose[12])
    # Arms out sideways: dominated by X, near-zero vertical component.
    assert abs(left_arm[1]) < 0.35, f"left arm is not horizontal: {left_arm}"
    assert abs(right_arm[1]) < 0.35, f"right arm is not horizontal: {right_arm}"
    assert left_arm[0] < -0.85 and right_arm[0] > 0.85


def test_left_and_right_are_not_mirrored(rig):
    """A flipped X conversion would put the avatar's left arm on its right side."""
    _positions, payload = rig
    pose = np.array(payload["pose"][0])
    assert pose[11][0] < 0 < pose[12][0], "left/right shoulders are swapped"
    assert pose[23][0] < 0 < pose[24][0], "left/right hips are swapped"


def _from_to_rotation(a, b):
    """Unity's Quaternion.FromToRotation, which is what DirectionBoneBinding applies."""
    from scipy.spatial.transform import Rotation
    a, b = unit(a), unit(b)
    axis = np.cross(a, b)
    dot = float(np.clip(np.dot(a, b), -1.0, 1.0))
    if np.linalg.norm(axis) < 1e-12:
        if dot > 0:
            return Rotation.identity()
        perp = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        axis = unit(np.cross(a, perp))
        return Rotation.from_rotvec(axis * np.pi)
    return Rotation.from_quat(np.append(axis, 1.0 + dot) / np.linalg.norm(np.append(axis, 1.0 + dot)))


def test_replaying_the_reference_pose_moves_nothing(rig):
    """Calibrating on this pose and immediately replaying it must produce a zero delta."""
    _positions, payload = rig
    pose = np.array(payload["pose"][0])
    for bone, a, b, _child in BODY_BINDINGS:
        direction = pose[b] - pose[a]
        delta = _from_to_rotation(direction, direction)
        assert np.degrees(delta.magnitude()) < 1e-4, f"{bone} drifts at the reference pose"


def test_retarget_points_the_bone_along_the_measured_direction(rig, hello_take):
    """The whole point of the binding: the bone ends up along the landmark direction.

    Simulates DirectionBoneBinding.Apply - delta = FromToRotation(reference, current) - and checks
    the bone axis it produces, which at bind time points along the reference, lands on the current
    direction for every frame of a real take.
    """
    from app.ingest.landmarks import to_landmarks
    _positions, payload = rig
    reference = np.array(payload["pose"][0])
    take = to_landmarks(hello_take).pose

    for bone, a, b, _child in BODY_BINDINGS:
        ref_dir = unit(reference[b] - reference[a])
        for frame in range(0, len(take), 7):
            current = unit(take[frame, b] - take[frame, a])
            produced = _from_to_rotation(ref_dir, current).apply(ref_dir)
            off = angle_between(produced, current)
            assert off < 0.01, f"{bone} frame {frame}: bone lands {off:.3f} deg off target"


def test_a_forehead_sign_actually_raises_the_hand(rig):
    """End-to-end sanity: FATHER is signed at the forehead, so the right wrist must rise."""
    from app.ingest.landmarks import to_landmarks
    from app.ingest.rokoko import parse_csv
    source = Path(
        "/Users/duveen/Library/Application Support/com.RokokoElectronics.RokokoStudio/"
        "Exports/Father.csv"
    )
    if not source.exists():
        pytest.skip("Father.csv not available")

    pose = to_landmarks(parse_csv(source)).pose
    right_wrist_y = pose[:, 16, 1]
    right_shoulder_y = pose[:, 12, 1]

    assert right_wrist_y.min() < right_shoulder_y.mean(), "wrist never starts below the shoulder"
    assert right_wrist_y.max() > right_shoulder_y.mean(), "wrist never rises above the shoulder"
    # And the left hand stays down - this is a one-handed sign.
    assert pose[:, 15, 1].max() < right_wrist_y.max()


def test_avatar_and_performer_proportions_are_comparable(rig, hello_take):
    """Wildly different limb ratios would make direction-only retargeting read wrong."""
    from app.ingest.landmarks import to_landmarks
    _positions, payload = rig
    avatar = np.array(payload["pose"][0])
    performer = to_landmarks(hello_take).pose.mean(axis=0)

    for name, (a, b) in {"upper arm": (11, 13), "forearm": (13, 15), "shoulders": (11, 12)}.items():
        av = np.linalg.norm(avatar[b] - avatar[a])
        pf = np.linalg.norm(performer[b] - performer[a])
        assert 0.6 < av / pf < 1.6, f"{name}: avatar {av:.3f}m vs performer {pf:.3f}m"
