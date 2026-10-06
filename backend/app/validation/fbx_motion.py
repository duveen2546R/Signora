"""Read canonical upper-body joints from audited FBX skeleton layouts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import sys
import tempfile

import numpy as np

from .mixed_effects import ValidationError

JOINTS = (
    "left_shoulder",
    "right_shoulder",
    "left_hip",
    "right_hip",
    "left_wrist",
    "right_wrist",
)
CASE_JOINTS = (*JOINTS, "left_elbow", "right_elbow")
HAND_BONES = tuple(
    f"{side}Hand{finger}{joint}"
    for side in ("Left", "Right")
    for finger in ("Thumb", "Index", "Middle", "Ring", "Pinky")
    for joint in range(1, 5)
)
EXTRA_BONES = ("Neck", "Head", "HeadTop_End", *HAND_BONES)
BASE = {
    "left_shoulder": "LeftArm",
    "right_shoulder": "RightArm",
    "left_wrist": "LeftHand",
    "right_wrist": "RightHand",
}
PROFILES = {
    # Audited action.fbx: 30 FPS, mixamorig namespace, LeftUpLeg/RightUpLeg hips.
    "mixamo_30": (30.0, {**BASE, "left_hip": "LeftUpLeg", "right_hip": "RightUpLeg"}),
    "rokoko_mixamo_60": (
        60.0,
        {**BASE, "left_hip": "LeftUpLeg", "right_hip": "RightUpLeg"},
    ),
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
    extras: np.ndarray | None = None  # optional audited nodes; missing nodes are NaN


def _clean(name: str) -> str:
    return name.rsplit("|", 1)[-1].rsplit(":", 1)[-1]


def load_motion(
    path: str | Path, *, include_elbows: bool = False, include_extras: bool = False
) -> Motion:
    """Copy native data in an isolated process (ufbx 0.0.5 has owner-lifetime faults).

    The worker retains native owners until its arrays are flushed, then exits without
    running faulty wrapper destructors. Native failures become ordinary validation errors.
    """
    path = Path(path).resolve()
    with tempfile.TemporaryDirectory(prefix="signsure-fbx-") as directory:
        output = Path(directory) / "motion.npz"
        environment = os.environ.copy()
        root = str(Path(__file__).resolve().parents[2])
        environment["PYTHONPATH"] = (
            root + os.pathsep + environment.get("PYTHONPATH", "")
        )
        try:
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app.validation.fbx_worker",
                    str(path),
                    str(output),
                    "extras"
                    if include_extras
                    else "elbows"
                    if include_elbows
                    else "legacy",
                ],
                capture_output=True,
                text=True,
                env=environment,
                timeout=180,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValidationError(
                f"{path.name}: FBX sampling exceeded 180 seconds."
            ) from exc
        if process.returncode or not output.is_file():
            raise ValidationError(
                f"{path.name}: FBX worker failed ({process.returncode}): {process.stderr.strip()[-2000:]}"
            )
        with np.load(output, allow_pickle=False) as data:
            return Motion(
                path,
                str(data["profile"]),
                float(data["fps"]),
                data["times"].copy(),
                data["joints"].copy(),
                data["extras"].copy() if "extras" in data else None,
            )


_NATIVE_OWNERS = []  # Worker only: retain wrapper parents through os._exit().


def _load_native(
    path: str | Path, *, include_elbows: bool = False, include_extras: bool = False
) -> Motion:
    try:
        import ufbx
    except ImportError as exc:
        raise ValidationError(
            "Install backend requirements for FBX validation."
        ) from exc
    path = Path(path)
    try:
        scene = ufbx.load_file(
            str(path),
            target_axes=ufbx.axes_left_handed_y_up,
            target_unit_meters=1.0,
            space_conversion=ufbx.SpaceConversion.TRANSFORM_ROOT,
            ignore_embedded=True,
            load_external_files=False,
        )
    except Exception as exc:
        raise ValidationError(f"Cannot parse {path.name}: {exc}") from exc
    include_elbows = include_elbows or include_extras
    fps = float(scene.settings.frames_per_second)
    native = scene.nodes
    nodes = [native[index] for index in range(len(native))]
    _NATIVE_OWNERS.extend((scene, native, nodes))
    indices: dict[str, list[int]] = {}
    for index, node in enumerate(nodes):
        indices.setdefault(_clean(node.name), []).append(index)
    matches = [
        (name, mapping)
        for name, (expected_fps, mapping) in PROFILES.items()
        if abs(fps - expected_fps) < 0.01
        and all(len(indices.get(bone, [])) == 1 for bone in mapping.values())
    ]
    if len(matches) != 1:
        raise ValidationError(
            f"{path.name}: unsupported or ambiguous skeleton at {fps:g} FPS. "
            "Use an audited profile for this exact export."
        )
    profile, mapping = matches[0]
    if include_elbows:
        mapping = {
            **mapping,
            "left_elbow": "LeftForeArm",
            "right_elbow": "RightForeArm",
        }
        if any(len(indices.get(bone, [])) != 1 for bone in mapping.values()):
            raise ValidationError(f"{path.name}: missing or ambiguous elbow bones.")
    stacks = scene.anim_stacks
    if len(stacks) != 1:
        raise ValidationError(f"{path.name}: exactly one animation stack is required.")
    stack = stacks[0]
    animation = stack.anim
    _NATIVE_OWNERS.extend((stacks, stack, animation))
    duration = float(stack.time_end - stack.time_begin)
    if not np.isfinite(duration) or duration <= 0:
        raise ValidationError(f"{path.name}: empty or invalid animation duration.")
    times = np.arange(int(round(duration * fps)) + 1, dtype=float) / fps
    # Do not sample beyond the declared FBX take endpoint due to rounding.
    times = times[times <= duration + 1e-6]
    times = np.minimum(times, duration)
    joints = CASE_JOINTS if include_elbows else JOINTS
    result = np.empty((len(times), len(joints), 3), dtype=float)
    indexes = [indices[mapping[key]][0] for key in joints]
    extra_indexes = (
        [
            indices[name][0] if len(indices.get(name, [])) == 1 else None
            for name in EXTRA_BONES
        ]
        if include_extras
        else []
    )
    extras = np.full((len(times), len(extra_indexes), 3), np.nan)
    for frame, time in enumerate(times):
        evaluated = ufbx.evaluate_scene(
            scene, animation, float(stack.time_begin + time)
        )
        evaluated_list = evaluated.nodes
        sampled_nodes = [evaluated_list[index] for index in indexes]
        matrices = [node.node_to_world for node in sampled_nodes]
        points = [matrix.c3 for matrix in matrices]
        _NATIVE_OWNERS.extend(
            (evaluated, evaluated_list, sampled_nodes, matrices, points)
        )
        for joint, index in enumerate(indexes):
            point = points[joint]
            result[frame, joint] = (point.x, point.y, point.z)
        for joint, index in enumerate(extra_indexes):
            if index is not None:
                node = evaluated_list[index]
                matrix = node.node_to_world
                point = matrix.c3
                _NATIVE_OWNERS.extend((node, matrix, point))
                extras[frame, joint] = (point.x, point.y, point.z)
    if not np.isfinite(result).all():
        raise ValidationError(f"{path.name}: joint positions contain invalid values.")
    
    if profile == "rokoko_mixamo_60":
        # Rotate 90 degrees around Y axis to face front (Z)
        theta = np.pi / 2
        c, s = np.cos(theta), np.sin(theta)
        ry = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        result = result @ ry.T
        if include_extras:
            valid_mask = np.isfinite(extras).all(axis=2)
            extras[valid_mask] = extras[valid_mask] @ ry.T
    shoulder = np.linalg.norm(result[:, 0] - result[:, 1], axis=1)
    if np.median(shoulder) < 0.05 or np.median(shoulder) > 1.5:
        raise ValidationError(
            f"{path.name}: shoulder width is implausible after metre conversion."
        )
    return Motion(path, profile, fps, times, result, extras if include_extras else None)
