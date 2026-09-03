"""Derive calibration landmarks from the avatar's own bind pose.

The Signora Unity runtime is calibration-relative: whatever pose arrives during its 2s calibration
window is mapped onto the avatar's bind rotation, and every later frame is applied as a delta from
it. Feed it the performer's arms-down first frame and the avatar - whose bind pose is a T-pose -
picks up a ~90 degree offset on every sign.

Feeding it landmarks built from the avatar's *own* bind pose makes the reference an exact identity:
at calibration the delta is zero, and afterwards each bone points exactly where the suit says.

    python tools/extract_bind_pose.py <avatar.glb> -o data/calibration.json
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from app.ingest.landmarks import (  # noqa: E402
    FOOT_OFFSETS,
    HAND_LANDMARK_COUNT,
    HEAD_OFFSETS,
    POSE_LANDMARK_COUNT,
    TIP_LENGTH_RATIO,
)

# Unity humanoid/Mixamo bone names for each MediaPipe pose index we can source from the rig.
POSE_FROM_BONE = {
    11: "LeftArm", 12: "RightArm",
    13: "LeftForeArm", 14: "RightForeArm",
    15: "LeftHand", 16: "RightHand",
    17: "LeftHandPinky1", 18: "RightHandPinky1",
    19: "LeftHandIndex1", 20: "RightHandIndex1",
    21: "LeftHandThumb1", 22: "RightHandThumb1",
    23: "LeftUpLeg", 24: "RightUpLeg",
    25: "LeftLeg", 26: "RightLeg",
    27: "LeftFoot", 28: "RightFoot",
}
FOOT_BONE = {29: "LeftFoot", 30: "RightFoot", 31: "LeftFoot", 32: "RightFoot"}
FINGER_BASE = {"Thumb": 1, "Index": 5, "Middle": 9, "Ring": 13, "Pinky": 17}


def read_gltf(path: Path) -> dict:
    with path.open("rb") as f:
        magic, _version, _total = struct.unpack("<4sII", f.read(12))
        if magic != b"glTF":
            raise ValueError(f"{path.name} is not a binary glTF file.")
        length, _chunk_type = struct.unpack("<II", f.read(8))
        return json.loads(f.read(length))


def node_matrix(node: dict) -> np.ndarray:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    m = np.eye(4)
    if "scale" in node:
        m[:3, :3] = np.diag(node["scale"])
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        rot = np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ])
        m[:3, :3] = rot @ m[:3, :3]
    if "translation" in node:
        m[:3, 3] = node["translation"]
    return m


def world_positions(gltf: dict) -> dict[str, np.ndarray]:
    """World-space bind position of every named node, converted to Unity's axes."""
    nodes = gltf["nodes"]
    out: dict[str, np.ndarray] = {}

    def walk(index: int, parent: np.ndarray) -> None:
        node = nodes[index]
        world = parent @ node_matrix(node)
        name = node.get("name")
        if name:
            # com.unity.cloud.gltfast converts right-handed glTF to left-handed Unity by
            # negating X. Directions - which is all the retargeter uses - follow the same flip.
            out[name] = np.array([-world[0, 3], world[1, 3], world[2, 3]])
        for child in node.get("children", []):
            walk(child, world)

    scene = gltf.get("scenes", [{}])[gltf.get("scene", 0)]
    for root in scene.get("nodes", []):
        walk(root, np.eye(4))
    return out


def _extend(near: np.ndarray, far: np.ndarray) -> np.ndarray:
    """Fingertip beyond the last joint; the bind pose has straight fingers, so extend along it."""
    direction = far - near
    length = np.linalg.norm(direction)
    if length < 1e-9:
        return far.copy()
    return far + direction / length * length * TIP_LENGTH_RATIO


def build(gltf: dict) -> dict:
    pos = world_positions(gltf)

    missing = [b for b in POSE_FROM_BONE.values() if b not in pos]
    if missing:
        raise ValueError(f"avatar is missing required bones: {sorted(set(missing))}")

    pose = np.zeros((POSE_LANDMARK_COUNT, 3))
    for index, bone in POSE_FROM_BONE.items():
        pose[index] = pos[bone]

    right = pos["RightArm"] - pos["LeftArm"]
    right /= np.linalg.norm(right)
    up = pos["Head"] - pos["Hips"]
    up /= np.linalg.norm(up)
    forward = np.cross(right, up)
    forward /= np.linalg.norm(forward)
    up = np.cross(forward, right)

    head = pos["Head"]
    for index, (f, r, u) in HEAD_OFFSETS.items():
        pose[index] = head + forward * f + right * r + up * u
    for index, (_segment, along) in FOOT_OFFSETS.items():
        pose[index] = pos[FOOT_BONE[index]] + forward * along

    hands = {}
    for side in ("Left", "Right"):
        hand = np.zeros((HAND_LANDMARK_COUNT, 3))
        hand[0] = pos[f"{side}Hand"]
        for finger, base in FINGER_BASE.items():
            joints = [pos[f"{side}Hand{finger}{i}"] for i in (1, 2, 3)]
            for offset, joint in enumerate(joints):
                hand[base + offset] = joint
            hand[base + 3] = _extend(joints[-2], joints[-1])
        hands[side] = hand

    origin = (pose[23] + pose[24]) / 2.0

    return {
        "name": "avatar-bind-pose",
        "fps": 30,
        "frameCount": 1,
        "pose": [np.round(pose - origin, 5).tolist()],
        "leftHand": [np.round(hands["Left"] - origin, 5).tolist()],
        "rightHand": [np.round(hands["Right"] - origin, 5).tolist()],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("glb", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("data/calibration.json"))
    args = ap.parse_args()

    payload = build(read_gltf(args.glb))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload))

    pose = np.array(payload["pose"][0])
    span = np.linalg.norm(pose[12] - pose[11])
    upper = np.linalg.norm(pose[13] - pose[11])
    fore = np.linalg.norm(pose[15] - pose[13])
    arm_dir = (pose[13] - pose[11]) / upper
    print(f"wrote {args.out}")
    print(f"  shoulder span {span:.3f}m, upper arm {upper:.3f}m, forearm {fore:.3f}m")
    print(f"  left shoulder x={pose[11][0]:+.3f}  right shoulder x={pose[12][0]:+.3f}")
    print(f"  left upper-arm direction ({arm_dir[0]:+.2f},{arm_dir[1]:+.2f},{arm_dir[2]:+.2f})"
          f"  -> {'T-pose (horizontal)' if abs(arm_dir[1]) < 0.5 else 'arms down'}")


if __name__ == "__main__":
    main()
