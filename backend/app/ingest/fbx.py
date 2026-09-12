"""Read a combined Rokoko Mixamo FBX into Signora's body, hand, and face tracks."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .landmarks import (
    ARKIT_BLENDSHAPES,
    FACE_BLENDSHAPE_COUNT,
    FOOT_OFFSETS,
    HAND_LANDMARK_COUNT,
    HEAD_OFFSETS,
    POSE_LANDMARK_COUNT,
    TIP_LENGTH_RATIO,
    LandmarkTake,
)
from .rokoko import RokokoFormatError

try:
    import ufbx
except ImportError:  # pragma: no cover - surfaced as a useful ingest error
    ufbx = None


class FbxFormatError(RokokoFormatError):
    """The file is not the supported combined Rokoko Mixamo FBX export."""


REQUIRED_FPS = 60.0

POSE_BONES = {
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

FINGER_BASE = {"Thumb": 1, "Index": 5, "Middle": 9, "Ring": 13, "Pinky": 17}
FINGER_BONES = tuple(
    f"{side}Hand{finger}{joint}"
    for side in ("Left", "Right")
    for finger in FINGER_BASE
    for joint in (1, 2, 3)
)
REQUIRED_BONES = frozenset({"Head", *POSE_BONES.values(), *FINGER_BONES})


def _clean_name(name: str) -> str:
    """Remove hierarchy/namespace decorations without fuzzy bone-name guessing."""
    return name.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def _canonical_face_name(name: str) -> str | None:
    cleaned = _clean_name(name).rsplit(".", 1)[-1]
    lowered = cleaned.lower()
    exact = {candidate.lower(): candidate for candidate in ARKIT_BLENDSHAPES}
    if lowered in exact:
        return exact[lowered]
    # Rokoko/FBX exporters may prefix the deformer name while keeping the ARKit token as a suffix.
    matches = [candidate for candidate in ARKIT_BLENDSHAPES if lowered.endswith(candidate.lower())]
    return matches[0] if len(matches) == 1 else None


def _vec(value) -> np.ndarray:
    return np.array([value.x, value.y, value.z], dtype=np.float64)


def _node_maps(scene) -> tuple[dict[str, int], dict[str, list[str]]]:
    indices: dict[str, int] = {}
    duplicates: dict[str, list[str]] = {}
    for index in range(len(scene.nodes)):
        raw = scene.nodes[index].name
        name = _clean_name(raw)
        if name in indices:
            duplicates.setdefault(name, []).append(raw)
        else:
            indices[name] = index
    return indices, duplicates


def _face_channels(scene) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for index in range(len(scene.blend_channels)):
        canonical = _canonical_face_name(scene.blend_channels[index].name)
        if canonical is not None:
            found.setdefault(canonical, []).append(index)
    return found


def _matrix_axis(matrix, index: int) -> np.ndarray:
    return _vec((matrix.c0, matrix.c1, matrix.c2)[index])


def _tip_axis_signatures(scene, nodes: dict[str, int]) -> dict[str, tuple[int, float]]:
    """Find the terminal bone's local direction from its first-frame world basis."""
    signatures = {}
    for side in ("Left", "Right"):
        for finger in FINGER_BASE:
            near = scene.nodes[nodes[f"{side}Hand{finger}2"]].node_to_world.c3
            far_node = scene.nodes[nodes[f"{side}Hand{finger}3"]]
            direction = _vec(far_node.node_to_world.c3) - _vec(near)
            norm = np.linalg.norm(direction)
            if norm < 1e-8:
                raise FbxFormatError(f"{side} {finger} terminal finger segment is degenerate.")
            direction /= norm
            candidates = []
            for axis in range(3):
                basis = _matrix_axis(far_node.node_to_world, axis)
                basis /= max(np.linalg.norm(basis), 1e-12)
                candidates.append(float(np.dot(direction, basis)))
            axis = int(np.argmax(np.abs(candidates)))
            signatures[f"{side}Hand{finger}3"] = (axis, 1.0 if candidates[axis] >= 0 else -1.0)
    return signatures


def _sample_hand(evaluated, nodes: dict[str, int], tips, side: str) -> np.ndarray:
    hand = np.zeros((HAND_LANDMARK_COUNT, 3), dtype=np.float64)
    hand[0] = _vec(evaluated.nodes[nodes[f"{side}Hand"]].node_to_world.c3)
    for finger, base in FINGER_BASE.items():
        points = [
            _vec(evaluated.nodes[nodes[f"{side}Hand{finger}{joint}"]].node_to_world.c3)
            for joint in (1, 2, 3)
        ]
        hand[base:base + 3] = points
        segment_length = np.linalg.norm(points[2] - points[1]) * TIP_LENGTH_RATIO
        node = evaluated.nodes[nodes[f"{side}Hand{finger}3"]]
        axis, sign = tips[f"{side}Hand{finger}3"]
        direction = _matrix_axis(node.node_to_world, axis) * sign
        direction /= max(np.linalg.norm(direction), 1e-12)
        hand[base + 3] = points[2] + direction * segment_length
    return hand


def parse_fbx(path: str | Path, name: str | None = None) -> LandmarkTake:
    """Parse the supported FBX profile and sample its only take at the exported 60 FPS clock."""
    if ufbx is None:
        raise FbxFormatError("FBX support is not installed; install backend requirements.")
    path = Path(path)
    try:
        scene = ufbx.load_file(
            str(path),
            target_axes=ufbx.axes_left_handed_y_up,
            target_unit_meters=1.0,
            space_conversion=ufbx.SpaceConversion.ADJUST_TRANSFORMS,
            ignore_embedded=True,
            load_external_files=False,
        )
    except Exception as exc:
        raise FbxFormatError(f"{path.name}: could not read FBX: {exc}") from exc

    fps = float(scene.settings.frames_per_second)
    if abs(fps - REQUIRED_FPS) > 0.01:
        raise FbxFormatError(
            f"{path.name}: expected a 60 FPS Rokoko export, but the FBX declares {fps:g} FPS."
        )
    if len(scene.anim_stacks) != 1:
        raise FbxFormatError(
            f"{path.name}: expected exactly one animation take, found {len(scene.anim_stacks)}."
        )
    stack = scene.anim_stacks[0]
    duration = float(stack.time_end - stack.time_begin)
    if not np.isfinite(duration) or duration <= 0:
        raise FbxFormatError(f"{path.name}: the animation take is empty.")

    nodes, duplicate_nodes = _node_maps(scene)
    missing_bones = sorted(REQUIRED_BONES - nodes.keys())
    ambiguous = sorted(REQUIRED_BONES & duplicate_nodes.keys())
    if missing_bones or ambiguous:
        raise FbxFormatError(
            f"{path.name}: FBX is not the required Mixamo skeleton. "
            f"Missing bones: {missing_bones[:8]}; ambiguous bones: {ambiguous[:8]}."
        )

    face_channels = _face_channels(scene)
    missing_face = [channel for channel in ARKIT_BLENDSHAPES if channel not in face_channels]
    if missing_face:
        raise FbxFormatError(
            f"{path.name}: face capture is incomplete; missing {len(missing_face)} ARKit channels, "
            f"including {missing_face[:8]}. Export the combined body+face FBX."
        )

    frame_count = int(round(duration * fps)) + 1
    times = np.arange(frame_count, dtype=np.float64) / fps
    absolute_times = stack.time_begin + times
    first = ufbx.evaluate_scene(scene, stack.anim, float(absolute_times[0]))
    tips = _tip_axis_signatures(first, nodes)

    pose_frames = np.zeros((frame_count, POSE_LANDMARK_COUNT, 3), dtype=np.float64)
    left_frames = np.zeros((frame_count, HAND_LANDMARK_COUNT, 3), dtype=np.float64)
    right_frames = np.zeros_like(left_frames)
    face_frames = np.zeros((frame_count, FACE_BLENDSHAPE_COUNT), dtype=np.float64)

    for frame, at in enumerate(absolute_times):
        evaluated = ufbx.evaluate_scene(scene, stack.anim, float(at))
        pose = pose_frames[frame]
        for index, bone in POSE_BONES.items():
            pose[index] = _vec(evaluated.nodes[nodes[bone]].node_to_world.c3)

        head_matrix = evaluated.nodes[nodes["Head"]].node_to_world
        head = _vec(head_matrix.c3)
        right = _matrix_axis(head_matrix, 0)
        up = _matrix_axis(head_matrix, 1)
        forward = _matrix_axis(head_matrix, 2)
        right /= max(np.linalg.norm(right), 1e-12)
        up /= max(np.linalg.norm(up), 1e-12)
        forward /= max(np.linalg.norm(forward), 1e-12)
        for index, (along_forward, along_right, along_up) in HEAD_OFFSETS.items():
            pose[index] = head + forward * along_forward + right * along_right + up * along_up
        for index, (_segment, along) in FOOT_OFFSETS.items():
            foot = evaluated.nodes[nodes["LeftFoot" if index % 2 else "RightFoot"]].node_to_world
            direction = _matrix_axis(foot, 2)
            direction /= max(np.linalg.norm(direction), 1e-12)
            pose[index] = _vec(foot.c3) + direction * along

        left_frames[frame] = _sample_hand(evaluated, nodes, tips, "Left")
        right_frames[frame] = _sample_hand(evaluated, nodes, tips, "Right")

        for column, canonical in enumerate(ARKIT_BLENDSHAPES):
            values = np.array([
                scene.blend_channels[channel].evaluate_blend_weight(stack.anim, float(at)) / 100.0
                for channel in face_channels[canonical]
            ])
            if not np.all(np.isfinite(values)):
                raise FbxFormatError(f"{path.name}: {canonical} contains a non-finite weight.")
            if values.max() - values.min() > 0.005:
                raise FbxFormatError(
                    f"{path.name}: duplicate {canonical} channels disagree at frame {frame + 1}."
                )
            face_frames[frame, column] = np.clip(values.mean(), 0.0, 1.0)

    origin = ((pose_frames[:, 23] + pose_frames[:, 24]) / 2.0)[:, None, :]
    return LandmarkTake(
        name=name or path.stem,
        fps=fps,
        pose=pose_frames - origin,
        left_hand=left_frames - origin,
        right_hand=right_frames - origin,
        face_blendshapes=face_frames,
        timestamps=times,
    )
