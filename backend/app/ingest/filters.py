"""Smoothing for reconstructed motion.

Rotations are filtered in the tangent space at each frame's neighbourhood mean rather than
component-wise on raw quaternions, which is not a rotation-preserving operation.

Finger joints get a shorter window than the body: glove data is noisier, but handshape changes fast
and over-smoothing it destroys exactly the detail that makes a sign readable.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter
from scipy.spatial.transform import Rotation

BODY_WINDOW = 9
FINGER_WINDOW = 5
POLYORDER = 2


def smooth_rotations(rot: Rotation, window: int = BODY_WINDOW, polyorder: int = POLYORDER) -> Rotation:
    n = len(rot)
    if window < 3 or n < window:
        return rot
    if window % 2 == 0:
        window += 1

    # Work in the log map around the sequence's mean rotation, filter there, then map back.
    base = rot.mean()
    rotvec = (base.inv() * rot).as_rotvec()
    smoothed = savgol_filter(rotvec, window, polyorder, axis=0, mode="nearest")
    return base * Rotation.from_rotvec(smoothed)


def smooth_positions(values: np.ndarray, window: int = BODY_WINDOW, polyorder: int = POLYORDER) -> np.ndarray:
    n = len(values)
    if window < 3 or n < window:
        return values
    if window % 2 == 0:
        window += 1
    return savgol_filter(values, window, polyorder, axis=0, mode="nearest")


def window_for(unity_bone: str) -> int:
    finger_parts = ("Thumb", "Index", "Middle", "Ring", "Little")
    return FINGER_WINDOW if any(p in unity_bone for p in finger_parts) else BODY_WINDOW
