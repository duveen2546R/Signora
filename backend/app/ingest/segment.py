"""Find the meaning-bearing part of a recorded sign.

Every take is recorded as a single sign performed from rest, so it contains three phases: the hand
travels up into position (preparation), performs the sign (the stroke), and returns (retraction).
Measured across the library, preparation runs 0.20-0.70s and retraction 0.03-0.67s - a large
fraction of each recording.

In a sentence only the stroke carries meaning. Preparation and retraction describe a journey to and
from rest that is wrong once the sign has a neighbour: the hand should arrive from the previous
sign, not from the performer's lap. Detecting the stroke is what lets a mid-sentence word be
*reached* rather than restarted.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import savgol_filter

from .landmarks import LandmarkTake

# Fraction of the reference wrist speed that counts as "moving". Measured against the 90th
# percentile rather than the maximum: two of the five takes contain a single corrupt final frame
# where the whole skeleton teleports, and a max-based threshold is dominated by that one sample.
# 0.35 x p90 reproduces the phase boundaries observed in all five takes.
ACTIVE_FRACTION = 0.35
SPEED_REFERENCE_PERCENTILE = 90

# Nothing meaningful in a sign moves slower than this. Comparing against zero instead lets
# floating-point noise in a completely static clip read as movement.
MIN_ACTIVITY_CM_S = 1.0

# A frame where the median displacement of every pose landmark exceeds this is not motion - it is a
# broken sample. Real signing sits near 0.1 cm per frame here; the corrupt frames measure 8-17 cm.
CORRUPT_MEDIAN_STEP_CM = 3.0

# Cap how far a boundary may slide downhill looking for a velocity minimum.
MAX_WALK_SECONDS = 0.15

# Signs contain internal holds, and they are long: Father is a burst, a full second of stillness at
# the forehead, then a second burst. The hold is part of the sign, so the stroke spans from the
# first burst to the last rather than taking the longest one - that would keep half of Father and
# a third of Hello. Runs shorter than this are blips, not movement, and are ignored when locating
# those outer boundaries.
MIN_BURST_SECONDS = 0.10

# Frames kept either side of the detected boundary so the stroke is never clipped into.
MARGIN_FRAMES = 2

# A seam may move into preparation/retraction to find a compatible posture, but it must never move
# into the meaning-bearing core. 150 ms is enough to find a local velocity minimum without putting
# a sign's run-up or return-to-rest back into the sentence.
SEAM_SEARCH_SECONDS = 0.15

# A stroke shorter than either guard means detection failed - a sign that is mostly a static hold
# has no strong velocity peak - so the whole clip is used instead.
MIN_STROKE_SECONDS = 0.30
MIN_STROKE_FRACTION = 0.25

WRISTS = (15, 16)
FINGERTIPS = (4, 8, 12, 16, 20)

# Palm rotation is reported as the speed of a point on the palm's edge, so it can be compared with
# translation in the same units.
PALM_RADIUS_CM = 8.0


@dataclass(frozen=True)
class Stroke:
    """Half-open [start, end) frame range, plus why it was chosen."""

    start: int
    end: int
    peak_speed_cm_s: float
    used_fallback: bool
    reason: str = ""
    dropped_head: int = 0
    dropped_tail: int = 0

    @property
    def frame_count(self) -> int:
        return self.end - self.start


def boundary_candidates(
    take: LandmarkTake, stroke: Stroke, side: str, seconds: float | None = None,
) -> range:
    """Safe entry/exit frames around a protected stroke.

    Entry candidates live before (and include) ``stroke.start``; exit candidates live after (and
    include) the final protected frame. Consequently optimizing a seam can add preparation or
    retraction, but can never remove a frame that stroke detection marked as meaning-bearing.

    ``seconds`` overrides how far the search may reach; ``None`` offers every usable frame outside
    the protected stroke. A seam is joined with the tightest window that works, so the default stays
    small and a wider one is only paid for when the tight seam cannot be built at all.
    """
    if side not in {"entry", "exit"}:
        raise ValueError("side must be 'entry' or 'exit'")
    head, tail, _ = usable_range(take)
    if seconds is None:
        window = take.frame_count
    else:
        window = max(int(round(seconds * take.fps)), 1)
    if side == "entry":
        start = max(head, stroke.start - window)
        return range(start, stroke.start + 1)
    final = max(stroke.end - 1, stroke.start)
    end = min(tail - 1, final + window)
    return range(final, end + 1)


def _smooth(speed: np.ndarray, fps: float) -> np.ndarray:
    window = int(round(0.3 * fps)) | 1        # ~0.3s, odd, never longer than the data
    if len(speed) > window >= 5:
        speed = savgol_filter(speed, window, 2)
    return np.clip(speed, 0.0, None)


def wrist_speed(take: LandmarkTake) -> np.ndarray:
    """Smoothed per-frame speed in cm/s, taking whichever wrist is moving faster."""
    if take.frame_count < 2:
        return np.zeros(max(take.frame_count, 1))
    speeds = [
        np.linalg.norm(np.diff(take.pose[:, w], axis=0), axis=1) * take.fps * 100.0
        for w in WRISTS
    ]
    return _smooth(np.maximum(*speeds), take.fps)


def activity_speed(take: LandmarkTake) -> np.ndarray:
    """How fast the sign is moving, in cm/s, counting more than where the hand is.

    Wrist translation alone misses whole categories of sign. Fingerspelling holds the hand still and
    moves only the fingers; so does any sign built from a handshape change or a twist of the wrist.
    Measured on a hand-articulation-only clip the wrist peaks at 0.0 cm/s while the fingertips reach
    103 - segmenting on the wrist alone declares the sign motionless and plays it untrimmed.

    So three things are combined, all expressed as a speed: the wrist itself, the fingertips
    *relative to their wrist* (which isolates articulation from carrying the hand around), and the
    palm's rotation as the speed of a point on its edge.
    """
    if take.frame_count < 2:
        return np.zeros(max(take.frame_count, 1))

    scale = take.fps * 100.0
    channels = [
        np.linalg.norm(np.diff(take.pose[:, w], axis=0), axis=1) * scale for w in WRISTS
    ]

    for hand in (take.left_hand, take.right_hand):
        local = hand[:, FINGERTIPS, :] - hand[:, 0:1, :]
        channels.append(np.linalg.norm(np.diff(local, axis=0), axis=2).max(axis=1) * scale)

        # Palm swing, from the wrist-to-knuckle axes the Unity retargeter also uses.
        axis = hand[:, 5] - hand[:, 0]
        axis = axis / np.maximum(np.linalg.norm(axis, axis=1, keepdims=True), 1e-9)
        cos = np.clip(np.sum(axis[:-1] * axis[1:], axis=1), -1.0, 1.0)
        channels.append(np.arccos(cos) * take.fps * PALM_RADIUS_CM)

    return _smooth(np.maximum.reduce(channels), take.fps)


def body_step_cm(take: LandmarkTake) -> np.ndarray:
    """Median frame-to-frame movement across all pose landmarks, in cm.

    A whole-body jump is a broken sample rather than a fast sign: no real motion moves every
    landmark at once. This separates cleanly - clean frames sit near 0.1 cm, corrupt ones at 8-17.
    """
    if take.frame_count < 2:
        return np.zeros(0)
    return np.median(np.linalg.norm(np.diff(take.pose, axis=0), axis=2), axis=1) * 100.0


def usable_range(take: LandmarkTake) -> tuple[int, int, int]:
    """Trim corrupt frames from the ends. Returns (start, end, interior_defects)."""
    step = body_step_cm(take)
    if step.size == 0:
        return 0, take.frame_count, 0

    bad = step > CORRUPT_MEDIAN_STEP_CM
    start, end = 0, take.frame_count
    while start < len(bad) and bad[start]:
        start += 1
    while end > start + 1 and bad[end - 2]:
        end -= 1

    interior = int(bad[start:max(end - 1, start)].sum())
    return start, end, interior


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Half-open [start, end) ranges of consecutive True values."""
    out: list[tuple[int, int]] = []
    start = None
    for i, active in enumerate(mask):
        if active and start is None:
            start = i
        elif not active and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out


def _activity_span(mask: np.ndarray, min_run: int) -> tuple[int, int]:
    """From the first real burst of movement to the last, ignoring isolated blips."""
    runs = [r for r in _runs(mask) if r[1] - r[0] >= min_run]
    if not runs:
        return 0, 0
    return runs[0][0], runs[-1][1]


def _walk_to_minimum(speed: np.ndarray, index: int, step: int, limit: int) -> int:
    """Walk downhill so the cut lands at a velocity minimum, never mid-acceleration."""
    i = index
    for _ in range(limit):
        nxt = i + step
        if not (0 <= nxt < len(speed)) or speed[nxt] > speed[i]:
            break
        i = nxt
    return i


def find_stroke(take: LandmarkTake) -> Stroke:
    head, tail, interior = usable_range(take)
    dropped_head, dropped_tail = head, take.frame_count - tail

    speed = activity_speed(take)[head:max(tail - 1, head)]
    frames = tail - head

    if frames < 5 or speed.size == 0 or speed.max() < MIN_ACTIVITY_CM_S:
        reason = ("clip too short to segment" if frames < 5
                  else "no movement detected anywhere in the clip")
        return Stroke(0, take.frame_count, float(speed.max()) if speed.size else 0.0,
                      True, reason, dropped_head, dropped_tail)

    reference = float(np.percentile(speed, SPEED_REFERENCE_PERCENTILE))
    peak = float(speed.max())
    active = speed > ACTIVE_FRACTION * reference
    lo, hi = _activity_span(active, max(int(round(MIN_BURST_SECONDS * take.fps)), 1))
    if hi <= lo:
        return Stroke(head, tail, peak, True, "no sustained movement found",
                      dropped_head, dropped_tail)

    walk = max(int(round(MAX_WALK_SECONDS * take.fps)), 1)
    lo = _walk_to_minimum(speed, lo, -1, walk)
    hi = _walk_to_minimum(speed, max(hi - 1, lo), +1, walk)

    start = head + max(lo - MARGIN_FRAMES, 0)
    end = head + min(hi + 1 + MARGIN_FRAMES, frames)

    count = end - start
    if count / take.fps < MIN_STROKE_SECONDS or count < MIN_STROKE_FRACTION * frames:
        return Stroke(head, tail, peak, True,
                      f"detected stroke was only {count} of {frames} usable frames",
                      dropped_head, dropped_tail)

    reason = f"{interior} interior defect frames" if interior else ""
    return Stroke(start, end, peak, False, reason, dropped_head, dropped_tail)


# --- Three-phase split: start / sign / end -----------------------------------------------------
#
# `find_stroke` separates movement from dead time, which is not the same thing as separating the
# sign from its run-up. Measured on the library, every stroke it returns *begins with the wrist at
# rest* and travels 50-77 cm up and back down: the reach from rest and the return to rest both sit
# inside it. Playing that mid-sentence replays the whole rest-to-sign-to-rest arc, which is what
# makes a sentence read as separate performances rather than one utterance.
#
# So the sign proper is located inside that envelope, either from hand-authored `Phase` labels in
# the CSV or, failing that, from how far the hand travels away from where it was resting.

# Fraction of the peak excursion that counts as "in signing space". Excursion rather than height,
# because a sign performed at the chest barely rises but still travels.
SIGN_EXCURSION_FRACTION = 0.55

# A start or end section shorter than this is not worth playing and counts as absent.
MIN_PHASE_SECONDS = 0.12

# How far either side of the excursion crossing to look for the quietest frame. A sign should be cut
# where the hand actually pauses: leaving a boundary at speed asks the bridge to depart at a velocity
# the remaining distance cannot absorb, and the clamp that stops it overshooting then produces a
# visible step instead. Walking downhill to the first local minimum is not enough - it stops at the
# first dip, which on real takes is still mid-movement.
BOUNDARY_SEARCH_SECONDS = 0.25


@dataclass(frozen=True)
class Phases:
    """Half-open frame ranges for the three phases of one recording."""

    prep_start: int
    stroke_start: int
    stroke_end: int
    retract_end: int
    fps: float
    source: str            # "authored" | "detected"
    reason: str = ""

    @property
    def preparation(self) -> tuple[int, int]:
        return self.prep_start, self.stroke_start

    @property
    def stroke(self) -> tuple[int, int]:
        return self.stroke_start, self.stroke_end

    @property
    def retraction(self) -> tuple[int, int]:
        return self.stroke_end, self.retract_end

    def _long_enough(self, span: tuple[int, int]) -> bool:
        return self.fps > 0 and (span[1] - span[0]) / self.fps >= MIN_PHASE_SECONDS

    @property
    def has_preparation(self) -> bool:
        return self._long_enough(self.preparation)

    @property
    def has_retraction(self) -> bool:
        return self._long_enough(self.retraction)

    def as_dict(self) -> dict:
        def describe(span: tuple[int, int]) -> dict:
            return {
                "start": span[0],
                "end": span[1],
                "durationSeconds": round((span[1] - span[0]) / self.fps, 3) if self.fps else 0.0,
            }

        return {
            "source": self.source,
            "reason": self.reason,
            "start": describe(self.preparation),
            "sign": describe(self.stroke),
            "end": describe(self.retraction),
            "hasStart": self.has_preparation,
            "hasEnd": self.has_retraction,
        }


def _detect_sign_span(take: LandmarkTake, lo: int, hi: int) -> tuple[int, int] | None:
    """Locate the sign inside the activity envelope by how far the hand leaves its resting place."""
    speed = activity_speed(take)
    best: tuple[np.ndarray, float] | None = None
    for wrist in WRISTS:
        resting = take.pose[:max(lo, 1), wrist].mean(axis=0)
        distance = np.linalg.norm(take.pose[:, wrist] - resting, axis=1)
        peak = float(distance[lo:hi].max()) if hi > lo else 0.0
        if best is None or peak > best[1]:
            best = (distance, peak)

    distance, peak = best
    if peak <= 0.0:
        return None

    inside = np.where(distance[lo:hi] > SIGN_EXCURSION_FRACTION * peak)[0]
    if inside.size == 0:
        return None

    window = max(int(round(BOUNDARY_SEARCH_SECONDS * take.fps)), 1)

    def quietest(centre: int, low: int, high: int) -> int:
        first = max(centre - window, low)
        last = min(centre + window, high)
        if last <= first:
            return max(min(centre, high), low)
        return first + int(np.argmin(speed[first:last]))

    limit = min(hi, len(speed))
    start = quietest(lo + int(inside[0]), lo, limit)
    end = quietest(lo + int(inside[-1]), max(start + 1, lo), limit) + 1
    return max(start, lo), min(end, hi)


def find_phases(take: LandmarkTake) -> Phases:
    """Split a recording into start / sign / end.

    Authored `Phase` labels win when present: a person marking the boundary knows where the sign
    begins, and no kinematic threshold generalises across a whole vocabulary. Detection is the
    fallback so an unannotated recording still works.
    """
    stroke = find_stroke(take)
    lo, hi = stroke.start, stroke.end
    head, tail = stroke.start, stroke.end

    if take.has_phase_bounds and take.fps > 0:
        start = int(round(take.sign_start_s * take.fps))
        end = int(round(take.sign_end_s * take.fps))
        start = max(min(start, take.frame_count - 1), 0)
        end = max(min(end, take.frame_count), start + 1)
        return Phases(
            0, start, end, take.frame_count, take.fps,
            take.phase_source or "detected",
        )

    if stroke.used_fallback:
        return Phases(lo, lo, hi, hi, take.fps, "detected",
                      f"phases not separated: {stroke.reason}")

    span = _detect_sign_span(take, lo, hi)
    if span is None:
        return Phases(head, lo, hi, tail, take.fps, "detected",
                      "no clear excursion; the whole movement is treated as the sign")

    start, end = span
    if (end - start) / take.fps < MIN_STROKE_SECONDS:
        return Phases(head, lo, hi, tail, take.fps, "detected",
                      "detected sign was too short; the whole movement is treated as the sign")

    return Phases(head, start, end, tail, take.fps, "detected")
