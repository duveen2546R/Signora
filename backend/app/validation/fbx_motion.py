"""Read canonical upper-body joints from the three observed FBX skeleton layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .mixed_effects import ValidationError

JOINTS = ("left_shoulder", "right_shoulder", "left_hip", "right_hip", "left_wrist", "right_wrist")
BASE = {
    "left_shoulder": "LeftArm", "right_shoulder": "RightArm",
    "left_wrist": "LeftHand", "right_wrist": "RightHand",
}
PROFILES = {
    "rokoko_mixamo_60": (60.0, {**BASE, "left_hip": "LeftUpLeg", "right_hip": "RightUpLeg"}),
    "newton_30": (30.0, {**BASE, "left_hip": "LeftThigh", "right_hip": "RightThigh"}),
    "blender_25": (25.0, {**BASE, "left_hip": "LeftUpLeg", "right_hip": "RightUpLeg"}),
}


@dataclass(frozen=True)
class Motion:
    path: Path
    profile: str
    fps: float
    times: np.ndarray
    joints: np.ndarray  # (frames, six joints, xyz), left-handed Y-up, metres


def _clean(name: str) -> str:
    return name.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def load_motion(path: str | Path) -> Motion:
    try:
        import ufbx
    except ImportError as exc:
        raise ValidationError("Install backend requirements for FBX validation.") from exc
    path = Path(path)
    try:
        scene = ufbx.load_file(
            str(path), target_axes=ufbx.axes_left_handed_y_up, target_unit_meters=1.0,
            space_conversion=ufbx.SpaceConversion.TRANSFORM_ROOT,
            ignore_embedded=True, load_external_files=False,
        )
    except Exception as exc:
        raise ValidationError(f"Cannot parse {path.name}: {exc}") from exc
    fps = float(scene.settings.frames_per_second)
    native = scene.nodes
    nodes = [native[index] for index in range(len(native))]
    indices: dict[str, list[int]] = {}
    for index, node in enumerate(nodes):
        indices.setdefault(_clean(node.name), []).append(index)
    matches = [
        (name, mapping) for name, (expected_fps, mapping) in PROFILES.items()
        if abs(fps - expected_fps) < 0.01 and all(len(indices.get(bone, [])) == 1 for bone in mapping.values())
    ]
    if len(matches) != 1:
        raise ValidationError(
            f"{path.name}: unsupported or ambiguous skeleton at {fps:g} FPS. "
            "Use an audited profile for this exact export."
        )
    profile, mapping = matches[0]
    stacks = scene.anim_stacks
    if len(stacks) != 1:
        raise ValidationError(f"{path.name}: exactly one animation stack is required.")
    stack = stacks[0]
    duration = float(stack.time_end - stack.time_begin)
    if not np.isfinite(duration) or duration <= 0:
        raise ValidationError(f"{path.name}: empty or invalid animation duration.")
    times = np.arange(int(round(duration * fps)) + 1, dtype=float) / fps
    # Do not sample beyond the declared FBX take endpoint due to rounding.
    times = times[times <= duration + 1e-8]
    result = np.empty((len(times), len(JOINTS), 3), dtype=float)
    indexes = [indices[mapping[key]][0] for key in JOINTS]
    for frame, time in enumerate(times):
        evaluated = ufbx.evaluate_scene(scene, stack.anim, float(stack.time_begin + time))
        evaluated_list = evaluated.nodes
        for joint, index in enumerate(indexes):
            point = evaluated_list[index].node_to_world.c3
            result[frame, joint] = (point.x, point.y, point.z)
    if not np.isfinite(result).all():
        raise ValidationError(f"{path.name}: joint positions contain invalid values.")
    shoulder = np.linalg.norm(result[:, 0] - result[:, 1], axis=1)
    if np.median(shoulder) < 0.05 or np.median(shoulder) > 1.5:
        raise ValidationError(f"{path.name}: shoulder width is implausible after metre conversion.")
    return Motion(path, profile, fps, times, result)
