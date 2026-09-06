# Per-sign annotation and ISL meaning review

Sentence signing uses complete reviewed English forms in
`backend/app/services/isl_patterns.json`. The initial registry intentionally contains **candidates,
not approved translations**. No fluent ISL review has been supplied with these recordings.
Until actual approval is recorded, the normal sentence composer labels a unique matching candidate
as a literal recorded-sign preview and plays it when all recordings and transitions pass the motion
checks. The explicitly labelled **Preview automatic transitions** tool also remains available to
inspect motion. Neither kind of preview constitutes linguistic approval.

**Annotate each recording once. There is no pair approval table and no requirement to configure
each neighbour.** Start/Sign/End annotations drive every occurrence of that recording automatically.
The 25-pair audit is an automated regression check, not 25 manual review tasks.

## Prepare and review

From `backend/`:

```bash
./.venv/bin/python tools/review_patterns.py --worksheet > /tmp/isl-review-worksheet.json
./.venv/bin/python tools/audit_library.py --output ../previews/isl-library-audit.json
```

The worksheet identifies each canonical recording, its content hash and authored boundaries.
Have a fluent ISL reviewer check vocabulary identity, full meaning-bearing movements (including
holds/contact), accepted English forms, gloss order, and rendered intelligibility with Deaf ISL
users. Use the library timestamp editor and the two-/three-sign transition preview on the actual
Unity avatar. Keep reviewer evidence outside public application data if it includes personal
information; the registry should carry only a non-sensitive reference to the review record.

The composer automatically tries direct motion, overlapping End/Start context, and a bounded
context search. A failure after these attempts returns diagnostics and no playable track. Investigate
the shared transition algorithm and source recording; do not create a pair-specific workaround or
shorten the Sign region to force a pass. If a source annotation is wrong, correct it once for that
sign and rerun the automated audit. Linguistic review applies to meaning, not transition settings.

## Record approval

Edit the version-controlled registry only after completing that review:

- Set `reviewStatus` to `approved` for the exact reviewed pattern.
- Supply `reviewedBy`, `reviewedAt` (ISO date), and `reviewEvidence`.
- Supply `reviewedClipHashes`, mapping every gloss in the performance to the actual reviewed
  canonical content hash. Timestamp edits and canonical-take changes invalidate this match.
- Increment the top-level registry `version`; validate with
  `./.venv/bin/python tools/review_patterns.py` and commit the review with the registry change.
- Leave `requiresUnavailableFeatures: true` on patterns needing unimplemented facial/nonmanual
  features. Such patterns are never offered as supported translations, even if marked approved.

Do not invent grammar by deleting English words. Add each accepted complete English variant to
`forms`. Candidate examples are greetings and thanks, alone, addressed to father, or combined.
Matching preserves question marks, negation, apostrophes and numbers; case, whitespace and simple
punctuation are normalized. Ambiguous matches are rejected. Exact reviewed phrases take precedence
over reviewed spelling slots.

New vocabulary needs no animation special cases. Record it, mark its boundaries, select its
canonical take, and include it in the reviewer-approved patterns. A new word is not automatically
an approved standalone translation merely because it exists in storage.

## Fingerspelling

There is no alphabet in the current local library. Optional future patterns can explicitly include
`fingerspellSlots: ["name"]`, a form such as `hello {name}`, and gloss placeholders such as
`["HELLO", "{name}"]`. This is an interface example, **not an approved ISL pattern**. Each slot accepts
one ASCII alphabetic word. Every letter must have a canonical recording and a matching reviewed
hash. Missing letters block the whole sentence; they never produce partial fingerspelling.
Multiword names, number signing and broad sentence grammar are outside this release.

## API contracts

`POST /api/v1/translate` still accepts `{ "text": "..." }`. It adds `language`,
`translationStatus` (`ready`, `preview`, `unsupported`, `missing-signs`), `patternId`, `patternVersion`, and
structured `issues`. `ready` describes interpretation: motion can still fail, returning `track: null`,
`totalMs: 0`, and `blendQuality.status: rejected` with seam diagnostics. Playback requires ready
or uniquely matched preview interpretation, a direct passing quality result, and a fully valid track.
`preview` is intentionally not a reviewed ISL claim. Playlist items and segments
carry zero-based `occurrenceIndex` so repeated signs remain distinct.

`GET /api/v1/translate/patterns` exposes registry review states and examples. There is deliberately
no unauthenticated API that approves patterns.

`PATCH /api/v1/signs/{clip_id}/phases` accepts `signStartSeconds`, `signEndSeconds`, and optional
`expectedContentHash` (sent by the editor to detect stale edits). Times are seconds relative to the
original raw landmark track, with exclusive Sign end. It updates the same database clip only after
publishing complete new artifacts, retains old artifacts and URLs, records annotation history, and
marks linguistic review pending. The original CSV and all raw coordinates remain unchanged.
Every boundary must match a real CSV Timestamp row (sub-millisecond display rounding is accepted
and aligned to the original sample). If the CSV contains a Phase column, library edits and new
uploads must both agree with it. To change that annotation, correct the CSV Phase column and upload
a new take; the editor never silently contradicts or rewrites the source CSV.

`GET /api/v1/signs/{clip_id}/raw` verifies stored landmarks against their retained CSV, returns
`timestampsSeconds` and any `csvPhaseBounds`, and restores exact timing for legacy artifacts.
Raw timing is the original CSV Timestamp column normalized to seconds from its first row. Slider
steps and frame previews use those actual values, including irregular intervals. The composer
resamples against that same clock, not an assumed 30-fps grid. CSV content hashes also participate
in composition cache identity; a replaced/mismatched source fails explicitly.

`POST /api/v1/captures/preview` accepts a CSV multipart upload and returns raw landmarks without
registering a recording. Raw preview is a front/side skeleton, with magnification, frame stepping,
scrubbing and keyboard-operable boundary controls. Saving requires at least 0.120s of source Start/End and 0.300s of Sign. Resampling must retain the
complete annotated Sign; corrupt frames may not truncate it. The final CSV sample interval is
preserved when converting to 60 fps. Shortened nonsemantic tails do not invalidate unused phases.

`POST /api/v1/signs/preview-sequence` accepts `clipIds` (two or three IDs) for an explicit motion
review on the avatar. It uses exactly the same strict composer as translations, returns
`purpose: motion-review`, and confers no linguistic approval.

## Local audit

`previews/isl-library-audit.json` records all 25 ordered pairs of the five local canonical recordings,
including repetitions, with content hashes and algorithm version. Algorithm 7 passes **25/25** with
unchanged CSV annotations and no pair-specific configuration. It handles NAMASTE contact release
through the same contact-aware handshape transition used for any recording with detected contact.
The automated result measures motion quality; it does not approve every pair as meaningful ISL.

New vocabulary follows the same pipeline: record, annotate Start/Sign/End once, and select the
canonical take. Transition generation needs no new rules for that sign or its neighbours.
Meaningful English interpretation remains a separate reviewed-pattern registry. No linguistic
approvals were created by running the motion audit.

No database migration is needed: phase metadata/history uses the existing QC JSON. Restart the
backend and refresh the frontend after rollout; algorithm version 7 invalidates old compositions.
