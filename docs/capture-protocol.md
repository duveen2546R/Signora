# Capture protocol

Fix this before recording vocabulary at scale. Re-shoots are expensive once the suit is off.

## Export settings

Rokoko Studio, **biomechanics CSV** export — the one with `*_position_x` and joint-angle columns
such as `RightElbow_flexion`. The pipeline validates the header against a known 331-column layout and
refuses anything else, so a changed export setting fails loudly rather than producing subtly wrong
motion.

Confirmed properties of this export: 30 fps, millisecond timestamps, world joint centres in metres,
Y-up, left-handed (the same convention as Unity — no axis conversion is applied).

## Per take

1. **0.5 s neutral rest** — arms relaxed, hands at rest, facing forward.
2. **The sign**, at a natural signing pace.
3. **Return to neutral rest**, and hold ~0.5 s.

The rest head and tail are what let clips be chained into sentences without a visible pop. A T-pose is
*not* required: bone orientations are reconstructed from joint positions, which carry no axis
convention, so there is no calibration pose to key off.

## Marking the sign phase

After selecting a CSV on the Capture screen, enter two timestamps in seconds:

- **Sign starts at**: the first meaning-bearing frame after preparation.
- **Sign ends at**: the exclusive end of the meaning-bearing range, before retraction.

The application requires at least 0.120 s of `start`, 0.300 s of `sign`, and 0.120 s of `end`.
These measured edge phases give the blender a natural route through rest when a direct transition
is unsafe. The application derives all three ranges, so do not enter three redundant durations.
Review the boundary at normal and half speed: handshape formation and intentional contact belong
inside `sign`.

For bulk/API uploads, an optional `Phase` CSV column may label every frame `start`, `sign`, or
`end`. Labels must be contiguous and ordered. Files without UI timestamps or a complete Phase
column are rejected.

## Naming

One sign per file, `{gloss}_{take}.csv` — `hello_01.csv`, `good_morning_02.csv`. The gloss and take
number are parsed from the filename, so a typo here creates a new vocabulary entry.

## Practice

- Re-calibrate the gloves at the start of every session; note it in the session log.
- Record **3 takes per sign** and pick the best at QC time.
- Keep both hands inside the signing space and avoid one hand fully occluding the other.
- Watch the ingest warnings: bone lengths that vary by more than a few millimetres mean the suit
  calibration drifted, and that take should be re-recorded.

## Priority order for vocabulary

1. **The manual alphabet.** Any word with no recorded sign falls back to fingerspelling, so the
   alphabet multiplies the usable vocabulary immediately.
2. Function and greeting words that appear in most sentences.
3. Topic vocabulary.
