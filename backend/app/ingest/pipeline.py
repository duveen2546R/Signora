"""End-to-end ingest: one Rokoko CSV in, one playable `.signclip` out.

Stage order matters. Retargeting happens on the raw 30 fps samples so that the geometry it reads is
exactly what the suit measured; resampling and smoothing then operate on local rotations, which is
the quantity that actually ships, rather than on intermediate values whose errors would be reshaped
by later stages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from . import clipfmt, filters, resample
from .reconstruct import reconstruct
from .retarget import hip_track, to_local_rotations
from .rigprofile import RigProfile
from .rokoko import Take, measure_skeleton, parse_csv


@dataclass
class QcMetrics:
    """Quality signals stored per clip, so bad takes are findable without watching them all."""

    source_fps: float
    source_frames: int
    output_frames: int
    duration: float
    max_bone_length_spread_mm: float
    peak_angular_velocity_deg_s: float
    fastest_bone: str
    dominant_hand: str
    hand_travel_cm: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _bone_length_spread_mm(take: Take) -> float:
    from . import skeleton as sk
    worst = 0.0
    for bone in sk.BONES:
        if bone.tail is None:
            continue
        d = np.linalg.norm(take.pos(bone.tail) - take.pos(bone.head), axis=1)
        worst = max(worst, float(d.max() - d.min()) * 1000.0)
    return worst


def _quality(take: Take, locals_: dict[str, Rotation], fps: float) -> QcMetrics:
    peak, fastest = 0.0, ""
    for name, rot in locals_.items():
        if len(rot) < 2:
            continue
        step = np.degrees((rot[:-1].inv() * rot[1:]).magnitude()) * fps
        if step.size and step.max() > peak:
            peak, fastest = float(step.max()), name

    travel = {}
    for side in ("Left", "Right"):
        p = take.pos(f"{side}Hand")
        travel[side] = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum() * 100.0)

    warnings: list[str] = []
    spread = _bone_length_spread_mm(take)
    if spread > 5.0:
        warnings.append(
            f"bone lengths vary by up to {spread:.1f}mm - the skeleton should be rigid; "
            "check the suit calibration for this take"
        )
    if max(travel.values()) < 5.0:
        warnings.append("almost no hand movement in this take - is it the right recording?")
    if take.duration < 0.5:
        warnings.append(f"take is only {take.duration:.2f}s long")

    return QcMetrics(
        source_fps=take.source_fps,
        source_frames=take.frame_count,
        output_frames=len(next(iter(locals_.values()))),
        duration=take.duration,
        max_bone_length_spread_mm=spread,
        peak_angular_velocity_deg_s=peak,
        fastest_bone=fastest,
        dominant_hand="Right" if travel["Right"] >= travel["Left"] else "Left",
        hand_travel_cm=travel,
        warnings=warnings,
    )


def ingest_take(
    take: Take,
    rig: RigProfile,
    target_fps: float = resample.TARGET_FPS,
    smooth: bool = True,
    twist_offsets: dict[str, float] | None = None,
) -> tuple[clipfmt.Clip, QcMetrics]:
    motion = reconstruct(take)
    locals_ = to_local_rotations(motion, rig, twist_offsets)

    target_times = resample.uniform_times(take.times, target_fps)
    out: dict[str, Rotation] = {}
    for name, rot in locals_.items():
        r = resample.resample_rotations(take.times, rot, target_times)
        if smooth:
            r = filters.smooth_rotations(r, window=filters.window_for(name))
        out[name] = r

    hips = hip_track(take.pos("Pelvis"), rig, measure_skeleton(take)["_hip_height"])
    hips = resample.resample_positions(take.times, hips, target_times)
    if smooth:
        hips = filters.smooth_positions(hips)

    clip = clipfmt.from_rotations(out, fps=target_fps, rig_digest=rig.digest, root_positions=hips)
    return clip, _quality(take, out, target_fps)


def ingest_file(
    csv_path: str | Path, rig: RigProfile, **kwargs
) -> tuple[clipfmt.Clip, QcMetrics]:
    return ingest_take(parse_csv(csv_path), rig, **kwargs)
