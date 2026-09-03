"""Resample a take onto a uniform frame grid.

The source runs at 30 fps with 33/34 ms jitter in its millisecond timestamps. Playback targets a
uniform 60 fps: uniform because the clip format stores no per-frame times, and 60 because upsampling
gives the browser a smoother result than repeating 30 fps frames.
"""

from __future__ import annotations

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

TARGET_FPS = 60.0


def uniform_times(times: np.ndarray, fps: float = TARGET_FPS) -> np.ndarray:
    duration = float(times[-1] - times[0])
    count = max(int(round(duration * fps)) + 1, 1)
    return times[0] + np.arange(count) / fps


def resample_positions(times: np.ndarray, values: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Linear interpolation over the leading axis of an (F, ...) array."""
    flat = values.reshape(len(times), -1)
    out = np.empty((len(target), flat.shape[1]), dtype=np.float64)
    for i in range(flat.shape[1]):
        out[:, i] = np.interp(target, times, flat[:, i])
    return out.reshape((len(target),) + values.shape[1:])


def resample_rotations(times: np.ndarray, rot: Rotation, target: np.ndarray) -> Rotation:
    """Spherical linear interpolation - component-wise lerp on quaternions is not a rotation."""
    clamped = np.clip(target, times[0], times[-1])
    return Slerp(times, rot)(clamped)
