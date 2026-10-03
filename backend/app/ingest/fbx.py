"""Read a combined Rokoko Mixamo FBX into Signora's body, hand, and face tracks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


def _node_maps(scene_nodes) -> tuple[dict[str, int], dict[str, list[str]]]:
    indices: dict[str, int] = {}
    duplicates: dict[str, list[str]] = {}
    for index in range(len(scene_nodes)):
        raw = scene_nodes[index].name
        name = _clean_name(raw)
        if name in indices:
            duplicates.setdefault(name, []).append(raw)
        else:
            indices[name] = index
    return indices, duplicates


def _face_channels(channels) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for index in range(len(channels)):
        canonical = _canonical_face_name(channels[index].name)
        if canonical is not None:
            found.setdefault(canonical, []).append(index)
    return found


def _matrix_axis(matrix, index: int) -> np.ndarray:
    return _vec((matrix.c0, matrix.c1, matrix.c2)[index])


def _bind_axes(source_nodes, nodes):
    """Align the source rest skeleton with the avatar's +X right, +Y up, +Z front."""
    def position(bone):
        return _vec(source_nodes[nodes[bone]].node_to_world.c3)

    right = position("RightArm") - position("LeftArm")
    right[1] = 0.0
    length = np.linalg.norm(right)
    if length < 1e-8:
        raise FbxFormatError("The FBX rest skeleton has degenerate shoulder positions.")
    right /= length
    up = np.array([0.0, 1.0, 0.0])
    basis = np.column_stack((right, up, np.cross(right, up)))
    head_matrix = source_nodes[nodes["Head"]].node_to_world
    head_basis = np.column_stack([_matrix_axis(head_matrix, i) for i in range(3)])
    # Mixamo bone-local axes are not anatomical face axes. Preserve animated head rotation
    # relative to its rest transform while placing synthetic facial points anatomically.
    return basis.T, np.linalg.solve(head_basis, basis)


def _snapshot_scene(scene):
    """Copy native node matrices before any child wrappers can be released."""
    native_list = scene.nodes
    native_nodes = [native_list[i] for i in range(len(native_list))]
    matrices = [node.node_to_world for node in native_nodes]
    copied = []
    for node, matrix in zip(native_nodes, matrices):
        columns = [matrix.c0, matrix.c1, matrix.c2, matrix.c3]
        copied.append(SimpleNamespace(name=node.name, node_to_world=SimpleNamespace(**{
            f"c{i}": SimpleNamespace(x=column.x, y=column.y, z=column.z)
            for i, column in enumerate(columns)
        })))
    return SimpleNamespace(nodes=copied, _owners=(scene, native_list, native_nodes, matrices))


def _tip_axis_signatures(scene, nodes: dict[str, int]) -> dict[str, tuple[int, float]]:
    """Find the terminal bone's local direction from its first-frame world basis."""
    signatures = {}
    scene_nodes = scene.nodes
    for side in ("Left", "Right"):
        for finger in FINGER_BASE:
            near_node = scene_nodes[nodes[f"{side}Hand{finger}2"]]
            near_matrix = near_node.node_to_world
            near = near_matrix.c3
            far_node = scene_nodes[nodes[f"{side}Hand{finger}3"]]
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
    scene_nodes = evaluated.nodes
    hand = np.zeros((HAND_LANDMARK_COUNT, 3), dtype=np.float64)
    hand[0] = _vec(scene_nodes[nodes[f"{side}Hand"]].node_to_world.c3)
    for finger, base in FINGER_BASE.items():
        points = [
            _vec(scene_nodes[nodes[f"{side}Hand{finger}{joint}"]].node_to_world.c3)
            for joint in (1, 2, 3)
        ]
        hand[base:base + 3] = points
        segment_length = np.linalg.norm(points[2] - points[1]) * TIP_LENGTH_RATIO
        node = scene_nodes[nodes[f"{side}Hand{finger}3"]]
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
            # Apply handedness/unit conversion at the scene root. Adjusting each animated
            # transform can invert Rokoko's Y axis when rotation curves are evaluated.
            space_conversion=ufbx.SpaceConversion.TRANSFORM_ROOT,
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
    # Keep native list owners alive while their children are accessed (ufbx-python 0.0.5).
    stacks = scene.anim_stacks
    native_nodes = scene.nodes
    source_nodes = [native_nodes[i] for i in range(len(native_nodes))]
    native_channels = scene.blend_channels
    channels = [native_channels[i] for i in range(len(native_channels))]
    if len(stacks) != 1:
        raise FbxFormatError(
            f"{path.name}: expected exactly one animation take, found {len(stacks)}."
        )
    stack = stacks[0]
    animation = stack.anim
    duration = float(stack.time_end - stack.time_begin)
    if not np.isfinite(duration) or duration <= 0:
        raise FbxFormatError(f"{path.name}: the animation take is empty.")

    nodes, duplicate_nodes = _node_maps(source_nodes)
    missing_bones = sorted(REQUIRED_BONES - nodes.keys())
    ambiguous = sorted(REQUIRED_BONES & duplicate_nodes.keys())
    if missing_bones or ambiguous:
        raise FbxFormatError(
            f"{path.name}: FBX is not the required Mixamo skeleton. "
            f"Missing bones: {missing_bones[:8]}; ambiguous bones: {ambiguous[:8]}."
        )

    face_channels = _face_channels(channels)
    missing_face = [channel for channel in ARKIT_BLENDSHAPES if channel not in face_channels]
    if missing_face:
        raise FbxFormatError(
            f"{path.name}: face capture is incomplete; missing {len(missing_face)} ARKit channels, "
            f"including {missing_face[:8]}. Export the combined body+face FBX."
        )

    alignment, head_offsets_basis = _bind_axes(source_nodes, nodes)

    frame_count = int(round(duration * fps)) + 1
    times = np.arange(frame_count, dtype=np.float64) / fps
    absolute_times = stack.time_begin + times
    first = ufbx.evaluate_scene(scene, animation, float(absolute_times[0]))
    first_snapshot = _snapshot_scene(first)
    tips = _tip_axis_signatures(first_snapshot, nodes)

    pose_frames = np.zeros((frame_count, POSE_LANDMARK_COUNT, 3), dtype=np.float64)
    left_frames = np.zeros((frame_count, HAND_LANDMARK_COUNT, 3), dtype=np.float64)
    right_frames = np.zeros_like(left_frames)
    face_frames = np.zeros((frame_count, FACE_BLENDSHAPE_COUNT), dtype=np.float64)

    for frame, at in enumerate(absolute_times):
        evaluated_scene = ufbx.evaluate_scene(scene, animation, float(at))
        evaluated = _snapshot_scene(evaluated_scene)
        evaluated_nodes = evaluated.nodes
        pose = pose_frames[frame]
        for index, bone in POSE_BONES.items():
            pose[index] = _vec(evaluated_nodes[nodes[bone]].node_to_world.c3)

        head_node = evaluated_nodes[nodes["Head"]]
        head_matrix = head_node.node_to_world
        head = _vec(head_matrix.c3)
        anatomical_head = np.column_stack([
            _matrix_axis(head_matrix, i) for i in range(3)
        ]) @ head_offsets_basis
        right, up, forward = anatomical_head.T
        right /= max(np.linalg.norm(right), 1e-12)
        up /= max(np.linalg.norm(up), 1e-12)
        forward /= max(np.linalg.norm(forward), 1e-12)
        for index, (along_forward, along_right, along_up) in HEAD_OFFSETS.items():
            pose[index] = head + forward * along_forward + right * along_right + up * along_up
        for index, (_segment, along) in FOOT_OFFSETS.items():
            foot_node = evaluated_nodes[nodes["LeftFoot" if index % 2 else "RightFoot"]]
            foot = foot_node.node_to_world
            direction = _matrix_axis(foot, 2)
            direction /= max(np.linalg.norm(direction), 1e-12)
            pose[index] = _vec(foot.c3) + direction * along

        left_frames[frame] = _sample_hand(evaluated, nodes, tips, "Left")
        right_frames[frame] = _sample_hand(evaluated, nodes, tips, "Right")

        for column, canonical in enumerate(ARKIT_BLENDSHAPES):
            values = np.array([
                ufbx.evaluate_blend_weight(animation, channels[channel], float(at))
                for channel in face_channels[canonical]
            ])
            if not np.all(np.isfinite(values)):
                raise FbxFormatError(f"{path.name}: {canonical} contains a non-finite weight.")
            if values.max() - values.min() > 0.005:
                raise FbxFormatError(
                    f"{path.name}: duplicate {canonical} channels disagree at frame {frame + 1}."
                )
            face_frames[frame, column] = np.clip(values.mean(), 0.0, 1.0)

    if not all(np.all(np.isfinite(track)) for track in (pose_frames, left_frames, right_frames)):
        raise FbxFormatError(f"{path.name}: body or hand motion contains NaN or infinity.")

    origin = ((pose_frames[:, 23] + pose_frames[:, 24]) / 2.0)[:, None, :]
    return LandmarkTake(
        name=name or path.stem,
        fps=fps,
        pose=(pose_frames - origin) @ alignment.T,
        left_hand=(left_frames - origin) @ alignment.T,
        right_hand=(right_frames - origin) @ alignment.T,
        face_blendshapes=face_frames,
        timestamps=times,
    )
