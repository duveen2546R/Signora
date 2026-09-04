# Blending signs into a sentence

Signs are recorded one at a time, each performed from rest. Played back to back they read as a
slideshow: the avatar snaps between poses at each boundary, and every word restarts from the
performer's resting posture as though it were the only word in the sentence.

The backend composes the whole sentence into **one continuous landmark track** instead:

```
neutral -> [transition] -> stroke -> [transition] -> stroke -> [transition] -> neutral
```

The player streams that single track, so there is no boundary at which the frame stream could pause
— the runtime starts pulling a channel back toward its bind pose after 0.2 s without frames.

Algorithm version 2 optimizes and validates every boundary. Version 1 remains available through
`compose(..., algorithm_version=1)` while the new behavior is reviewed.

## Only the stroke is played

Each recording contains preparation, the stroke, and retraction. Measured across the library,
preparation runs **0.20–0.70 s** and retraction **0.03–0.67 s**. Only the stroke carries meaning;
preparation describes a journey from rest that is wrong once the sign has a neighbour.

`segment.py` finds it from smoothed wrist speed:

- The reference is the **90th percentile**, not the maximum. Two of the five recordings end with a
  frame where the whole skeleton teleports; a max-based threshold is dominated by that one sample.
- Activity is speed above **35 % of that reference**, which reproduces the phase boundaries visible
  in all five takes.
- The stroke spans the **first burst to the last**, not the longest one. Signs contain long internal
  holds — `Father` is a burst, a full second still at the forehead, then a second burst — so taking
  the longest contiguous run keeps half the sign.
- Boundaries then walk downhill to a velocity minimum so a cut never lands mid-acceleration.
- If the result is under 0.3 s or under a quarter of the clip, the whole clip is used instead: a
  sign that is mostly a held pose has no velocity peak to find.

Corrupt frames are dropped **before** resampling. Smoothing across one smears it over its
neighbours, where it can no longer be isolated — it survives as a 4 m/s lunge at the end of the sign.

## Blending cannot interpolate positions

Interpolating landmark positions directly shortens the forearm by **28 %** at the midpoint of a real
blend. Unity reads only normalised directions, so the avatar does not visibly stretch — but the joint
sweeps a distorted arc at uneven angular velocity, which is the artefact blending exists to remove.

So every pose is decomposed into generalised coordinates, interpolated there, and rebuilt. What is
constrained is only what was *measured* to be constant across the library:

| Quantity | Spread | Treatment |
|---|---|---|
| Hip width | 0.00 mm | constrained |
| Wrist → each knuckle | 0.00 mm | five independent constrained spokes |
| Arm and finger bones | 0.00 mm | constrained |
| Head landmarks 0–10 | 0.07 mm residual | rigid group |
| **Shoulder width** | **41.64 mm** | **free** — real shoulder-girdle motion |
| **Palm as a whole** | **32.48 mm residual** | **free** — the metacarpal arch genuinely flexes |

Six pose landmarks (17–22) are the same joints as entries in the hand arrays and are derived from
them, so the two arrays can never disagree about where a knuckle is. Same for the wrist, which is
`pose[15]`/`pose[16]` and `hand[0]`.

## Boundaries are selected, not assumed

The detected stroke is a protected meaning-bearing core. For each neighboring pair, version 2 may
add up to 150 ms of preparation or retraction while searching for compatible entry and exit frames;
it can never move a boundary into the protected core. The pair cost includes both wrists, arm and
palm orientation, handshape, boundary velocity, elbow plane, and whole-body displacement.

This preserves internal holds and contacts while avoiding a needlessly difficult transition when a
nearby safe frame already has a compatible posture.

## Transitions carry velocity and preserve anatomy

Wrist speed at a stroke boundary is **22–29 % of peak**, not zero, and two takes end at 79–88 % of
peak because the recording was cut mid-retraction. A zero-velocity cross-fade would visibly stop and
restart at every seam, so transitions are **quintic Hermites with the measured boundary velocities**
(minimum jerk when those are zero).

The velocities are differenced *into* each clip — backwards at A's final frame, forwards from B's
first. Getting that direction wrong silently yields zero at both ends, which is exactly the
discontinuity the transition exists to remove.

Each wrist follows a Cartesian seventh-order boundary spline carrying measured position, velocity,
acceleration, and jerk into and out of the transition. Analytical two-bone IK places the elbow and
wrist while preserving the measured upper-arm and forearm lengths and a stable interpolated elbow
plane. Hip, arm, palm, and finger directions use spherical cubic Bézier curves. Exact antiparallel
directions take a deterministic great-circle route instead of collapsing at midpoint.

Stable hand-to-hand and hand-to-body contacts are detected over three frames. An outgoing contact
keeps its handshape through release; an incoming contact forms its handshape before approach.

Duration scales with distance, `0.10 + 0.52 x gap` seconds, because the gap between consecutive
signs ranges from **4.2 cm to 61.8 cm**. It is then stretched if the generated motion would exceed
**250 cm/s** at the wrist: Unity rate-limits arm bones to 720 °/s, which on a 28 cm forearm is about
350 cm/s, and a faster transition is silently truncated on screen rather than played.

## Quality gate and neutral fallback

Every bridge is checked for finite coordinates, 0.5 mm bone-length tolerance, wrist and joint rate
limits, acceleration and jerk relative to adjacent motion, contact readiness, and torso or head
intersections. The translate response includes additive `blendQuality` metadata with one of:

- `direct`: every bridge passed directly.
- `neutral-fallback`: an unsafe direct pair was replaced by two validated bridges through neutral.
- `rejected`: direct and neutral routes both failed, so no track is returned.

Each transition segment also carries `mode` and `qualityScore`. The cache key includes the ordered
clip content hashes and algorithm version, so an algorithm update cannot reuse stale motion.

## Version 1 holds coast, they do not freeze

A beat of stillness after each sign keeps words from running together. Repeating the final frame
provides that but drops velocity to zero in a single frame — measured as the largest acceleration
anywhere in a composed sentence, larger than anything in the recorded motion it sits between.
Instead the pose **coasts** to rest along a minimum-jerk deceleration.

With that, seams accelerate at 44 cm/s per frame against 46 inside the recorded motion: **the joins
are smoother than the footage they connect.**

## Checking it

```bash
cd backend && ./.venv/bin/python tools/preview_sentence.py ThankYou Father -o sentence.html
```

Renders the composed track as a stick figure with the segment timeline, both-wrist speed,
acceleration, jerk, selected seam frames, contact markers, quality scores, and fallback mode. The
tests prove a track is geometrically legal; fluent-signer review still decides whether it is
linguistically correct.
