# Automatic transitions from per-sign phases

Each capture is annotated once with two boundaries on its CSV clock:

| Section | Time range |
|---|---|
| Start (preparation) | `0 → signStart` |
| Sign (meaning-bearing movement and holds) | `signStart → signEnd` |
| End (retraction) | `signEnd → duration` |

The composer selects phases by the occurrence's position in the resolved sign sequence:

| Position | Retained recorded sections |
|---|---|
| Single | Start + Sign + End |
| First | Start + Sign |
| Middle | Sign |
| Last | Sign + End |

There is no pair configuration or pair approval registry. A newly recorded sign uses the same
algorithm with any neighbour. Sentence meaning is resolved separately through reviewed ISL
patterns; motion previews and regression audits do not claim linguistic correctness.

## CSV timestamps are authoritative

Raw motion retains `timestampsSeconds` from the CSV Timestamp column, normalized to its first row.
Scrubbing, frame stepping, boundary input and resampling all use that same clock, including uneven
sample intervals. Boundary input must match a real row; sub-millisecond display rounding aligns to
that row. If the CSV has Phase labels, supplied boundaries must agree with them.

Existing recordings can be edited through the library without uploading again. Raw preview verifies
stored motion against the retained CSV. Boundary edits publish new content-addressed artifacts,
atomically update the same clip reference, and preserve old artifacts and the original source CSV.
Changing CSV Phase labels requires correcting the source and uploading a new take; the editor
never silently contradicts the CSV. Artifact and CSV hashes participate in composition caching.

Corrupt frames are removed before resampling. Any removal overlapping an authored Sign rejects the
capture instead of trimming meaning. Resampling preserves the final CSV sample interval as well as
the full Sign range. A nonsemantic tail shortened during cleanup does not invalidate a phase that
isn't needed at that sentence position.

## Algorithm 7: compose automatically, validate every bridge

The backend prepares the selected recordings together on one measured skeleton at 60 fps. Each
prepared Sign section, including its internal holds and contacts, appears exactly once. Start and
End sections retained by position remain contiguous with their own Sign.

For each join the algorithm tries:

1. A direct velocity-aware transition between the retained endpoints, using Cartesian wrist
   trajectories, two-bone inverse kinematics and spherical interpolation of bone directions.
2. If needed, an overlap shaped by the outgoing sign's End and incoming sign's Start. The source
   trajectories continue near their annotated boundaries while a smooth weight transfers control.
   Its first three derivatives vanish at the endpoints. A bounded search tests durations from
   0.2 to 1.6 seconds and nearby phase context; the first passing candidate is used. No Sign frames
   are removed, and no neutral waypoint is inserted.
3. A bounded search over adjacent End/Start context if overlap still fails. Context that would
   restore a standalone neutral reset is excluded. If every strategy fails, reject the composition.

Handshape timing is separate from wrist travel. Detected outgoing contacts retain their shape
through release; incoming contacts form before approach. The overlap delays outgoing shape changes
through the first 30% of travel and completes incoming changes by 70%, using smooth spherical
interpolation. This also handles contact at both ends. No sign names appear in this logic.

All frames are rebuilt using measured arm, finger and palm-spoke lengths. Shared hand/body joints
remain identical. Generated bridges must pass finite-coordinate, bone-length, wrist/joint speed,
seam acceleration/jerk, contact readiness and body-intersection checks. Quality thresholds are
unchanged. The longer overlap search allows natural movement time instead of rejecting solely
because the initial direct planner exceeded its 600-ms window.

The whole performance is a continuous track:

```text
rest → Start + Sign → transition → Sign → transition → Sign + End → rest
```

No artificial holds or neutral resets are inserted between signs. Natural movement between signs
still takes time. Opening and closing bridges must also pass; a failed bridge returns no playable
track and retains diagnostics identifying the signs and quality failures.

## Playback and diagnostics

`blendQuality.status: direct` means all bridges passed, including phase-assisted ones. A seam can
report `strategy: phase-overlap`; `phaseOverlapAttempt` preserves its measured quality. Rejected
composition returns `track: null` and `totalMs: 0`.

The browser receives and validates the complete track before starting. It streams frames through
the existing calibrated Unity path. Occurrence indices distinguish repeated signs. Hiding the tab
pauses the playback clock; returning resumes from the same position instead of skipping signing.

Cache identity includes algorithm version, ordered clip hashes, phase annotations and source CSV
hashes. A phase edit or source change cannot reuse an old composition.

## Automated checks

From `backend/`:

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python tools/audit_library.py --output ../previews/isl-library-audit.json
```

The local audit passes **all 25 ordered pairs**, including repetitions, of HELLO, FATHER, THANKYOU,
GOOD_MORNING and NAMASTE with their existing CSV annotations unchanged. This is an automated
regression audit, not work the user must do for every pair. Future captures still pass the same
runtime quality gates; these results do not guarantee arbitrary damaged captures will play.

See [per-sign annotation and ISL meaning review](isl-review.md) for timestamp editing and the
separate process for reviewing vocabulary identity and sentence meaning.

Algorithm 1 is retained only for historical comparisons via `compose(..., algorithm_version=1)`;
normal application playback always uses the current strict composer.
