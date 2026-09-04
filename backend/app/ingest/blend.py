"""Geometrically valid blending between independently recorded signs.

Two signs recorded separately have no relationship to each other: the second one starts from
whatever posture the performer happened to be in, not from where the first one ended. Joining them
means generating the movement in between, and doing it in a way that keeps the skeleton valid.

Landmark positions cannot simply be interpolated. Blending two real takes shortens the forearm by up
to 28% at the midpoint; because Unity reads only normalised directions, the avatar does not visibly
stretch, but the joint sweeps a distorted arc at uneven angular velocity. So every pose is expressed
in generalised coordinates - unit directions for everything that has a constant length, positions
only for genuine degrees of freedom - interpolated there, and rebuilt.

Transitions also have to be velocity-continuous. Wrist speed at a stroke boundary runs at 22-29% of
the take's peak, and two of the five takes end at 79-88% of peak because the recording was cut
mid-retraction. A zero-velocity cross-fade would visibly stop and restart at every seam, so
transitions are quintic Hermites carrying the measured boundary velocities.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.spatial.transform import Rotation, Slerp

from . import landmarks as lm
from .landmarks import LandmarkSkeleton, LandmarkTake

_EPS = 1e-9

# Transition duration as a function of how far the hands must travel. Fits the measured range:
# a 4.2 cm gap lands near the floor, a 61.8 cm gap near 0.42 s.
DURATION_BASE = 0.10
DURATION_PER_METRE = 0.52
MIN_DURATION = 0.12
MAX_DURATION = 0.60

# A transition must not outrun the avatar. Unity rate-limits arm bones to 720 deg/s, and on a 28 cm
# forearm that is about 350 cm/s at the wrist - a faster transition is silently truncated on screen
# rather than played. Duration is stretched until the generated motion fits inside this.
MAX_WRIST_SPEED_CM_S = 250.0
MAX_ANGULAR_SPEED_DEG_S = 720.0
SPEED_FIT_ATTEMPTS = 6

# Transition-quality limits. Geometry and runtime-rate failures are hard failures; acceleration and
# jerk are compared with the motion next to the seam so the gate adapts to a quiet or energetic sign.
MAX_BONE_ERROR_M = 0.0005
SEAM_ENVELOPE_MULTIPLIER = 1.25
CONTACT_DISTANCE_M = 0.04
CONTACT_SPEED_M_S = 0.10
CONTACT_MIN_FRAMES = 3
TORSO_RADIUS_M = 0.10
HEAD_RADIUS_M = 0.09

# Frames either side of a boundary used to finite-difference the velocity.
VELOCITY_WINDOW = 3


@dataclass(frozen=True)
class Pose:
    """One frame: the three landmark arrays the runtime consumes."""

    pose: np.ndarray        # (33, 3)
    left_hand: np.ndarray   # (21, 3)
    right_hand: np.ndarray  # (21, 3)

    @classmethod
    def at(cls, take: LandmarkTake, index: int) -> "Pose":
        return cls(take.pose[index], take.left_hand[index], take.right_hand[index])


@dataclass(frozen=True)
class GeneralisedPose:
    """A pose in coordinates where interpolation cannot violate the skeleton.

    Constrained quantities are stored as unit directions and rebuilt at their measured length;
    only real degrees of freedom are stored as positions.
    """

    hip_axis: np.ndarray                      # (3,) unit, left hip -> right hip
    shoulders: np.ndarray                     # (2, 3) genuinely mobile, so kept as positions
    head_rotation: Rotation
    head_centroid: np.ndarray                 # (3,)
    legs: np.ndarray                          # (8, 3) drive nothing in Unity
    arm_dirs: np.ndarray                      # (4, 3) unit, in POSE_BONES order
    left_dirs: np.ndarray                     # (n, 3) unit, spokes then finger bones
    right_dirs: np.ndarray


@dataclass(frozen=True)
class ContactState:
    """Stable contact at a clip boundary, used to time handshape changes safely."""

    left: bool = False
    right: bool = False
    hand_to_hand: bool = False


@dataclass(frozen=True)
class TransitionQuality:
    """Machine-readable evidence for accepting or rejecting a generated bridge."""

    score: float
    passed: bool
    metrics: dict[str, float | int | bool]
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "passed": self.passed,
            "metrics": self.metrics,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class TransitionResult:
    track: LandmarkTake
    quality: TransitionQuality
    duration: float
    requires_neutral: bool = False
    contacts: dict[str, ContactState] = field(default_factory=dict)


_HAND_EDGES: tuple[tuple[int, int], ...] = lm.HAND_SPOKES + lm.HAND_BONES


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return np.where(n < _EPS, np.array([0.0, 1.0, 0.0]), v / np.where(n < _EPS, 1.0, n))


def _hand_dirs(hand: np.ndarray) -> np.ndarray:
    return _unit(np.stack([hand[b] - hand[a] for a, b in _HAND_EDGES]))


def decompose(skel: LandmarkSkeleton, frame: Pose) -> GeneralisedPose:
    p = frame.pose
    a, b = lm.HIP_PAIR
    head = p[list(lm.POSE_HEAD_GROUP)]
    centroid = head.mean(axis=0)
    rotation, _ = Rotation.align_vectors(head - centroid, skel.head_shape)

    return GeneralisedPose(
        hip_axis=_unit(p[b] - p[a]),
        shoulders=p[list(lm.POSE_SOFT)].copy(),
        head_rotation=rotation,
        head_centroid=centroid,
        legs=p[list(lm.POSE_FREE)].copy(),
        arm_dirs=_unit(np.stack([p[y] - p[x] for x, y in lm.POSE_BONES])),
        left_dirs=_hand_dirs(frame.left_hand),
        right_dirs=_hand_dirs(frame.right_hand),
    )


def rebuild(skel: LandmarkSkeleton, gp: GeneralisedPose) -> Pose:
    """Forward kinematics from generalised coordinates back to landmarks."""
    p = np.zeros((lm.POSE_LANDMARK_COUNT, 3))

    a, b = lm.HIP_PAIR
    p[a] = -gp.hip_axis * skel.hip_half_width
    p[b] = +gp.hip_axis * skel.hip_half_width
    p[list(lm.POSE_SOFT)] = gp.shoulders
    p[list(lm.POSE_HEAD_GROUP)] = gp.head_centroid + gp.head_rotation.apply(skel.head_shape)
    p[list(lm.POSE_FREE)] = gp.legs

    for (x, y), direction in zip(lm.POSE_BONES, gp.arm_dirs, strict=True):
        p[y] = p[x] + direction * skel.pose_lengths[(x, y)]

    hands = {}
    for side, dirs in (("left", gp.left_dirs), ("right", gp.right_dirs)):
        hand = np.zeros((lm.HAND_LANDMARK_COUNT, 3))
        # The wrist is shared with the pose array; anchoring here keeps them identical.
        hand[0] = p[lm.WRIST_IN_POSE[side]]
        for (x, y), direction in zip(_HAND_EDGES, dirs, strict=True):
            hand[y] = hand[x] + direction * skel.hand_lengths[(x, y)]
        hands[side] = hand

    for index, (side, source) in lm.POSE_FROM_HAND.items():
        p[index] = hands[side][source]

    return Pose(p, hands["left"], hands["right"])


def enforce(skel: LandmarkSkeleton, frame: Pose) -> Pose:
    """Project a pose onto the skeleton's constraints, discarding any length drift."""
    return rebuild(skel, decompose(skel, frame))


def slerp_vectors(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    """Great-circle interpolation of unit vectors, including exact antipodal pairs.

    Near-parallel vectors can safely use normalised lerp. Antiparallel vectors cannot: their lerp
    collapses to zero at the midpoint and the old fallback chose an arbitrary world-up direction,
    producing a one-frame limb flip. For those rows a deterministic perpendicular great-circle is
    selected from the least-aligned Cartesian axis.
    """
    a = np.atleast_2d(a)
    b = np.atleast_2d(b)
    dot = np.clip(np.sum(a * b, axis=-1), -1.0, 1.0)
    theta = np.arccos(dot)
    sine = np.sin(theta)

    out = np.empty_like(a)
    parallel = dot > 1.0 - 1e-7
    if np.any(parallel):
        out[parallel] = _unit((1 - t) * a[parallel] + t * b[parallel])

    opposite = dot < -1.0 + 1e-7
    if np.any(opposite):
        source = a[opposite]
        axes = np.eye(3)[np.argmin(np.abs(source), axis=1)]
        tangent = _unit(np.cross(source, axes))
        angle = np.pi * t
        out[opposite] = np.cos(angle) * source + np.sin(angle) * tangent

    far = ~(parallel | opposite)
    if np.any(far):
        s, th = sine[far][:, None], theta[far][:, None]
        out[far] = (np.sin((1 - t) * th) * a[far] + np.sin(t * th) * b[far]) / s
    return _unit(out)


def spherical_bezier(
    start: np.ndarray,
    start_rate: np.ndarray,
    end: np.ndarray,
    end_rate: np.ndarray,
    duration: float,
    taus: np.ndarray,
) -> np.ndarray:
    """Cubic Bézier on unit spheres, with endpoint controls derived from angular tangents."""
    one_vector = np.ndim(start) == 1
    start, end = np.atleast_2d(start), np.atleast_2d(end)
    c0 = _unit(start + np.atleast_2d(start_rate) * duration / 3.0)
    c1 = _unit(end - np.atleast_2d(end_rate) * duration / 3.0)
    values = []
    for tau in np.asarray(taus).reshape(-1):
        a = slerp_vectors(start, c0, float(tau))
        b = slerp_vectors(c0, c1, float(tau))
        c = slerp_vectors(c1, end, float(tau))
        d = slerp_vectors(a, b, float(tau))
        e = slerp_vectors(b, c, float(tau))
        values.append(slerp_vectors(d, e, float(tau)))
    result = np.stack(values)
    return result[:, 0] if one_vector else result


def blend(skel: LandmarkSkeleton, a: Pose, b: Pose, t: float) -> Pose:
    """Interpolate two poses at parameter t, preserving every measured constraint."""
    ga, gb = decompose(skel, a), decompose(skel, b)
    key = Slerp([0.0, 1.0], Rotation.concatenate([ga.head_rotation, gb.head_rotation]))
    return rebuild(skel, GeneralisedPose(
        hip_axis=slerp_vectors(ga.hip_axis, gb.hip_axis, t)[0],
        shoulders=(1 - t) * ga.shoulders + t * gb.shoulders,
        head_rotation=key(t),
        head_centroid=(1 - t) * ga.head_centroid + t * gb.head_centroid,
        legs=(1 - t) * ga.legs + t * gb.legs,
        arm_dirs=slerp_vectors(ga.arm_dirs, gb.arm_dirs, t),
        left_dirs=slerp_vectors(ga.left_dirs, gb.left_dirs, t),
        right_dirs=slerp_vectors(ga.right_dirs, gb.right_dirs, t),
    ))


def _quintic_hermite(p0, v0, p1, v1, tau):
    """Hermite with zero acceleration at both ends - minimum jerk when the tangents are zero.

    `v0`/`v1` are tangents already expressed per unit of tau (i.e. velocity multiplied by duration).
    """
    tau = np.asarray(tau).reshape((-1,) + (1,) * (np.ndim(p0)))
    t3 = tau ** 3
    t4 = tau ** 4
    t5 = tau ** 5
    h00 = 1 - 10 * t3 + 15 * t4 - 6 * t5
    h10 = tau - 6 * t3 + 8 * t4 - 3 * t5
    h01 = 10 * t3 - 15 * t4 + 6 * t5
    h11 = -4 * t3 + 7 * t4 - 3 * t5
    return h00 * p0 + h10 * v0 + h01 * p1 + h11 * v1


def _quintic_boundary(p0, v0, a0, p1, v1, a1, duration, tau):
    """Quintic trajectory matching endpoint position, velocity, and measured acceleration."""
    tau = np.asarray(tau).reshape((-1,) + (1,) * np.ndim(p0))
    c0 = p0
    c1 = v0 * duration
    c2 = 0.5 * a0 * duration ** 2
    delta = p1 - c0 - c1 - c2
    velocity = v1 * duration - c1 - 2.0 * c2
    acceleration = a1 * duration ** 2 - 2.0 * c2
    c3 = 10.0 * delta - 4.0 * velocity + 0.5 * acceleration
    c4 = -15.0 * delta + 7.0 * velocity - acceleration
    c5 = 6.0 * delta - 3.0 * velocity + 0.5 * acceleration
    return c0 + c1 * tau + c2 * tau ** 2 + c3 * tau ** 3 + c4 * tau ** 4 + c5 * tau ** 5


def _septic_boundary(p0, v0, a0, j0, p1, v1, a1, j1, duration, tau):
    """Seventh-order trajectory matching position through jerk at both recorded boundaries."""
    tau = np.asarray(tau).reshape((-1,) + (1,) * np.ndim(p0))
    c0 = p0
    c1 = v0 * duration
    c2 = 0.5 * a0 * duration ** 2
    c3 = (1.0 / 6.0) * j0 * duration ** 3
    rhs = np.stack([
        p1 - c0 - c1 - c2 - c3,
        v1 * duration - c1 - 2.0 * c2 - 3.0 * c3,
        a1 * duration ** 2 - 2.0 * c2 - 6.0 * c3,
        j1 * duration ** 3 - 6.0 * c3,
    ])
    matrix = np.array([
        [1.0, 1.0, 1.0, 1.0],
        [4.0, 5.0, 6.0, 7.0],
        [12.0, 20.0, 30.0, 42.0],
        [24.0, 60.0, 120.0, 210.0],
    ])
    c4, c5, c6, c7 = np.linalg.solve(matrix, rhs)
    return (
        c0 + c1 * tau + c2 * tau ** 2 + c3 * tau ** 3 + c4 * tau ** 4
        + c5 * tau ** 5 + c6 * tau ** 6 + c7 * tau ** 7
    )


def _tangent(q0: np.ndarray, q1: np.ndarray, rate: np.ndarray, duration: float) -> np.ndarray:
    """Endpoint tangent, clamped so a fast exit velocity cannot overshoot the target.

    Two takes end at 79-88% of their peak speed; without this the Hermite swings the hand well past
    where the next sign starts before coming back.
    """
    tangent = rate * duration
    span = np.linalg.norm(q1 - q0, axis=-1, keepdims=True)
    magnitude = np.linalg.norm(tangent, axis=-1, keepdims=True)
    limit = np.maximum(span, _EPS)
    scale = np.where(magnitude > limit, limit / np.maximum(magnitude, _EPS), 1.0)
    return tangent * scale


def _rate(take: LandmarkTake, index: int, skel: LandmarkSkeleton, forward: bool) -> GeneralisedPose:
    """Velocity of the generalised coordinates at `index`, in units per second.

    `forward` selects which side of `index` to difference against, and it has to point *into* the
    clip: the outgoing boundary is a clip's last frame, where there is nothing ahead to difference
    against, and the incoming boundary is frame 0, where there is nothing behind. Getting this
    backwards silently yields zero velocity at both ends - the transition then arrives stationary
    and the stroke resumes at full speed, putting a velocity step exactly at the seam the
    transition exists to smooth.
    """
    step = min(VELOCITY_WINDOW, max(1, take.frame_count - 1))
    other = min(index + step, take.frame_count - 1) if forward else max(index - step, 0)
    span = abs(other - index) / take.fps
    if span < _EPS:
        return None

    here = decompose(skel, Pose.at(take, index))
    there = decompose(skel, Pose.at(take, other))
    sign = 1.0 / span if forward else -1.0 / span

    return GeneralisedPose(
        hip_axis=(there.hip_axis - here.hip_axis) * sign,
        shoulders=(there.shoulders - here.shoulders) * sign,
        head_rotation=Rotation.identity(),
        head_centroid=(there.head_centroid - here.head_centroid) * sign,
        legs=(there.legs - here.legs) * sign,
        arm_dirs=(there.arm_dirs - here.arm_dirs) * sign,
        left_dirs=(there.left_dirs - here.left_dirs) * sign,
        right_dirs=(there.right_dirs - here.right_dirs) * sign,
    )


def transition_duration(a: Pose, b: Pose) -> float:
    """Distance-only compatibility helper retained for algorithm version 1."""
    gap = max(
        float(np.linalg.norm(b.pose[15] - a.pose[15])),
        float(np.linalg.norm(b.pose[16] - a.pose[16])),
    )
    return float(np.clip(DURATION_BASE + DURATION_PER_METRE * gap, MIN_DURATION, MAX_DURATION))


def required_transition_duration(skel: LandmarkSkeleton, a: Pose, b: Pose) -> float:
    """Unclamped time required by travel and angular articulation limits."""
    gap = max(float(np.linalg.norm(b.pose[w] - a.pose[w])) for w in (15, 16))
    ga, gb = decompose(skel, a), decompose(skel, b)
    arm = float(np.arccos(np.clip(np.sum(ga.arm_dirs * gb.arm_dirs, axis=1), -1, 1)).max())
    fingers_a = np.concatenate([ga.left_dirs, ga.right_dirs])
    fingers_b = np.concatenate([gb.left_dirs, gb.right_dirs])
    fingers = float(np.arccos(np.clip(np.sum(fingers_a * fingers_b, axis=1), -1, 1)).max())
    return max(
        DURATION_BASE + DURATION_PER_METRE * gap,
        arm / np.deg2rad(360.0),
        fingers / np.deg2rad(240.0),
        MIN_DURATION,
    )


def _point_velocity(take: LandmarkTake, index: int, points: np.ndarray, forward: bool) -> np.ndarray:
    step = min(VELOCITY_WINDOW, max(1, take.frame_count - 1))
    other = min(index + step, take.frame_count - 1) if forward else max(index - step, 0)
    span = abs(other - index) / take.fps
    if span < _EPS:
        return np.zeros_like(points[index])
    sign = 1.0 if forward else -1.0
    return (points[other] - points[index]) * sign / span


def _point_acceleration(
    take: LandmarkTake, index: int, points: np.ndarray, forward: bool,
) -> np.ndarray:
    """One-sided boundary acceleration from three frames inside the recorded clip."""
    if take.frame_count < 3:
        return np.zeros_like(points[index])
    if forward:
        i0, i1, i2 = index, min(index + 1, take.frame_count - 1), min(index + 2, take.frame_count - 1)
    else:
        i0, i1, i2 = index, max(index - 1, 0), max(index - 2, 0)
    if len({i0, i1, i2}) < 3:
        return np.zeros_like(points[index])
    return (points[i2] - 2.0 * points[i1] + points[i0]) * take.fps ** 2


def _point_jerk(take: LandmarkTake, index: int, points: np.ndarray, forward: bool) -> np.ndarray:
    """One-sided chronological jerk from four frames inside a clip boundary."""
    if take.frame_count < 4:
        return np.zeros_like(points[index])
    if forward:
        indices = [min(index + step, take.frame_count - 1) for step in range(4)]
        if len(set(indices)) < 4:
            return np.zeros_like(points[index])
        p0, p1, p2, p3 = (points[i] for i in indices)
        return (p3 - 3.0 * p2 + 3.0 * p1 - p0) * take.fps ** 3
    indices = [max(index - step, 0) for step in range(4)]
    if len(set(indices)) < 4:
        return np.zeros_like(points[index])
    p0, p1, p2, p3 = (points[i] for i in indices)
    return (p0 - 3.0 * p1 + 3.0 * p2 - p3) * take.fps ** 3


def _stable_contact(take: LandmarkTake, index: int, forward: bool) -> ContactState:
    """Detect contact over three samples on the available side of a boundary."""
    direction = 1 if forward else -1
    indices = [int(np.clip(index + direction * i, 0, take.frame_count - 1))
               for i in range(CONTACT_MIN_FRAMES)]
    body_indices = list(lm.POSE_HEAD_GROUP) + [11, 12, 23, 24]
    side_hits: dict[str, bool] = {}
    for side, hand in (("left", take.left_hand), ("right", take.right_hand)):
        distances = []
        speeds = []
        for at in indices:
            tips = hand[at, [0, 4, 8, 12, 16, 20]]
            body = take.pose[at, body_indices]
            distances.append(float(np.linalg.norm(tips[:, None] - body[None, :], axis=2).min()))
            speeds.append(float(np.linalg.norm(_point_velocity(take, at, hand, forward)[0])))
        side_hits[side] = max(distances) <= CONTACT_DISTANCE_M and max(speeds) <= CONTACT_SPEED_M_S

    hand_distance = [float(np.linalg.norm(
        take.left_hand[at, [0, 4, 8, 12, 16, 20], None]
        - take.right_hand[at, None, [0, 4, 8, 12, 16, 20]], axis=-1,
    ).min()) for at in indices]
    return ContactState(
        left=side_hits["left"], right=side_hits["right"],
        hand_to_hand=max(hand_distance) <= CONTACT_DISTANCE_M,
    )


def seam_cost(
    skel: LandmarkSkeleton,
    a: LandmarkTake,
    a_index: int,
    b: LandmarkTake,
    b_index: int,
) -> float:
    """Perceptual mismatch between two safe boundary candidates; lower is easier to join."""
    pa, pb = Pose.at(a, a_index), Pose.at(b, b_index)
    ga, gb = decompose(skel, pa), decompose(skel, pb)
    scale = max(sum(skel.pose_lengths.values()) / max(len(skel.pose_lengths), 1), 0.20)
    wrist = np.mean([np.linalg.norm(pb.pose[w] - pa.pose[w]) / scale for w in (15, 16)])
    arm = np.mean(1.0 - np.sum(ga.arm_dirs * gb.arm_dirs, axis=1))
    hand = np.mean(1.0 - np.sum(
        np.concatenate([ga.left_dirs, ga.right_dirs])
        * np.concatenate([gb.left_dirs, gb.right_dirs]), axis=1,
    ))
    va = np.stack([_point_velocity(a, a_index, a.pose[:, w], False) for w in (15, 16)])
    vb = np.stack([_point_velocity(b, b_index, b.pose[:, w], True) for w in (15, 16)])
    velocity = np.linalg.norm(va - vb, axis=1).mean() / 2.5
    elbow_plane = np.mean([
        1.0 - float(np.dot(
            _elbow_plane(pa, shoulder, elbow, wrist),
            _elbow_plane(pb, shoulder, elbow, wrist),
        ))
        for shoulder, elbow, wrist in ((11, 13, 15), (12, 14, 16))
    ])
    body = np.linalg.norm(ga.shoulders - gb.shoulders, axis=1).mean() / scale
    return float(
        0.30 * wrist + 0.15 * arm + 0.20 * hand + 0.15 * velocity
        + 0.15 * elbow_plane + 0.05 * body
    )


def transition(
    skel: LandmarkSkeleton,
    a: LandmarkTake, a_index: int,
    b: LandmarkTake, b_index: int,
    fps: float,
    duration: float | None = None,
) -> LandmarkTake:
    """Frames carrying the avatar from `a[a_index]` to `b[b_index]`.

    Returns the in-between frames only - neither endpoint is repeated, so the result concatenates
    directly between the two strokes.

    The duration comes from how far the hands must travel, then is stretched if the resulting motion
    would exceed what the avatar can actually display.
    """
    return plan_transition(skel, a, a_index, b, b_index, fps, duration).track


def plan_transition(
    skel: LandmarkSkeleton,
    a: LandmarkTake,
    a_index: int,
    b: LandmarkTake,
    b_index: int,
    fps: float,
    duration: float | None = None,
) -> TransitionResult:
    """Build and objectively validate one direct bridge."""
    start, end = Pose.at(a, a_index), Pose.at(b, b_index)
    required = required_transition_duration(skel, start, end)
    velocity_mismatch = max(
        float(np.linalg.norm(
            _point_velocity(a, a_index, a.pose[:, wrist], forward=False)
            - _point_velocity(b, b_index, b.pose[:, wrist], forward=True)
        ))
        for wrist in (15, 16)
    )
    required = max(required, velocity_mismatch / 6.0)  # 6 m/s² comfortable correction envelope
    requires_neutral = duration is None and required > MAX_DURATION
    span = float(duration if duration is not None else np.clip(required, MIN_DURATION, MAX_DURATION))
    contacts = {
        "outgoing": _stable_contact(a, a_index, forward=False),
        "incoming": _stable_contact(b, b_index, forward=True),
    }

    bridge = _build_transition(
        skel, a, a_index, b, b_index, fps, span,
        contacts["outgoing"], contacts["incoming"],
    )
    for _ in range(SPEED_FIT_ATTEMPTS):
        wrist_peak = _max_wrist_speed(bridge)
        angular_peak = _max_angular_speed(skel, bridge)
        factor = max(
            wrist_peak / MAX_WRIST_SPEED_CM_S,
            angular_peak / MAX_ANGULAR_SPEED_DEG_S,
            1.0,
        )
        if duration is not None or factor <= 1.0 or span >= MAX_DURATION:
            break
        span = min(span * factor, MAX_DURATION)
        bridge = _build_transition(
            skel, a, a_index, b, b_index, fps, span,
            contacts["outgoing"], contacts["incoming"],
        )

    quality = evaluate_transition(
        skel, a, a_index, bridge, b, b_index, contacts,
        requires_neutral=requires_neutral,
    )
    # Rate limits alone are not enough: a short bridge can be under the speed ceiling yet still
    # create an acceleration/jerk spike at its endpoints. Stretch it until those measured seam
    # envelopes pass, or until the direct-transition ceiling sends it to neutral fallback.
    for _ in range(SPEED_FIT_ATTEMPTS):
        stretchable = all(
            any(token in reason for token in ("speed", "acceleration", "jerk"))
            for reason in quality.reasons
        )
        if quality.passed or not stretchable or duration is not None or span >= MAX_DURATION:
            break
        accel_ratio = float(quality.metrics["seamAccelerationRatio"])
        jerk_ratio = float(quality.metrics["seamJerkRatio"])
        factor = max(
            np.sqrt(max(accel_ratio / SEAM_ENVELOPE_MULTIPLIER, 1.0)),
            np.cbrt(max(jerk_ratio / SEAM_ENVELOPE_MULTIPLIER, 1.0)),
            1.08,
        )
        span = min(span * factor, MAX_DURATION)
        bridge = _build_transition(
            skel, a, a_index, b, b_index, fps, span,
            contacts["outgoing"], contacts["incoming"],
        )
        quality = evaluate_transition(
            skel, a, a_index, bridge, b, b_index, contacts,
            requires_neutral=requires_neutral,
        )
    return TransitionResult(bridge, quality, span, requires_neutral, contacts)


def _elbow_plane(frame: Pose, shoulder: int, elbow: int, wrist: int) -> np.ndarray:
    reach = frame.pose[wrist] - frame.pose[shoulder]
    bend = frame.pose[elbow] - frame.pose[shoulder]
    normal = np.cross(reach, bend)
    if np.linalg.norm(normal) < _EPS:
        axis = np.eye(3)[np.argmin(np.abs(_unit(reach)))]
        normal = np.cross(reach, axis)
    return _unit(normal)


def solve_two_bone_ik(
    shoulder: np.ndarray,
    target: np.ndarray,
    upper_length: float,
    lower_length: float,
    plane_normal: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Analytical shoulder/elbow/wrist solution with a stable elbow plane."""
    delta = target - shoulder
    distance = float(np.linalg.norm(delta))
    direction = _unit(delta)
    minimum = abs(upper_length - lower_length) + 1e-7
    maximum = upper_length + lower_length - 1e-7
    reachable = float(np.clip(distance, minimum, maximum))
    wrist = shoulder + direction * reachable
    along = (upper_length ** 2 - lower_length ** 2 + reachable ** 2) / (2.0 * reachable)
    height = np.sqrt(max(upper_length ** 2 - along ** 2, 0.0))
    bend = _unit(np.cross(_unit(plane_normal), direction))
    elbow = shoulder + direction * along + bend * height
    return elbow, wrist, direction


def _handshape_taus(
    taus: np.ndarray,
    outgoing: ContactState,
    incoming: ContactState,
    side: str,
) -> np.ndarray:
    """Keep a released contact's shape briefly; form an arriving contact before approach."""
    outgoing_contact = outgoing.hand_to_hand or getattr(outgoing, side)
    incoming_contact = incoming.hand_to_hand or getattr(incoming, side)
    if outgoing_contact and not incoming_contact:
        return np.clip((taus - 0.30) / 0.70, 0.0, 1.0)
    if incoming_contact and not outgoing_contact:
        return np.clip(taus / 0.70, 0.0, 1.0)
    return taus


def _build_transition(
    skel: LandmarkSkeleton,
    a: LandmarkTake, a_index: int,
    b: LandmarkTake, b_index: int,
    fps: float,
    duration: float,
    outgoing_contact: ContactState | None = None,
    incoming_contact: ContactState | None = None,
) -> LandmarkTake:
    start, end = Pose.at(a, a_index), Pose.at(b, b_index)
    count = max(int(round(duration * fps)) - 1, 1)
    ga, gb = decompose(skel, start), decompose(skel, end)
    # Difference into each clip: backwards at A's final frame, forwards from B's first.
    va, vb = _rate(a, a_index, skel, forward=False), _rate(b, b_index, skel, forward=True)

    taus = (np.arange(1, count + 1) / (count + 1)).astype(np.float64)

    def curve(field: str, unit: bool, curve_taus: np.ndarray | None = None) -> np.ndarray:
        q0 = getattr(ga, field)
        q1 = getattr(gb, field)
        r0 = getattr(va, field) if va else np.zeros_like(q0)
        r1 = getattr(vb, field) if vb else np.zeros_like(q1)
        selected_taus = taus if curve_taus is None else curve_taus
        if unit:
            return spherical_bezier(q0, r0, q1, r1, duration, selected_taus)
        t0 = _tangent(q0, q1, r0, duration)
        t1 = _tangent(q0, q1, r1, duration)
        return _quintic_hermite(q0, t0, q1, t1, selected_taus)

    hip = curve("hip_axis", True)
    shoulders = curve("shoulders", False)
    centroid = curve("head_centroid", False)
    legs = curve("legs", False)
    arms = curve("arm_dirs", True)
    outgoing_contact = outgoing_contact or ContactState()
    incoming_contact = incoming_contact or ContactState()
    left = curve(
        "left_dirs", True,
        _handshape_taus(taus, outgoing_contact, incoming_contact, "left"),
    )
    right = curve(
        "right_dirs", True,
        _handshape_taus(taus, outgoing_contact, incoming_contact, "right"),
    )

    # Plan wrists in Cartesian space, then solve the two arm chains analytically. This produces the
    # minimum-jerk path a viewer sees while the IK projection keeps both arm segments rigid.
    wrist_paths: dict[str, np.ndarray] = {}
    plane_paths: dict[str, np.ndarray] = {}
    for side, shoulder_index, elbow_index, wrist_index in (
        ("left", 11, 13, 15), ("right", 12, 14, 16),
    ):
        p0, p1 = start.pose[wrist_index], end.pose[wrist_index]
        v0 = _point_velocity(a, a_index, a.pose[:, wrist_index], forward=False)
        v1 = _point_velocity(b, b_index, b.pose[:, wrist_index], forward=True)
        a0 = _point_acceleration(a, a_index, a.pose[:, wrist_index], forward=False)
        a1 = _point_acceleration(b, b_index, b.pose[:, wrist_index], forward=True)
        j0 = _point_jerk(a, a_index, a.pose[:, wrist_index], forward=False)
        j1 = _point_jerk(b, b_index, b.pose[:, wrist_index], forward=True)
        # Boundary rates are clamped by the same span rule used by the generalized coordinates;
        # convert the safe tangents back to per-second values for the full boundary polynomial.
        safe_v0 = _tangent(p0, p1, v0, duration) / duration
        safe_v1 = _tangent(p0, p1, v1, duration) / duration
        wrist_paths[side] = _septic_boundary(
            p0, safe_v0, a0, j0, p1, safe_v1, a1, j1, duration, taus,
        )
        n0 = _elbow_plane(start, shoulder_index, elbow_index, wrist_index)
        n1 = _elbow_plane(end, shoulder_index, elbow_index, wrist_index)
        plane_paths[side] = np.stack([slerp_vectors(n0, n1, float(t))[0] for t in taus])

    for i in range(count):
        for side, shoulder_index, arm_offset in (("left", 11, 0), ("right", 12, 2)):
            upper = skel.pose_lengths[lm.POSE_BONES[arm_offset]]
            lower = skel.pose_lengths[lm.POSE_BONES[arm_offset + 1]]
            elbow, wrist, _ = solve_two_bone_ik(
                shoulders[i, 0 if side == "left" else 1],
                wrist_paths[side][i], upper, lower, plane_paths[side][i],
            )
            shoulder = shoulders[i, 0 if side == "left" else 1]
            arms[i, arm_offset] = _unit(elbow - shoulder)
            arms[i, arm_offset + 1] = _unit(wrist - elbow)

    key = Slerp([0.0, 1.0], Rotation.concatenate([ga.head_rotation, gb.head_rotation]))
    # Head orientation is a minor channel; ease it along the geodesic rather than Hermite it.
    eased = _quintic_hermite(0.0, 0.0, 1.0, 0.0, taus).reshape(-1)
    heads = key(np.clip(eased, 0.0, 1.0))

    frames = [
        rebuild(skel, GeneralisedPose(
            hip_axis=hip[i], shoulders=shoulders[i], head_rotation=heads[i],
            head_centroid=centroid[i], legs=legs[i], arm_dirs=arms[i],
            left_dirs=left[i], right_dirs=right[i],
        ))
        for i in range(count)
    ]

    return LandmarkTake(
        name=f"{a.name}->{b.name}",
        fps=fps,
        pose=np.stack([f.pose for f in frames]),
        left_hand=np.stack([f.left_hand for f in frames]),
        right_hand=np.stack([f.right_hand for f in frames]),
    )


def _max_wrist_speed(take: LandmarkTake) -> float:
    if take.frame_count < 2:
        return 0.0
    return max(float(
        (np.linalg.norm(np.diff(take.pose[:, wrist], axis=0), axis=1) * take.fps * 100.0).max()
    ) for wrist in (15, 16))


def _max_angular_speed(skel: LandmarkSkeleton, take: LandmarkTake) -> float:
    if take.frame_count < 2:
        return 0.0
    directions = []
    for i in range(take.frame_count):
        gp = decompose(skel, Pose.at(take, i))
        directions.append(np.concatenate([gp.arm_dirs, gp.left_dirs, gp.right_dirs]))
    rows = np.stack(directions)
    dots = np.clip(np.sum(rows[:-1] * rows[1:], axis=-1), -1.0, 1.0)
    return float(np.degrees(np.arccos(dots)).max() * take.fps)


def _max_bone_error(skel: LandmarkSkeleton, take: LandmarkTake) -> float:
    worst = 0.0
    for (x, y), length in skel.pose_lengths.items():
        got = np.linalg.norm(take.pose[:, y] - take.pose[:, x], axis=1)
        worst = max(worst, float(np.abs(got - length).max()))
    for hand in (take.left_hand, take.right_hand):
        for (x, y), length in skel.hand_lengths.items():
            got = np.linalg.norm(hand[:, y] - hand[:, x], axis=1)
            worst = max(worst, float(np.abs(got - length).max()))
    return worst


def _point_segment_distance(point: np.ndarray, start: np.ndarray, end: np.ndarray) -> float:
    axis = end - start
    denom = float(np.dot(axis, axis))
    if denom < _EPS:
        return float(np.linalg.norm(point - start))
    along = float(np.clip(np.dot(point - start, axis) / denom, 0.0, 1.0))
    return float(np.linalg.norm(point - (start + along * axis)))


def _collision_count(take: LandmarkTake, contacts: dict[str, ContactState]) -> int:
    allowed = {
        "left": contacts["outgoing"].left or contacts["incoming"].left
                or contacts["outgoing"].hand_to_hand or contacts["incoming"].hand_to_hand,
        "right": contacts["outgoing"].right or contacts["incoming"].right
                 or contacts["outgoing"].hand_to_hand or contacts["incoming"].hand_to_hand,
    }
    hits: dict[str, list[bool]] = {"left": [], "right": []}
    for i in range(take.frame_count):
        shoulder = take.pose[i, [11, 12]].mean(axis=0)
        hips = take.pose[i, [23, 24]].mean(axis=0)
        head = take.pose[i, list(lm.POSE_HEAD_GROUP)].mean(axis=0)
        for side, hand in (("left", take.left_hand), ("right", take.right_hand)):
            if allowed[side]:
                hits[side].append(False)
                continue
            points = hand[i, [0, 4, 8, 12, 16, 20]]
            inside = [
                _point_segment_distance(point, hips, shoulder) < TORSO_RADIUS_M
                or np.linalg.norm(point - head) < HEAD_RADIUS_M
                for point in points
            ]
            # A single curled fingertip near the chest is normal at rest. Count a penetration only
            # when the wrist or at least three fingertips enter an envelope, and only in the middle
            # of the path rather than while intentionally approaching either endpoint.
            middle = 0.15 * take.frame_count <= i <= 0.85 * take.frame_count
            hits[side].append(bool(middle and (inside[0] or sum(inside[1:]) >= 3)))

    collisions = 0
    for side_hits in hits.values():
        for i, hit in enumerate(side_hits):
            if hit and ((i > 0 and side_hits[i - 1]) or (i + 1 < len(side_hits) and side_hits[i + 1])):
                collisions += 1
    return collisions


def _seam_dynamics(
    a: LandmarkTake, a_index: int, bridge: LandmarkTake, b: LandmarkTake, b_index: int,
) -> tuple[float, float]:
    """Acceleration/jerk ratios at the two joins against nearby recorded motion."""
    window = 8
    left = a.pose[max(0, a_index - window):a_index + 1]
    right = b.pose[b_index:min(b.frame_count, b_index + window + 1)]
    combined = np.concatenate([left, bridge.pose, right], axis=0)
    if len(combined) < 5:
        return 0.0, 0.0

    ratios = []
    for wrist in (15, 16):
        velocity = np.diff(combined[:, wrist], axis=0) * bridge.fps * 100.0
        acceleration = np.linalg.norm(np.diff(velocity, axis=0), axis=1) * bridge.fps
        jerk = np.abs(np.diff(acceleration)) * bridge.fps

        source_accel_parts = []
        source_jerk_parts = []
        for source in (left[:, wrist], right[:, wrist]):
            source_velocity = np.diff(source, axis=0) * bridge.fps * 100.0
            source_accel = np.linalg.norm(np.diff(source_velocity, axis=0), axis=1) * bridge.fps
            source_accel_parts.append(source_accel)
            source_jerk_parts.append(np.abs(np.diff(source_accel)) * bridge.fps)
        source_accel = np.concatenate(source_accel_parts)
        source_jerk = np.concatenate(source_jerk_parts)
        accel_limit = max(float(np.percentile(source_accel, 95)) if source_accel.size else 0.0, 1200.0)
        jerk_limit = max(float(np.percentile(source_jerk, 95)) if source_jerk.size else 0.0, 12000.0)

        boundaries = (len(left) - 1, len(left) + bridge.frame_count - 1)
        accel_samples = np.concatenate([
            acceleration[max(boundary - 2, 0):min(boundary + 3, len(acceleration))]
            for boundary in boundaries
        ])
        jerk_samples = np.concatenate([
            jerk[max(boundary - 2, 0):min(boundary + 2, len(jerk))]
            for boundary in boundaries
        ])
        seam_accel = float(accel_samples.max()) if accel_samples.size else 0.0
        seam_jerk = float(jerk_samples.max()) if jerk_samples.size else 0.0
        ratios.append((seam_accel / accel_limit, seam_jerk / jerk_limit))
    return max(r[0] for r in ratios), max(r[1] for r in ratios)


def _contact_handshape_error(
    skel: LandmarkSkeleton,
    a: LandmarkTake,
    a_index: int,
    bridge: LandmarkTake,
    b: LandmarkTake,
    b_index: int,
    contacts: dict[str, ContactState],
) -> float:
    """Largest handshape error where an outgoing/incoming contact must still be established."""
    if bridge.frame_count == 0:
        return 0.0
    start = decompose(skel, Pose.at(a, a_index))
    end = decompose(skel, Pose.at(b, b_index))
    early = decompose(skel, Pose.at(bridge, min(int(0.25 * bridge.frame_count), bridge.frame_count - 1)))
    late = decompose(skel, Pose.at(bridge, min(int(0.75 * bridge.frame_count), bridge.frame_count - 1)))
    errors = [0.0]
    for side in ("left", "right"):
        outgoing = contacts["outgoing"].hand_to_hand or getattr(contacts["outgoing"], side)
        incoming = contacts["incoming"].hand_to_hand or getattr(contacts["incoming"], side)
        if outgoing:
            source, sample = getattr(start, f"{side}_dirs"), getattr(early, f"{side}_dirs")
            errors.append(float(np.degrees(np.arccos(
                np.clip(np.sum(source * sample, axis=1), -1.0, 1.0)
            )).max()))
        if incoming:
            target, sample = getattr(end, f"{side}_dirs"), getattr(late, f"{side}_dirs")
            errors.append(float(np.degrees(np.arccos(
                np.clip(np.sum(target * sample, axis=1), -1.0, 1.0)
            )).max()))
    return max(errors)


def evaluate_transition(
    skel: LandmarkSkeleton,
    a: LandmarkTake,
    a_index: int,
    bridge: LandmarkTake,
    b: LandmarkTake,
    b_index: int,
    contacts: dict[str, ContactState],
    requires_neutral: bool = False,
) -> TransitionQuality:
    finite = bool(
        np.isfinite(bridge.pose).all()
        and np.isfinite(bridge.left_hand).all()
        and np.isfinite(bridge.right_hand).all()
    )
    bone_error = _max_bone_error(skel, bridge)
    # The runtime experiences A -> bridge -> B as one stream. Measuring only differences between
    # bridge frames misses the two most important steps and can approve a visually obvious snap at
    # either boundary. Include both recorded endpoints in the rate-limit window.
    seam_track = LandmarkTake(
        name=f"{a.name}->{b.name}-quality-window",
        fps=bridge.fps,
        pose=np.concatenate([
            a.pose[a_index:a_index + 1], bridge.pose, b.pose[b_index:b_index + 1],
        ]),
        left_hand=np.concatenate([
            a.left_hand[a_index:a_index + 1],
            bridge.left_hand,
            b.left_hand[b_index:b_index + 1],
        ]),
        right_hand=np.concatenate([
            a.right_hand[a_index:a_index + 1],
            bridge.right_hand,
            b.right_hand[b_index:b_index + 1],
        ]),
    )
    wrist_speed = _max_wrist_speed(seam_track)
    angular_speed = _max_angular_speed(skel, seam_track)
    acceleration_ratio, jerk_ratio = _seam_dynamics(a, a_index, bridge, b, b_index)
    collisions = _collision_count(bridge, contacts)
    contact_error = _contact_handshape_error(
        skel, a, a_index, bridge, b, b_index, contacts,
    )

    metrics: dict[str, float | int | bool] = {
        "finite": finite,
        "maxBoneErrorMm": round(bone_error * 1000.0, 4),
        "maxWristSpeedCmS": round(wrist_speed, 2),
        "maxAngularSpeedDegS": round(angular_speed, 2),
        "seamAccelerationRatio": round(acceleration_ratio, 3),
        "seamJerkRatio": round(jerk_ratio, 3),
        "collisionFrames": collisions,
        "contactHandshapeErrorDeg": round(contact_error, 2),
    }
    reasons = []
    checks = (
        (not finite, "transition contains non-finite landmark values"),
        (bone_error > MAX_BONE_ERROR_M, "transition violates measured bone lengths"),
        (wrist_speed > MAX_WRIST_SPEED_CM_S * 1.02, "wrist speed exceeds the avatar limit"),
        (angular_speed > MAX_ANGULAR_SPEED_DEG_S * 1.02, "joint speed exceeds the avatar limit"),
        (acceleration_ratio > SEAM_ENVELOPE_MULTIPLIER,
         "seam acceleration exceeds the adjacent-motion envelope"),
        (jerk_ratio > SEAM_ENVELOPE_MULTIPLIER,
         "seam jerk exceeds the adjacent-motion envelope"),
        (collisions > 0, "transition intersects the torso or head"),
        (contact_error > 8.0, "contact handshape is not ready at the required boundary"),
        (requires_neutral, "direct transition requires more than 600 ms"),
    )
    reasons.extend(message for failed, message in checks if failed)
    penalties = [
        min(wrist_speed / MAX_WRIST_SPEED_CM_S, 1.5),
        min(angular_speed / MAX_ANGULAR_SPEED_DEG_S, 1.5),
        min(acceleration_ratio / SEAM_ENVELOPE_MULTIPLIER, 1.5),
        min(jerk_ratio / SEAM_ENVELOPE_MULTIPLIER, 1.5),
        min(collisions / 3.0, 1.5),
        min(contact_error / 8.0, 1.5),
    ]
    score = max(0.0, 100.0 - 8.0 * sum(penalties) - (20.0 if requires_neutral else 0.0))
    return TransitionQuality(score, not reasons, metrics, tuple(reasons))


def coast(
    skel: LandmarkSkeleton,
    take: LandmarkTake,
    index: int,
    frames: int,
    fps: float,
) -> LandmarkTake:
    """Let the pose at `index` decelerate to a stop over `frames`, instead of freezing there.

    A sign needs a beat of stillness after it or the next one runs into it. Repeating the final
    frame provides that, but it drops the velocity to zero in a single frame - measured as the
    largest acceleration spike anywhere in a composed sentence, larger than anything in the recorded
    motion it sits between. Coasting to rest keeps the pause and removes the spike.
    """
    if frames <= 0:
        return LandmarkTake(name=f"{take.name}-coast", fps=fps,
                            pose=take.pose[:0], left_hand=take.left_hand[:0],
                            right_hand=take.right_hand[:0])

    duration = frames / fps
    start = decompose(skel, Pose.at(take, index))
    rate = _rate(take, index, skel, forward=False)
    taus = ((np.arange(frames) + 1) / frames).astype(np.float64)

    def curve(field: str, unit: bool) -> np.ndarray:
        q0 = getattr(start, field)
        v0 = getattr(rate, field) * duration if rate is not None else np.zeros_like(q0)
        # Minimum-jerk deceleration from v0 to rest covers half of v0 * T.
        q1 = q0 + v0 * 0.5
        values = _quintic_hermite(q0, v0, q1, np.zeros_like(q1), taus)
        return _unit(values) if unit else values

    hip = curve("hip_axis", True)
    shoulders = curve("shoulders", False)
    centroid = curve("head_centroid", False)
    legs = curve("legs", False)
    arms = curve("arm_dirs", True)
    left = curve("left_dirs", True)
    right = curve("right_dirs", True)

    poses = [
        rebuild(skel, GeneralisedPose(
            hip_axis=hip[i], shoulders=shoulders[i], head_rotation=start.head_rotation,
            head_centroid=centroid[i], legs=legs[i], arm_dirs=arms[i],
            left_dirs=left[i], right_dirs=right[i],
        ))
        for i in range(frames)
    ]

    return LandmarkTake(
        name=f"{take.name}-coast", fps=fps,
        pose=np.stack([p.pose for p in poses]),
        left_hand=np.stack([p.left_hand for p in poses]),
        right_hand=np.stack([p.right_hand for p in poses]),
    )
