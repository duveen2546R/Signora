"""Blending between independently recorded signs.

The load-bearing property is that a blended pose is still a possible pose: limbs keep their length
and the two landmark arrays keep agreeing about the joints they share. Interpolating positions
directly fails this - it shortens the forearm by 28% at the midpoint of a real blend.
"""
import numpy as np
import pytest

from app.ingest import landmarks as lm
from app.ingest.blend import (
    Pose,
    blend,
    decompose,
    enforce,
    rebuild,
    slerp_vectors,
    transition,
    transition_duration,
)


def segment_errors(skel, take):
    """Worst deviation of any constrained segment from its measured length, in metres."""
    worst = 0.0
    for (x, y), length in skel.pose_lengths.items():
        got = np.linalg.norm(take.pose[:, y] - take.pose[:, x], axis=1)
        worst = max(worst, float(np.abs(got - length).max()))
    for hand in (take.left_hand, take.right_hand):
        for (x, y), length in skel.hand_lengths.items():
            got = np.linalg.norm(hand[:, y] - hand[:, x], axis=1)
            worst = max(worst, float(np.abs(got - length).max()))
    return worst


def test_enforce_is_a_no_op_on_recorded_frames(library, skeleton):
    """Projection must not move real data; if it does, the constraints are wrong."""
    worst = 0.0
    for take in library.values():
        for i in range(0, take.frame_count, 9):
            before = Pose.at(take, i)
            after = enforce(skeleton, before)
            worst = max(worst, float(np.abs(after.pose - before.pose).max()),
                        float(np.abs(after.left_hand - before.left_hand).max()))
    assert worst < 1e-3, f"projection moved real data by {worst * 1000:.3f} mm"


def test_decompose_rebuild_round_trip(library, skeleton):
    take = next(iter(library.values()))
    frame = Pose.at(take, 5)
    out = rebuild(skeleton, decompose(skeleton, frame))
    assert np.abs(out.pose - frame.pose).max() < 1e-3


def test_shared_joints_stay_shared(library, skeleton):
    """The wrist and the knuckles appear in both arrays; they must never disagree."""
    take = next(iter(library.values()))
    out = blend(skeleton, Pose.at(take, 0), Pose.at(take, take.frame_count - 1), 0.5)
    assert np.abs(out.left_hand[0] - out.pose[15]).max() < 1e-9
    assert np.abs(out.right_hand[0] - out.pose[16]).max() < 1e-9
    for index, (side, source) in lm.POSE_FROM_HAND.items():
        hand = out.left_hand if side == "left" else out.right_hand
        assert np.abs(out.pose[index] - hand[source]).max() < 1e-9


def test_blending_preserves_limb_length_where_lerp_does_not(library, skeleton):
    """The measured failure: naive interpolation collapses the forearm mid-blend."""
    names = list(library)
    a, b = Pose.at(library[names[0]], -1), Pose.at(library[names[1]], 0)
    forearm = skeleton.pose_lengths[(14, 16)]

    naive = 0.5 * a.pose + 0.5 * b.pose
    naive_len = np.linalg.norm(naive[16] - naive[14])
    blended = blend(skeleton, a, b, 0.5)
    blended_len = np.linalg.norm(blended.pose[16] - blended.pose[14])

    assert abs(blended_len - forearm) < 1e-9
    assert abs(naive_len - forearm) > 10 * abs(blended_len - forearm)


def test_blend_endpoints_are_exact(library, skeleton):
    take = next(iter(library.values()))
    a, b = Pose.at(take, 0), Pose.at(take, 10)
    assert np.abs(blend(skeleton, a, b, 0.0).pose - a.pose).max() < 1e-3
    assert np.abs(blend(skeleton, a, b, 1.0).pose - b.pose).max() < 1e-3


def test_slerp_vectors_stays_on_the_sphere():
    rng = np.random.default_rng(3)
    a = rng.normal(size=(20, 3))
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b = rng.normal(size=(20, 3))
    b /= np.linalg.norm(b, axis=1, keepdims=True)
    for t in (0.0, 0.25, 0.5, 1.0):
        assert np.allclose(np.linalg.norm(slerp_vectors(a, b, t), axis=1), 1.0)


def test_slerp_handles_identical_and_opposite_vectors():
    same = np.array([[0.0, 1.0, 0.0]])
    assert np.allclose(slerp_vectors(same, same.copy(), 0.5), same)
    opposite = -same
    out = slerp_vectors(same, opposite, 0.5)
    assert np.all(np.isfinite(out)) and np.allclose(np.linalg.norm(out), 1.0)


def test_opposite_slerp_follows_one_continuous_great_circle():
    start = np.array([[1.0, 0.0, 0.0]])
    end = -start
    samples = np.stack([slerp_vectors(start, end, t)[0] for t in np.linspace(0, 1, 21)])
    steps = np.degrees(np.arccos(np.clip(np.sum(samples[:-1] * samples[1:], axis=1), -1, 1)))
    assert steps.max() < 10.0
    assert np.allclose(samples[0], start[0])
    assert np.allclose(samples[-1], end[0])


def test_two_bone_ik_preserves_lengths_and_elbow_side():
    from app.ingest.blend import solve_two_bone_ik

    shoulder = np.zeros(3)
    plane = np.array([0.0, 0.0, 1.0])
    elbow, wrist, _ = solve_two_bone_ik(
        shoulder, np.array([0.35, 0.10, 0.0]), 0.25, 0.22, plane,
    )
    assert np.isclose(np.linalg.norm(elbow - shoulder), 0.25)
    assert np.isclose(np.linalg.norm(wrist - elbow), 0.22)
    assert elbow[1] > 0.0, "the supplied elbow plane must select a stable bend side"


def test_contact_detector_requires_stable_slow_proximity(library):
    from app.ingest.blend import _stable_contact
    from app.ingest.landmarks import LandmarkTake

    source = next(iter(library.values()))
    pose = source.pose[:5].copy()
    left = source.left_hand[:5].copy()
    right = source.right_hand[:5].copy()
    left[:] = pose[:, 0:1]  # stationary hand on the head envelope for all three samples
    contact = LandmarkTake("contact", source.fps, pose, left, right)
    assert _stable_contact(contact, 2, forward=False).left


@pytest.mark.parametrize("release,approach", [(True, False), (False, True), (True, True)])
def test_phase_overlap_preserves_contact_shapes_during_release_and_approach(
    prepared, skeleton, monkeypatch, release, approach,
):
    from app.ingest import blend as blending
    from app.ingest.segment import find_stroke

    a, b = list(prepared.values())[:2]
    end, start = find_stroke(a).end - 1, find_stroke(b).start
    # Isolate the planner from detection (tested above). The same contact states
    # must work for arbitrary recording identities, including contact at both ends.
    monkeypatch.setattr(blending, "_stable_contact", lambda _take, _index, forward:
                        blending.ContactState(hand_to_hand=approach if forward else release))
    result = blending.plan_phase_overlap(skeleton, a, end, b, start, 60.0)
    assert result.quality.metrics["contactHandshapeErrorDeg"] < 0.01
    assert segment_errors(skeleton, result.track) < 5e-4
    for active, reference, at in [(release, Pose.at(a, end), 0.25),
                                   (approach, Pose.at(b, start), 0.75)]:
        if active:
            source = decompose(skeleton, reference)
            sample = decompose(skeleton, Pose.at(result.track, int(at * result.track.frame_count)))
            np.testing.assert_allclose(sample.left_dirs, source.left_dirs, atol=1e-8)
            np.testing.assert_allclose(sample.right_dirs, source.right_dirs, atol=1e-8)
    assert np.linalg.norm(np.diff(result.track.pose[:, 16], axis=0), axis=1).max() > 0.001


def test_quality_gate_rejects_unintended_body_intersection(library, skeleton):
    from app.ingest.blend import ContactState, evaluate_transition, transition
    from app.ingest.landmarks import LandmarkTake

    take = next(iter(library.values()))
    bridge = transition(skeleton, take, 5, take, 15, fps=60.0)
    left = bridge.left_hand.copy()
    head = bridge.pose[:, list(range(11))].mean(axis=1)
    left[:, [0, 4, 8, 12, 16, 20]] = head[:, None]
    colliding = LandmarkTake(bridge.name, bridge.fps, bridge.pose, left, bridge.right_hand)
    quality = evaluate_transition(
        skeleton, take, 5, colliding, take, 15,
        {"outgoing": ContactState(), "incoming": ContactState()},
    )
    assert not quality.passed
    assert quality.metrics["collisionFrames"] > 0
    assert any("intersects" in reason for reason in quality.reasons)


def test_transition_duration_scales_with_distance(library, skeleton):
    """A fixed duration suits neither a 4 cm nor a 62 cm move."""
    names = list(library)
    pairs = []
    for i, a in enumerate(names):
        b = names[(i + 1) % len(names)]
        start, end = Pose.at(library[a], -1), Pose.at(library[b], 0)
        gap = max(np.linalg.norm(end.pose[15] - start.pose[15]),
                  np.linalg.norm(end.pose[16] - start.pose[16]))
        pairs.append((gap, transition_duration(start, end)))
    pairs.sort()
    durations = [d for _, d in pairs]
    assert durations == sorted(durations), "duration must not decrease as the gap grows"
    assert pairs[0][1] < pairs[-1][1]


def test_transition_is_rigid_throughout(library, skeleton):
    names = list(library)
    a, b = library[names[0]], library[names[1]]
    bridge = transition(skeleton, a, a.frame_count - 1, b, 0, fps=60.0)
    assert bridge.frame_count > 0
    assert segment_errors(skeleton, bridge) < 5e-4


def test_transition_carries_the_boundary_velocity(library, skeleton):
    """Zero-velocity transitions arrive stationary and the next sign resumes at speed.

    That velocity step at the seam is exactly what a transition exists to remove, so the generated
    motion must leave and arrive moving.
    """
    names = list(library)
    a, b = library[names[0]], library[names[1]]
    bridge = transition(skeleton, a, a.frame_count - 1, b, 0, fps=60.0)

    entry = np.linalg.norm(bridge.pose[1, 16] - bridge.pose[0, 16]) * 60.0
    b_speed = np.linalg.norm(b.pose[1, 16] - b.pose[0, 16]) * b.fps
    assert entry > 0.0
    # Arrival should be in the same ballpark as the sign it hands over to, not a standing start.
    exit_speed = np.linalg.norm(bridge.pose[-1, 16] - bridge.pose[-2, 16]) * 60.0
    assert exit_speed > 0.1 * b_speed or b_speed < 0.05


def test_coast_decelerates_instead_of_freezing(library, skeleton):
    from app.ingest.blend import coast
    take = next(iter(library.values()))
    settle = coast(skeleton, take, take.frame_count - 1, 6, 60.0)
    assert settle.frame_count == 6
    speed = np.linalg.norm(np.diff(settle.pose[:, 16], axis=0), axis=1) * 60.0
    if speed.size > 1:
        assert speed[-1] <= speed[0] + 1e-9, "a coast must not accelerate"
    assert segment_errors(skeleton, settle) < 5e-4
