"""Assemble a sentence into one continuous landmark track.

A sentence is not a queue of clips. Playing recordings back to back makes the avatar snap between
poses and restart every word from the performer's resting posture, which is why sentences currently
read as a slideshow. Here the strokes are extracted, the movement between them is generated, and the
whole thing is emitted as a single track:

    neutral -> [transition] -> stroke -> [transition] -> stroke -> ... -> [transition] -> neutral

Composing server-side rather than in the browser means the player has nothing to stitch, so there is
no gap at a clip boundary - and the runtime starts pulling a channel back toward its bind pose as
soon as frames are more than 0.2s old.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import blend, filters, resample
from .blend import Pose
from .landmarks import LandmarkSkeleton, LandmarkTake, concat, slice_frames
from .segment import Stroke, boundary_candidates, find_stroke, usable_range

TARGET_FPS = 60.0
ALGORITHM_VERSION = 2

# Stillness after each sign so one word reads as finished before the next begins.
HOLD_SECONDS = 0.10
FINAL_HOLD_SECONDS = 0.35
NEUTRAL_FALLBACK_HOLD_SECONDS = 0.08


class BlendRejected(ValueError):
    """Neither a direct nor a neutral bridge met the hard motion-quality constraints."""


@dataclass(frozen=True)
class Segment:
    """Where one sign or transition sits in the composed track."""

    gloss: str
    start: int
    end: int
    kind: str          # "sign" | "transition" | "hold"
    mode: str | None = None
    quality_score: float | None = None

    def as_dict(self) -> dict:
        payload = {"gloss": self.gloss, "startFrame": self.start,
                   "endFrame": self.end, "kind": self.kind}
        if self.mode is not None:
            payload["mode"] = self.mode
        if self.quality_score is not None:
            payload["qualityScore"] = round(self.quality_score, 1)
        return payload


@dataclass
class Composition:
    track: LandmarkTake
    segments: list[Segment] = field(default_factory=list)
    neutral: Pose | None = None
    blend_quality: dict = field(default_factory=dict)

    def to_payload(self, decimals: int = 4) -> dict:
        payload = self.track.to_payload(decimals)
        payload["segments"] = [s.as_dict() for s in self.segments]
        if self.neutral is not None:
            payload["neutral"] = {
                "pose": np.round(self.neutral.pose, decimals).tolist(),
                "leftHand": np.round(self.neutral.left_hand, decimals).tolist(),
                "rightHand": np.round(self.neutral.right_hand, decimals).tolist(),
            }
        if self.blend_quality:
            payload["blendQuality"] = self.blend_quality
        return payload


def enforce_track(skel: LandmarkSkeleton, take: LandmarkTake) -> LandmarkTake:
    """Project every frame back onto the skeleton's measured constraints."""
    frames = [blend.enforce(skel, Pose.at(take, i)) for i in range(take.frame_count)]
    return LandmarkTake(
        name=take.name, fps=take.fps,
        pose=np.stack([f.pose for f in frames]),
        left_hand=np.stack([f.left_hand for f in frames]),
        right_hand=np.stack([f.right_hand for f in frames]),
    )


def prepare(
    take: LandmarkTake,
    skel: LandmarkSkeleton,
    fps: float = TARGET_FPS,
    smooth: bool = True,
) -> LandmarkTake:
    """Put a clip on the playback timebase and take the sensor noise off it.

    The landmark tracks were previously written straight from the parser - raw, unsmoothed and at
    the native ~30 fps - while the resampling and filtering only fed the unused rotation path.

    Resampling and smoothing both act on each coordinate independently, which pulls joints off their
    bones - up to 10 mm on the upper arm. The projection at the end puts them back; without it the
    limb lengths drift and the joint sweeps an arc that is subtly wrong.

    Corrupt frames are dropped *first*. Two of the five source recordings end with a sample where
    the whole skeleton teleports; smoothing across one of those smears it over its neighbours, and
    it can no longer be isolated afterwards - it survives as a 4 m/s lunge at the end of the sign.
    """
    head, tail, _interior = usable_range(take)
    take = slice_frames(take, head, tail)

    times = np.arange(take.frame_count) / take.fps
    target = resample.uniform_times(times, fps)

    tracks = [
        resample.resample_positions(times, track, target)
        for track in (take.pose, take.left_hand, take.right_hand)
    ]
    if smooth:
        tracks = [filters.smooth_positions(t) for t in tracks]

    return enforce_track(skel, LandmarkTake(
        name=take.name, fps=fps,
        pose=tracks[0], left_hand=tracks[1], right_hand=tracks[2],
    ))


def neutral_pose(skel: LandmarkSkeleton, takes: list[LandmarkTake]) -> Pose:
    """A resting pose in the performer's proportions, averaged over how each take begins.

    The calibration pose cannot be used for this: it is the *avatar's* bind pose, a T-pose in the
    avatar's own proportions, which is right for zeroing the retargeter and wrong as somewhere for a
    person to stand between sentences.
    """
    generalised = [blend.decompose(skel, Pose.at(t, 0)) for t in takes]

    def mean_unit(field: str) -> np.ndarray:
        return blend._unit(np.mean([getattr(g, field) for g in generalised], axis=0))

    def mean(field: str) -> np.ndarray:
        return np.mean([getattr(g, field) for g in generalised], axis=0)

    return blend.rebuild(skel, blend.GeneralisedPose(
        hip_axis=mean_unit("hip_axis"),
        shoulders=mean("shoulders"),
        head_rotation=generalised[0].head_rotation,
        head_centroid=mean("head_centroid"),
        legs=mean("legs"),
        arm_dirs=mean_unit("arm_dirs"),
        left_dirs=mean_unit("left_dirs"),
        right_dirs=mean_unit("right_dirs"),
    ))


def _hold(take: LandmarkTake, index: int, frames: int, fps: float) -> LandmarkTake:
    if frames <= 0:
        return slice_frames(take, index, index)
    repeat = slice_frames(take, index, index + 1)
    return LandmarkTake(
        name=f"{take.name}-hold", fps=fps,
        pose=np.repeat(repeat.pose, frames, axis=0),
        left_hand=np.repeat(repeat.left_hand, frames, axis=0),
        right_hand=np.repeat(repeat.right_hand, frames, axis=0),
    )


def _single(skel: LandmarkSkeleton, pose: Pose, fps: float, name: str) -> LandmarkTake:
    return LandmarkTake(name=name, fps=fps,
                        pose=pose.pose[None], left_hand=pose.left_hand[None],
                        right_hand=pose.right_hand[None])


def compose(
    skel: LandmarkSkeleton,
    clips: list[tuple[str, LandmarkTake]],
    fps: float = TARGET_FPS,
    strokes: dict[str, Stroke] | None = None,
    rest: Pose | None = None,
    algorithm_version: int = ALGORITHM_VERSION,
) -> Composition:
    """Build and quality-gate a continuous sentence from prepared sign recordings."""
    if not clips:
        raise ValueError("a sentence needs at least one sign")
    if algorithm_version == 1:
        return _compose_legacy(skel, clips, fps, strokes, rest)
    if algorithm_version != ALGORITHM_VERSION:
        raise ValueError(f"unsupported blending algorithm version {algorithm_version}")

    strokes = strokes or {}
    detected = [strokes.get(gloss) or find_stroke(clip) for gloss, clip in clips]

    if rest is None:
        rest = neutral_pose(skel, [clip for _, clip in clips])
    rest_track = _single(skel, rest, fps, "neutral")

    # Select compatible boundary frames only from preparation/retraction. The detected stroke is a
    # protected core, so an optimizer can add context but can never clip meaning-bearing motion.
    entries = [stroke.start for stroke in detected]
    exits = [stroke.end - 1 for stroke in detected]

    first_candidates = boundary_candidates(clips[0][1], detected[0], "entry")
    entries[0] = min(
        first_candidates,
        key=lambda at: blend.seam_cost(skel, rest_track, 0, clips[0][1], at),
    )
    for i in range(len(clips) - 1):
        outgoing = boundary_candidates(clips[i][1], detected[i], "exit")
        incoming = boundary_candidates(clips[i + 1][1], detected[i + 1], "entry")
        exits[i], entries[i + 1] = min(
            ((a_at, b_at) for a_at in outgoing for b_at in incoming),
            key=lambda pair: blend.seam_cost(
                skel, clips[i][1], pair[0], clips[i + 1][1], pair[1],
            ),
        )
    last_candidates = boundary_candidates(clips[-1][1], detected[-1], "exit")
    exits[-1] = min(
        last_candidates,
        key=lambda at: blend.seam_cost(skel, clips[-1][1], at, rest_track, 0),
    )

    trimmed = [
        (gloss, slice_frames(clip, entries[i], exits[i] + 1))
        for i, (gloss, clip) in enumerate(clips)
    ]

    pieces: list[LandmarkTake] = []
    segments: list[Segment] = []
    seams: list[dict] = []
    cursor = 0

    def add(
        track: LandmarkTake,
        gloss: str,
        kind: str,
        mode: str | None = None,
        quality_score: float | None = None,
    ) -> None:
        nonlocal cursor
        if track.frame_count == 0:
            return
        pieces.append(track)
        segments.append(Segment(
            gloss, cursor, cursor + track.frame_count, kind, mode, quality_score,
        ))
        cursor += track.frame_count

    def join(
        previous: LandmarkTake,
        previous_index: int,
        following: LandmarkTake,
        following_index: int,
        from_gloss: str,
        to_gloss: str,
        from_frame: int,
        to_frame: int,
        allow_neutral: bool,
    ) -> str:
        direct = blend.plan_transition(
            skel, previous, previous_index, following, following_index, fps,
        )
        seam = {
            "fromGloss": from_gloss,
            "toGloss": to_gloss,
            "fromFrame": from_frame,
            "toFrame": to_frame,
            "mode": "direct",
            "durationMs": int(round(direct.duration * 1000)),
            "contacts": {
                name: {
                    "left": state.left,
                    "right": state.right,
                    "handToHand": state.hand_to_hand,
                }
                for name, state in direct.contacts.items()
            },
            **direct.quality.as_dict(),
        }
        if direct.quality.passed:
            add(direct.track, to_gloss, "transition", "direct", direct.quality.score)
            seams.append(seam)
            return "direct"

        if not allow_neutral:
            seams.append(seam)
            raise BlendRejected(
                f"cannot safely blend {from_gloss or 'neutral'} to {to_gloss or 'neutral'}: "
                + "; ".join(direct.quality.reasons)
            )

        into_rest = blend.plan_transition(
            skel, previous, previous_index, rest_track, 0, fps,
        )
        out_of_rest = blend.plan_transition(
            skel, rest_track, 0, following, following_index, fps,
        )
        fallback_passed = into_rest.quality.passed and out_of_rest.quality.passed
        seam.update({
            "mode": "neutral-fallback",
            "passed": fallback_passed,
            "score": round(min(into_rest.quality.score, out_of_rest.quality.score), 1),
            "durationMs": int(round((
                into_rest.duration + out_of_rest.duration + NEUTRAL_FALLBACK_HOLD_SECONDS
            ) * 1000)),
            "reasons": list(direct.quality.reasons),
            "fallback": {
                "intoNeutral": into_rest.quality.as_dict(),
                "outOfNeutral": out_of_rest.quality.as_dict(),
            },
        })
        seams.append(seam)
        if not fallback_passed:
            reasons = list(into_rest.quality.reasons) + list(out_of_rest.quality.reasons)
            raise BlendRejected(
                f"cannot safely blend {from_gloss} to {to_gloss}, including through neutral: "
                + "; ".join(dict.fromkeys(reasons))
            )

        score = min(into_rest.quality.score, out_of_rest.quality.score)
        add(into_rest.track, to_gloss, "transition", "neutral-fallback", score)
        add(_hold(
            rest_track, 0, int(round(NEUTRAL_FALLBACK_HOLD_SECONDS * fps)), fps,
        ), "", "hold", "neutral-fallback", score)
        add(out_of_rest.track, to_gloss, "transition", "neutral-fallback", score)
        return "neutral-fallback"

    add(rest_track, "", "hold")

    previous: LandmarkTake | None = rest_track
    previous_index = 0
    previous_gloss = ""
    used_fallback = False

    for position, (gloss, stroke_track) in enumerate(trimmed):
        mode = join(
            previous, previous_index, stroke_track, 0,
            previous_gloss, gloss,
            exits[position - 1] if position else 0,
            entries[position],
            allow_neutral=position > 0,
        )
        used_fallback = used_fallback or mode == "neutral-fallback"
        add(stroke_track, gloss, "sign")

        previous = stroke_track
        previous_index = stroke_track.frame_count - 1
        previous_gloss = gloss

        # Version 2 carries the measured exit velocity directly into the optimized bridge. An
        # inserted coast would move the selected boundary after it had been scored and can pull a
        # resting hand through the torso; semantic holds already inside the protected stroke remain.

    join(
        previous, previous_index, rest_track, 0,
        previous_gloss, "", exits[-1], 0, allow_neutral=False,
    )
    add(_hold(rest_track, 0, int(round(FINAL_HOLD_SECONDS * fps)), fps), "", "hold")

    score = min((float(seam["score"]) for seam in seams), default=100.0)
    quality = {
        "status": "neutral-fallback" if used_fallback else "direct",
        "score": round(score, 1),
        "algorithmVersion": ALGORITHM_VERSION,
        "seams": seams,
    }
    return Composition(
        track=concat(pieces), segments=segments, neutral=rest, blend_quality=quality,
    )


def _compose_legacy(
    skel: LandmarkSkeleton,
    clips: list[tuple[str, LandmarkTake]],
    fps: float,
    strokes: dict[str, Stroke] | None,
    rest: Pose | None,
) -> Composition:
    """Algorithm version 1, retained for comparison during the version-2 rollout."""
    strokes = strokes or {}
    trimmed = []
    for gloss, clip in clips:
        stroke = strokes.get(gloss) or find_stroke(clip)
        trimmed.append((gloss, slice_frames(clip, stroke.start, stroke.end)))
    if rest is None:
        rest = neutral_pose(skel, [clip for _, clip in clips])
    rest_track = _single(skel, rest, fps, "neutral")
    pieces: list[LandmarkTake] = [rest_track]
    segments: list[Segment] = [Segment("", 0, 1, "hold")]
    cursor = 1
    previous, previous_index = rest_track, 0
    for position, (gloss, stroke_track) in enumerate(trimmed):
        bridge = blend.transition(skel, previous, previous_index, stroke_track, 0, fps)
        for track, kind in ((bridge, "transition"), (stroke_track, "sign")):
            pieces.append(track)
            segments.append(Segment(gloss, cursor, cursor + track.frame_count, kind))
            cursor += track.frame_count
        previous, previous_index = stroke_track, stroke_track.frame_count - 1
        if position < len(trimmed) - 1:
            settle = blend.coast(
                skel, stroke_track, previous_index, int(round(HOLD_SECONDS * fps)), fps,
            )
            pieces.append(settle)
            segments.append(Segment(gloss, cursor, cursor + settle.frame_count, "hold"))
            cursor += settle.frame_count
            previous, previous_index = settle, settle.frame_count - 1
    bridge = blend.transition(skel, previous, previous_index, rest_track, 0, fps)
    pieces.append(bridge)
    segments.append(Segment("", cursor, cursor + bridge.frame_count, "transition"))
    cursor += bridge.frame_count
    final = _hold(rest_track, 0, int(round(FINAL_HOLD_SECONDS * fps)), fps)
    pieces.append(final)
    segments.append(Segment("", cursor, cursor + final.frame_count, "hold"))
    return Composition(
        concat(pieces), segments, rest,
        {"status": "direct", "score": 0.0, "algorithmVersion": 1, "seams": []},
    )
