"""Synthetic two-view recordings of a known FBX take, for checking the single-take protocol.

The "video truth" is the FBX skeleton plus a fixed joint-centre mismatch and an optional injected
elbow-flexion error. Two virtual phones film it at 0 deg and an oblique angle with their own clock
offsets, a misreported focal length, temporally correlated keypoint noise and dropouts. The same
phones can also film a noise recording (still hold, then slow movement) and pose-model replicates.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .angles3d import ANGLES, joint_angles
from .fbx_motion import CASE_JOINTS, Motion
from .conditional_equivalence import ar1_noise
from .multiview import Camera, View, intrinsics, lowpass


@dataclass(frozen=True)
class Scenario:
    oblique_deg: float = 35.0
    distance_m: float = 3.0
    focal_px: float = 1500.0
    focal_error: float = 0.05  # metadata focal is off by this fraction
    size: tuple[int, int] = (1920, 1080)
    fps: float = 30.0
    second_view_delay_s: float = 0.137
    video_lead_s: float = 0.41  # phones start recording before the suit take
    noise_px: float = 3.0
    noise_ar: float = 0.7  # detector jitter is correlated frame to frame
    motion_noise_factor: float = 1.0  # detector noise while moving relative to holding still
    dropout: float = 0.02
    joint_offset_m: float = 0.01
    hold_s: float = 0.6
    replicate_noise_fraction: float = 0.5  # TTA jitter relative to detector noise


@dataclass(frozen=True)
class SimulatedTake:
    first: View
    second: View
    K1: np.ndarray
    K2: np.ndarray
    motion: Motion  # padded FBX
    truth: np.ndarray  # what the phones saw, on the FBX clock
    replicates: tuple[tuple[View, View], ...] = ()

    def true_difference(self, window: slice) -> dict[str, np.ndarray]:
        """Video-truth minus FBX angles, filtered exactly as the pipeline filters both."""
        video = joint_angles(lowpass(self.truth, self.motion.fps))
        fbx = joint_angles(lowpass(self.motion.joints, self.motion.fps))
        return {name: video[name][window] - fbx[name][window] for name in video}


def padded(motion: Motion, hold_s: float) -> Motion:
    """Rest-pose holds around the take, as a real recording would have."""
    count = int(round(hold_s * motion.fps))
    joints = np.concatenate([
        np.repeat(motion.joints[:1], count, 0), motion.joints, np.repeat(motion.joints[-1:], count, 0)
    ])
    return replace(motion, joints=joints, times=np.arange(len(joints)) / motion.fps)


def look_at(eye: np.ndarray, target: np.ndarray, K: np.ndarray) -> Camera:
    forward = (target - eye) / np.linalg.norm(target - eye)
    right = np.cross(forward, [0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    down = np.cross(forward, right)
    R = np.stack([right, down, forward])
    return Camera(K, R, -R @ eye)


def inject_flexion(xyz: np.ndarray, side: str, delta_deg: np.ndarray) -> np.ndarray:
    """Rotate the forearm (wrist and index) about the elbow so flexion grows by `delta_deg`."""
    out = xyz.copy()
    shoulder, elbow, wrist = (CASE_JOINTS.index(name) for name in ANGLES[f"{side}_elbow_flexion"])
    index = CASE_JOINTS.index(f"{side}_index")
    previous = np.array([1.0, 0.0, 0.0])
    for frame, angle in enumerate(np.broadcast_to(np.radians(delta_deg), len(xyz))):
        upper = xyz[frame, elbow] - xyz[frame, shoulder]
        lower = xyz[frame, wrist] - xyz[frame, elbow]
        axis = np.cross(upper, lower)
        if np.linalg.norm(axis) < 1e-6 * np.linalg.norm(upper) * np.linalg.norm(lower):
            axis = previous
        axis = axis / np.linalg.norm(axis)
        previous = axis
        c, s = np.cos(angle), np.sin(angle)
        for joint in (wrist, index):
            v = xyz[frame, joint] - xyz[frame, elbow]
            rotated = v * c + np.cross(axis, v) * s + axis * (axis @ v) * (1 - c)
            out[frame, joint] = xyz[frame, elbow] + rotated
    return out


def phones(motion: Motion, scenario: Scenario) -> tuple[list[Camera], np.ndarray]:
    """True cameras (fixed for every recording in a session) and the reported intrinsics."""
    centre = np.nanmean(motion.joints[:, :4], axis=(0, 1))
    width, height = scenario.size
    K_true = intrinsics(width, height, scenario.focal_px)
    cameras = []
    for angle in (0.0, scenario.oblique_deg):
        a = np.radians(angle)
        # FBX is yaw-aligned to face +Z, so the frontal phone sits on +Z.
        eye = centre + scenario.distance_m * np.array([np.sin(a), 0.0, np.cos(a)])
        cameras.append(look_at(eye, centre, K_true))
    return cameras, intrinsics(width, height, scenario.focal_px * (1 + scenario.focal_error))


def _film(truth, truth_times, cameras, scenario, rng, *, lead_s, noise_scale, replicates=0):
    views, extra = [], [[] for _ in range(replicates)]
    for camera, delay in zip(cameras, (0.0, scenario.second_view_delay_s)):
        duration = truth_times[-1] + lead_s - delay + 0.5
        times = np.arange(0.0, duration, 1.0 / scenario.fps)
        source = times - lead_s + delay  # truth clock of each video frame
        xyz = np.stack([
            np.stack([np.interp(source, truth_times, truth[:, j, axis]) for axis in range(3)], -1)
            for j in range(truth.shape[1])
        ], axis=1)
        clean = camera.project(xyz)
        shape = clean.shape[:2] + (2,)
        level = scenario.noise_px * noise_scale(source)
        observed = clean + ar1_noise(shape, 1.0, scenario.noise_ar, rng) * level
        confidence = np.full(shape[:2], 0.9)
        dropped = rng.random(confidence.shape) < scenario.dropout
        observed[dropped] = np.nan
        confidence[dropped] = 0.0
        views.append(View(times, observed, confidence, scenario.size))
        for store in extra:
            jitter = ar1_noise(
                shape, scenario.noise_px * scenario.replicate_noise_fraction, scenario.noise_ar, rng
            )
            store.append(View(times, observed + jitter, confidence, scenario.size))
    return views, tuple(tuple(pair) for pair in extra)


def simulate(
    motion: Motion,
    scenario: Scenario = Scenario(),
    *,
    injected: dict[str, np.ndarray | float] | None = None,
    replicates: int = 0,
    seed: int = 0,
) -> SimulatedTake:
    """The sign take. `injected` maps "left"/"right" to an elbow-flexion error in degrees,
    constant or per frame of the padded take."""
    rng = np.random.default_rng(seed)
    motion = padded(motion, scenario.hold_s)
    truth = motion.joints + rng.normal(0, scenario.joint_offset_m, motion.joints.shape[1:])
    for side, delta in (injected or {}).items():
        truth = inject_flexion(truth, side, np.broadcast_to(delta, len(truth)).astype(float))
    cameras, K = phones(motion, scenario)
    moving = lambda source: np.full(len(source), scenario.motion_noise_factor)[:, None, None]
    (first, second), extra = _film(
        truth, motion.times, cameras, scenario, rng,
        lead_s=scenario.video_lead_s, noise_scale=moving, replicates=replicates,
    )
    return SimulatedTake(first, second, K, K.copy(), motion, truth, extra)


def simulate_noise_recording(
    motion: Motion,
    scenario: Scenario = Scenario(),
    *,
    still_s: float = 10.0,
    slow_factor: float = 2.5,
    seed: int = 0,
) -> tuple[View, View]:
    """Same phones, no suit needed: hold the rest pose for `still_s`, then move slowly.

    The hold includes slow postural sway; the moving part is the take replayed `slow_factor`
    times slower, which gives the calibration varied poses.
    """
    rng = np.random.default_rng(seed + 7919)
    motion = padded(motion, scenario.hold_s)
    hold = int(still_s * scenario.fps)
    t = np.arange(hold) / scenario.fps
    sway = 0.003 * np.sin(2 * np.pi * 0.15 * t)[:, None, None] * np.array([1.0, 0.3, 0.5])
    still = motion.joints[:1] + sway
    slow_times = motion.times * slow_factor
    slow = np.stack([
        np.stack([np.interp(np.arange(0, slow_times[-1], 1 / scenario.fps), slow_times, motion.joints[:, j, a])
                  for a in range(3)], -1)
        for j in range(motion.joints.shape[1])
    ], axis=1)
    truth = np.concatenate([still, slow])
    truth_times = np.arange(len(truth)) / scenario.fps
    cameras, _ = phones(motion, scenario)
    noise = lambda source: np.where(source < still_s, 1.0, scenario.motion_noise_factor)[:, None, None]
    (first, second), _ = _film(truth, truth_times, cameras, scenario, rng, lead_s=0.0, noise_scale=noise)
    return first, second
