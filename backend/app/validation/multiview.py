"""Two uncalibrated phone views of one take -> filtered 3D joints on the FBX clock.

Cameras are self-calibrated from body keypoints seen in both views (essential matrix, then a
reprojection refinement). The FBX is never used to place the cameras: fitting the cameras to the
skeleton under test and then comparing against it would bias the result toward agreement. Joint
angles are scale and frame invariant, so the unknown baseline length needs no recovery.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field, replace

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import butter, filtfilt
from scipy.spatial.transform import Rotation

from .angles3d import joint_angles
from .fbx_motion import CASE_JOINTS, Motion
from .mixed_effects import ValidationError

MIN_CONFIDENCE = 0.6
MAX_REPROJECTION_PX = 15.0
MAX_GAP_S = 0.15
CUTOFF_HZ = 6.0
ONSET_FRACTION = 0.05
MIN_MOVEMENT_S = 0.2  # sign movements last far longer than a filtered twitch
REST_GAP_S = 0.15  # keep the hold clear of movement onset
REST_MAX_S = 1.5
REST_MIN_S = 0.4
MAX_JOINT_SPEED = 8.0  # m/s; faster than any human limb, so only an export glitch
WRISTS = ("left_wrist", "right_wrist")
BONES = (
    ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
    ("left_shoulder", "right_shoulder"), ("left_hip", "right_hip"),
    ("left_shoulder", "left_hip"), ("right_shoulder", "right_hip"),
    ("left_wrist", "left_index"), ("right_wrist", "right_index"),
)
BONE_WEIGHT_PX = 100.0  # a 1% bone-length change costs as much as 1 px of reprojection
PRIOR_PX = 2.0  # one prior standard deviation costs as much as typical detector noise
FOCAL_PRIOR_SD = 0.15  # log-scale doubt about a phone's video focal length without metadata


@dataclass(frozen=True)
class View:
    """One video's keypoints in pixels; missing detections are NaN with zero confidence."""

    times: np.ndarray
    uv: np.ndarray  # frames x joints x 2 pixels
    confidence: np.ndarray  # frames x joints
    size: tuple[int, int]  # width, height

    @classmethod
    def from_pose(cls, pose, width: int, height: int) -> "View":
        """Adapt a normalised `video_pose.VideoPose`."""
        return cls(pose.times, pose.xy * np.array([width, height]), pose.confidence, (width, height))


@dataclass(frozen=True)
class Camera:
    K: np.ndarray
    R: np.ndarray
    t: np.ndarray

    @property
    def P(self) -> np.ndarray:
        return self.K @ np.hstack([self.R, self.t[:, None]])

    def project(self, xyz: np.ndarray) -> np.ndarray:
        camera = xyz @ self.R.T + self.t
        image = camera @ self.K.T
        with np.errstate(invalid="ignore", divide="ignore"):
            return image[..., :2] / image[..., 2:3]


@dataclass
class TwoViewTake:
    times: np.ndarray
    xyz: np.ndarray  # frames x joints x 3, arbitrary scale and frame
    cameras: tuple[Camera, Camera]
    diagnostics: dict = field(default_factory=dict)


def intrinsics(width: int, height: int, focal_px: float) -> np.ndarray:
    return np.array([[focal_px, 0, width / 2], [0, focal_px, height / 2], [0, 0, 1.0]])


def focal_from_35mm(focal_35mm: float, width: int, height: int) -> float:
    """Pixels from the 35 mm-equivalent focal length phones store in video metadata."""
    return focal_35mm * np.hypot(width, height) / np.hypot(36.0, 24.0)


def _interpolate(times: np.ndarray, values: np.ndarray, at: np.ndarray) -> np.ndarray:
    flat = values.reshape(len(times), -1)
    out = np.full((len(at), flat.shape[1]), np.nan)
    for column in range(flat.shape[1]):
        finite = np.isfinite(flat[:, column])
        if finite.sum() >= 2:
            inside = (at >= times[finite][0]) & (at <= times[finite][-1])
            out[inside, column] = np.interp(at[inside], times[finite], flat[finite, column])
    return out.reshape((len(at), *values.shape[1:]))


def wrist_speed(times: np.ndarray, positions: np.ndarray, joints=CASE_JOINTS) -> np.ndarray:
    """Summed wrist speed, the sync signal shared by every view and the FBX."""
    index = [joints.index(name) for name in WRISTS]
    velocity = np.gradient(positions[:, index], times, axis=0)
    return np.nansum(np.linalg.norm(velocity, axis=-1), axis=1)


def estimate_lag(reference: np.ndarray, other: np.ndarray, rate: float, max_lag_s: float = 2.0) -> float:
    """Seconds to add to `other`'s timestamps so it lines up with `reference` (sub-frame)."""
    def standard(x):
        x = np.where(np.isfinite(x), x, np.nanmean(x))
        return (x - x.mean()) / (x.std() or 1.0)

    a, b = standard(reference), standard(other)
    max_lag = int(min(max_lag_s * rate, len(a) - 2, len(b) - 2))
    lags = np.arange(-max_lag, max_lag + 1)
    scores = np.empty(len(lags))
    for position, lag in enumerate(lags):
        # a[i] pairs with b[i - lag]
        lo, hi = max(0, lag), min(len(a), len(b) + lag)
        scores[position] = np.mean(a[lo:hi] * b[lo - lag : hi - lag]) if hi - lo > 4 else -np.inf
    best = int(np.argmax(scores))
    shift = float(lags[best])
    if 0 < best < len(lags) - 1:
        left, centre, right = scores[best - 1 : best + 2]
        curvature = left - 2 * centre + right
        if curvature < 0:
            shift += 0.5 * (left - right) / curvature
    return shift / rate


def triangulate(cameras: tuple[Camera, ...], uv: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Confidence-weighted linear triangulation of (views, points, 2) -> (points, 3)."""
    rows = []
    for camera, points, weight in zip(cameras, uv, weights):
        P = camera.P
        rows.append(weight[:, None] * (points[:, :1] * P[2] - P[0]))
        rows.append(weight[:, None] * (points[:, 1:2] * P[2] - P[1]))
    system = np.stack(rows, axis=1)
    # Inhomogeneous form (X = [x, y, z, 1]): a batched 3x3 normal-equation solve, ~50x faster
    # than per-point SVD and identical for points at finite depth.
    A, b = system[:, :, :3], -system[:, :, 3]
    normal = np.einsum("nki,nkj->nij", A, A)
    rhs = np.einsum("nki,nk->ni", A, b)
    good = np.abs(np.linalg.det(normal)) > 1e-12
    out = np.full((len(system), 3), np.nan)
    out[good] = np.linalg.solve(normal[good], rhs[good][..., None])[..., 0]
    return out


def _rays(uv: np.ndarray, K: np.ndarray) -> np.ndarray:
    return np.column_stack([uv, np.ones(len(uv))]) @ np.linalg.inv(K).T


def _essential(x1: np.ndarray, x2: np.ndarray) -> np.ndarray:
    system = np.einsum("ni,nj->nij", x2, x1).reshape(len(x1), 9)
    _, _, vt = np.linalg.svd(system)
    u, _, v = np.linalg.svd(vt[-1].reshape(3, 3))
    return u @ np.diag([1.0, 1.0, 0.0]) @ v


def _pose_from_essential(E, uv1, uv2, K1, K2) -> tuple[np.ndarray, np.ndarray]:
    u, _, vt = np.linalg.svd(E)
    if np.linalg.det(u) < 0:
        u = -u
    if np.linalg.det(vt) < 0:
        vt = -vt
    w = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])
    first = Camera(K1, np.eye(3), np.zeros(3))
    best, chosen = -1, None
    for R in (u @ w @ vt, u @ w.T @ vt):
        for t in (u[:, 2], -u[:, 2]):
            second = Camera(K2, R, t)
            xyz = triangulate((first, second), np.stack([uv1, uv2]), np.ones((2, len(uv1))))
            depth1 = xyz[:, 2]
            depth2 = (xyz @ R.T + t)[:, 2]
            in_front = int(np.sum((depth1 > 0) & (depth2 > 0)))
            if in_front > best:
                best, chosen = in_front, (R, t)
    return chosen


def _oblique_start(yaw_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Second phone on a circle around the signer, yawed by `yaw_deg`, unit baseline."""
    a = np.radians(yaw_deg)
    depth = 1.0 / (2.0 * abs(np.sin(a / 2)))
    eye = depth * np.array([np.sin(a), 0.0, 1.0 - np.cos(a)])
    forward = np.array([0.0, 0.0, depth]) - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, [0.0, -1.0, 0.0])  # camera 1 frame is y-down
    right /= np.linalg.norm(right)
    R = np.stack([right, np.cross(forward, right), forward])
    return R, -R @ eye


@dataclass(frozen=True)
class Calibration:
    cameras: tuple[Camera, Camera]
    parameters: np.ndarray  # rotvec(3), baseline direction (2), [log focal scale x2]
    covariance: np.ndarray  # Gauss-Newton, assuming independent residuals
    K: tuple[np.ndarray, np.ndarray]  # starting intrinsics the parameters are relative to
    diagnostics: dict


def cameras_from(parameters: np.ndarray, K1: np.ndarray, K2: np.ndarray) -> tuple[Camera, Camera]:
    rotation = Rotation.from_rotvec(parameters[:3]).as_matrix()
    theta, phi = parameters[3:5]
    direction = np.array([np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)])
    k1, k2 = K1.copy(), K2.copy()
    if len(parameters) > 5:
        k1[0, 0] = k1[1, 1] = K1[0, 0] * np.exp(parameters[5])
        k2[0, 0] = k2[1, 1] = K2[0, 0] * np.exp(parameters[6])
    return Camera(k1, np.eye(3), np.zeros(3)), Camera(k2, rotation, direction)


def calibrate_pairs(
    uv: np.ndarray,
    confidence: np.ndarray,
    K1: np.ndarray,
    K2: np.ndarray,
    *,
    joints: tuple[str, ...] = CASE_JOINTS,
    min_confidence: float = MIN_CONFIDENCE,
    refine_focal: bool = True,
    yaw_prior_deg: tuple[float, ...] = (20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0),
    outlier_px: float = 10.0,
    frame_step: int = 2,
    max_frames: int = 150,
    focal_prior_sd: float = FOCAL_PRIOR_SD,
    initial: np.ndarray | None = None,
) -> Calibration:
    """Relative pose (and optionally focal lengths) from body keypoints alone.

    `uv` is (2 views, frames, joints, 2) on one shared clock; frames may come from several
    recordings made without moving the phones. A single signer fills little of the frame, so
    two-view geometry is close to affine and reprojection error alone barely constrains depth
    (bas-relief / focal-depth ambiguity). Two FBX-free constraints resolve it: multi-start from the
    protocol's 30-90 deg oblique setups, and bone-length constancy, since a depth-distorted
    reconstruction stretches limbs as they turn. Gauge: camera 1 at the origin, unit baseline.
    Focal lengths, when refined, carry a log-normal prior around K1/K2 of `focal_prior_sd`, so
    their remaining uncertainty enters the covariance instead of being assumed away.
    """
    frame_step = max(frame_step, int(np.ceil(uv.shape[1] / max_frames)))
    uv = uv[:, ::frame_step]
    usable = (confidence[:, ::frame_step] >= min_confidence).all(0) & np.isfinite(uv).all(-1).all(0)
    if usable.sum() < 50:
        raise ValidationError("Fewer than 50 confident keypoints are visible in both views.")
    bones = np.array([
        (joints.index(a), joints.index(b)) for a, b in BONES if a in joints and b in joints
    ])

    def residuals(params, mask):
        pair = cameras_from(params, K1, K2)
        points = uv[:, mask]
        xyz = np.full(mask.shape + (3,), np.nan)
        xyz[mask] = triangulate(pair, points, np.ones(points.shape[:2]))
        reprojection = np.concatenate([(c.project(xyz[mask]) - p).ravel() for c, p in zip(pair, points)])
        lengths = np.linalg.norm(xyz[:, bones[:, 0]] - xyz[:, bones[:, 1]], axis=-1)
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            relative = lengths / np.nanmedian(lengths, axis=0) - 1
        prior = PRIOR_PX * params[5:7] / focal_prior_sd
        return np.concatenate([reprojection, BONE_WEIGHT_PX * np.nan_to_num(relative).ravel(), prior])

    def packed(R, t, focal=()):
        t = t / np.linalg.norm(t)
        return np.concatenate([
            Rotation.from_matrix(R).as_rotvec(),
            [np.arccos(np.clip(t[2], -1, 1)), np.arctan2(t[1], t[0])],
            focal,
        ])

    if initial is not None:
        # Warm refit (bootstrap replicates): same basin, same data selection, no multi-start.
        inliers = usable
        fit = least_squares(residuals, initial, args=(inliers,), loss="huber", f_scale=2.0)
    else:
        x1, x2 = _rays(uv[0][usable], K1), _rays(uv[1][usable], K2)
        starts = [packed(*_pose_from_essential(_essential(x1, x2), uv[0][usable], uv[1][usable], K1, K2))]
        starts += [packed(*_oblique_start(sign * yaw)) for yaw in yaw_prior_deg for sign in (1, -1)]
        # Short screening fits pick the basin; only the winner is refined to convergence.
        screened = [
            least_squares(residuals, start, args=(usable,), loss="huber", f_scale=2.0, max_nfev=20)
            for start in starts
        ]
        best = min(screened, key=lambda fit: fit.cost)
        best = least_squares(residuals, best.x, args=(usable,), loss="huber", f_scale=2.0)

        # Drop gross detector errors, then free the focal lengths if requested.
        count = 4 * usable.sum()
        error = np.linalg.norm(best.fun[:count].reshape(2, -1, 2), axis=-1).max(axis=0)
        inliers = usable.copy()
        inliers[usable] = error <= outlier_px
        start = np.concatenate([best.x, [0.0, 0.0]]) if refine_focal else best.x
        fit = least_squares(residuals, start, args=(inliers,), loss="huber", f_scale=2.0)
    pair = cameras_from(fit.x, K1, K2)
    count = 4 * inliers.sum()
    error = np.linalg.norm(fit.fun[:count].reshape(-1, 2), axis=1)
    bone_spread = fit.fun[count : count + len(fit.fun) - count - (len(fit.x) - 5)] / BONE_WEIGHT_PX
    dof = max(1, len(fit.fun) - len(fit.x))
    covariance = 2 * fit.cost / dof * np.linalg.pinv(fit.jac.T @ fit.jac)
    return Calibration(pair, fit.x, covariance, (K1, K2), {
        "pairs": int(usable.sum()),
        "inlier_fraction": float(inliers.sum() / usable.sum()),
        "reprojection_rms_px": float(np.sqrt(np.mean(error**2))),
        "bone_length_cv": float(np.sqrt(np.mean(bone_spread[bone_spread != 0] ** 2))),
        "focal_px": [float(pair[0].K[0, 0]), float(pair[1].K[0, 0])],
        "baseline_angle_deg": float(np.degrees(Rotation.from_matrix(pair[1].R).magnitude())),
    })


def self_calibrate(
    first: View,
    second_uv: np.ndarray,
    second_confidence: np.ndarray,
    K1: np.ndarray,
    K2: np.ndarray,
    **options,
) -> tuple[Camera, Camera, dict]:
    """`calibrate_pairs` for one recording; `second_uv` already resampled onto `first.times`."""
    calibration = calibrate_pairs(
        np.stack([first.uv, second_uv]), np.stack([first.confidence, second_confidence]), K1, K2, **options
    )
    return (*calibration.cameras, calibration.diagnostics)


def fill_short_gaps(times: np.ndarray, values: np.ndarray, max_gap_s: float = MAX_GAP_S) -> np.ndarray:
    """Linear fill of interior NaN runs up to `max_gap_s`; longer gaps stay missing."""
    flat = values.reshape(len(times), -1).copy()
    for column in range(flat.shape[1]):
        series = flat[:, column]
        missing = ~np.isfinite(series)
        if not missing.any() or missing.all():
            continue
        edges = np.flatnonzero(np.diff(np.concatenate([[0], missing.astype(int), [0]])))
        for start, stop in zip(edges[::2], edges[1::2]):
            if start == 0 or stop == len(series):
                continue
            if times[stop] - times[start - 1] <= max_gap_s:
                series[start:stop] = np.interp(
                    times[start:stop], [times[start - 1], times[stop]], [series[start - 1], series[stop]]
                )
    return flat.reshape(values.shape)


def lowpass(values: np.ndarray, rate: float, cutoff_hz: float = CUTOFF_HZ) -> np.ndarray:
    """Zero-lag 4th-order Butterworth (2nd order run forward and back), applied identically to
    video and FBX. Each contiguous finite run is filtered on its own; gaps stay NaN."""
    b, a = butter(2, cutoff_hz / (rate / 2))
    padding = 3 * max(len(a), len(b))
    flat = values.reshape(len(values), -1)
    out = np.full_like(flat, np.nan, dtype=float)
    for column in range(flat.shape[1]):
        finite = np.isfinite(flat[:, column])
        edges = np.flatnonzero(np.diff(np.concatenate([[0], finite.astype(int), [0]])))
        for start, stop in zip(edges[::2], edges[1::2]):
            if stop - start > padding:
                out[start:stop, column] = filtfilt(b, a, flat[start:stop, column])
    return out.reshape(values.shape)


def synchronise(
    first: View, second: View, joints: tuple[str, ...] = CASE_JOINTS, *, lag: float | None = None
) -> tuple[float, np.ndarray, np.ndarray]:
    """Lag of the second view and its keypoints/confidence resampled onto `first.times`.

    Without a given `lag` this is a coarse estimate from 2D wrist speed, which foreshortening
    biases by a frame or two; `refine_lag` corrects it once cameras are known.
    """
    if lag is None:
        rate = 1.0 / np.median(np.diff(first.times))
        lag = estimate_lag(
            wrist_speed(first.times, first.uv, joints),
            wrist_speed(first.times, _interpolate(second.times, second.uv, first.times), joints),
            rate,
        )
    shifted = second.times + lag
    return (
        lag,
        _interpolate(shifted, second.uv, first.times),
        np.nan_to_num(_interpolate(shifted, second.confidence, first.times)),
    )


def refine_lag(
    cameras: tuple[Camera, Camera], first: View, second: View, lag: float, *, search_s: float = 0.12
) -> float:
    """Sub-frame view offset that makes moving keypoints triangulate most consistently.

    Only correctly synchronised views agree geometrically while the hands move, so the median
    reprojection error of moving-frame keypoints is minimised over offsets around `lag`.
    """
    rate = 1.0 / np.median(np.diff(first.times))
    speed = wrist_speed(first.times, first.uv)
    moving = np.nan_to_num(speed) > np.nanpercentile(speed, 60)
    best, best_error = lag, np.inf
    for candidate in lag + np.arange(-search_s, search_s + 1e-9, 1.0 / (4 * rate)):
        _, uv2, conf2 = synchronise(first, second, lag=candidate)
        uv = np.stack([first.uv[moving], uv2[moving]]).reshape(2, -1, 2)
        weights = np.stack([first.confidence[moving], conf2[moving]]).reshape(2, -1)
        usable = (weights >= MIN_CONFIDENCE).all(0) & np.isfinite(uv).all(-1).all(0)
        if usable.sum() < 30:
            continue
        xyz = triangulate(cameras, uv[:, usable], np.ones((2, usable.sum())))
        error = np.median(np.max([np.linalg.norm(c.project(xyz) - p, axis=-1) for c, p in zip(cameras, uv[:, usable])], axis=0))
        if error < best_error:
            best, best_error = float(candidate), error
    return best


def triangulate_take(
    cameras: tuple[Camera, Camera],
    times: np.ndarray,
    uv: np.ndarray,
    confidence: np.ndarray,
    *,
    max_reprojection_px: float = MAX_REPROJECTION_PX,
) -> np.ndarray:
    """(2, frames, joints, 2) synced keypoints -> gap-filled (frames, joints, 3)."""
    frames, count = uv.shape[1:3]
    flat_uv = uv.reshape(2, -1, 2)
    weights = confidence.reshape(2, -1)
    usable = (weights >= MIN_CONFIDENCE).all(0) & np.isfinite(flat_uv).all(-1).all(0)
    xyz = np.full((frames * count, 3), np.nan)
    xyz[usable] = triangulate(cameras, flat_uv[:, usable], weights[:, usable])
    error = np.max([np.linalg.norm(c.project(xyz) - points, axis=-1) for c, points in zip(cameras, flat_uv)], axis=0)
    xyz[~(error <= max_reprojection_px)] = np.nan
    return fill_short_gaps(times, xyz.reshape(frames, count, 3))


def reconstruct(
    first: View,
    second: View,
    K1: np.ndarray,
    K2: np.ndarray,
    *,
    joints: tuple[str, ...] = CASE_JOINTS,
    refine_focal: bool = True,
    calibration: Calibration | None = None,
    max_reprojection_px: float = MAX_REPROJECTION_PX,
) -> TwoViewTake:
    """Sync the second view to the first, self-calibrate (unless given), triangulate, gap-fill."""
    lag, uv2, conf2 = synchronise(first, second, joints)
    uv = np.stack([first.uv, uv2])
    confidence = np.stack([first.confidence, conf2])
    if calibration is None:
        calibration = calibrate_pairs(uv, confidence, K1, K2, joints=joints, refine_focal=refine_focal)
        lag = refine_lag(calibration.cameras, first, second, lag)
        lag, uv2, conf2 = synchronise(first, second, joints, lag=lag)
        uv = np.stack([first.uv, uv2])
        confidence = np.stack([first.confidence, conf2])
        calibration = calibrate_pairs(
            uv, confidence, K1, K2, joints=joints, refine_focal=refine_focal, initial=calibration.parameters
        )
    xyz = triangulate_take(
        calibration.cameras, first.times, uv, confidence, max_reprojection_px=max_reprojection_px
    )
    diagnostics = {
        **calibration.diagnostics,
        "view_lag_s": float(lag),
        "triangulated_fraction": float(np.isfinite(xyz).all(-1).mean()),
    }
    return TwoViewTake(first.times, xyz, calibration.cameras, diagnostics)


def trim_glitches(motion: Motion, max_speed: float = MAX_JOINT_SPEED) -> tuple[Motion, list[int]]:
    """Drop leading/trailing FBX frames whose joints jump impossibly fast.

    Rokoko exports can end (or start) on a frame that snaps back to a reference pose; a single
    such frame dominates peak speed, stretches the sign window and corrupts filtering. Glitches
    inside the take are not repaired silently: the take is refused.
    Returns the trimmed motion and the dropped frame indices.
    """
    step = np.linalg.norm(np.diff(motion.joints, axis=0), axis=-1)
    jumps = np.nanmax(step, axis=1) * motion.fps > max_speed  # jump between frame i and i + 1
    if not jumps.any():
        return motion, []
    start, stop = 0, len(motion.joints)
    while start < stop - 1 and jumps[start]:
        start += 1
    while stop - 1 > start and jumps[stop - 2]:
        stop -= 1
    if jumps[start : stop - 1].any():
        bad = motion.times[start + int(np.flatnonzero(jumps[start : stop - 1])[0])]
        raise ValidationError(f"The FBX jumps impossibly fast at {bad:.2f} s, inside the take; re-export it.")
    dropped = list(range(0, start)) + list(range(stop, len(motion.joints)))
    trimmed = replace(
        motion,
        joints=motion.joints[start:stop],
        times=motion.times[start:stop],
        extras=None if motion.extras is None else motion.extras[start:stop],
    )
    return trimmed, dropped


def sign_window(motion: Motion, fraction: float = ONSET_FRACTION) -> tuple[int, int]:
    """FBX frames from onset to offset, where filtered wrist speed crosses `fraction` of peak.

    Defined on the FBX alone, before any difference is looked at.
    """
    xyz = lowpass(motion.joints, motion.fps)
    speed = wrist_speed(motion.times, xyz, CASE_JOINTS)
    above = np.nan_to_num(speed) >= fraction * np.nanmax(speed)
    # Only sustained movement counts: a filter edge or a twitch can touch the threshold for a frame.
    shortest = max(2, int(round(MIN_MOVEMENT_S * motion.fps)))
    edges = np.flatnonzero(np.diff(np.concatenate([[0], above.astype(int), [0]])))
    runs = [(start, stop) for start, stop in zip(edges[::2], edges[1::2]) if stop - start >= shortest]
    if not runs or sum(stop - start for start, stop in runs) < 10:
        raise ValidationError("The FBX contains no clear movement window.")
    return int(runs[0][0]), int(runs[-1][1])


def rest_window(motion: Motion, onset: int) -> slice:
    """The still hold just before the sign, used to measure per-angle definition offsets."""
    stop = onset - int(round(REST_GAP_S * motion.fps))
    start = max(0, stop - int(round(REST_MAX_S * motion.fps)))
    if stop - start < int(round(REST_MIN_S * motion.fps)):
        raise ValidationError(
            f"The offset rule needs at least {REST_MIN_S:g} s of stillness before the sign in the FBX "
            "(and both videos); hold the rest pose longer before signing."
        )
    return slice(start, stop)


def similarity_alignment(source: np.ndarray, target: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Umeyama scale, orthogonal matrix (reflection allowed: FBX is left-handed) and translation."""
    finite = np.isfinite(source).all(-1) & np.isfinite(target).all(-1)
    a, b = source[finite], target[finite]
    mu_a, mu_b = a.mean(0), b.mean(0)
    u, s, vt = np.linalg.svd((b - mu_b).T @ (a - mu_a) / len(a))
    rotation = u @ vt
    scale = s.sum() / np.mean(np.sum((a - mu_a) ** 2, axis=1))
    return float(scale), rotation, mu_b - scale * mu_a @ rotation.T


def evaluate_take(
    first: View,
    second: View,
    K1: np.ndarray,
    K2: np.ndarray,
    motion: Motion,
    *,
    margins: dict[str, float] | None = None,
    refine_focal: bool = True,
    **options,
) -> dict:
    """Full single-take protocol: reconstruct, put video on the FBX clock, window, test."""
    from .equivalence_single_take import load_margins, single_take_report

    if motion.joints.shape[1] != len(CASE_JOINTS):
        raise ValidationError("Load the FBX with include_elbows=True.")
    motion, _ = trim_glitches(motion)
    margins = margins or load_margins()
    take = reconstruct(first, second, K1, K2, refine_focal=refine_focal)
    video_xyz = lowpass(take.xyz, 1.0 / np.median(np.diff(take.times)))
    fbx_xyz = lowpass(motion.joints, motion.fps)

    # Video -> FBX clock from 3D wrist speed (z-scored, so the unknown video scale is irrelevant).
    lag = estimate_lag(
        wrist_speed(motion.times, fbx_xyz),
        wrist_speed(motion.times, _interpolate(take.times, video_xyz, motion.times)),
        motion.fps,
    )
    video_on_fbx = _interpolate(take.times + lag, video_xyz, motion.times)
    start, stop = sign_window(motion)
    window = slice(start, stop)
    covered = np.isfinite(video_on_fbx[window]).all(-1).mean()
    if covered < 0.95:
        raise ValidationError(
            f"Both videos must cover the whole sign window; only {covered:.0%} is triangulated."
        )
    report = single_take_report(
        {k: v[window] for k, v in joint_angles(video_on_fbx).items()},
        {k: v[window] for k, v in joint_angles(fbx_xyz).items()},
        motion.fps,
        margins,
        **options,
    )

    # Sanity only: where would the FBX skeleton land in each image after a similarity fit?
    scale, rotation, shift = similarity_alignment(fbx_xyz[window], video_on_fbx[window])
    aligned = scale * fbx_xyz[window] @ rotation.T + shift
    observed = [
        _interpolate(first.times + lag, first.uv, motion.times)[window],
        _interpolate(first.times + lag, _interpolate(second.times + take.diagnostics["view_lag_s"], second.uv, first.times), motion.times)[window],
    ]
    fbx_reprojection = [
        float(np.nanmedian(np.linalg.norm(camera.project(aligned) - uv, axis=-1)))
        for camera, uv in zip(take.cameras, observed)
    ]
    report["diagnostics"] = {
        **take.diagnostics,
        "fbx_lag_s": float(lag),
        "window_frames": [start, stop],
        "window_s": [float(motion.times[start]), float(motion.times[stop - 1])],
        "fbx_reprojection_median_px": fbx_reprojection,
    }
    return report
