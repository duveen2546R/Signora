# Independent motion validation

## Website recording relationship and validity

The **Analysis** page now distinguishes one simultaneous performance, separate repetitions, and
unknown correspondence. The API records `recording_relationship`; omitted website values default
to `unknown`. Separate/unknown recordings produce **movement similarity** only. They cannot enter
matched accuracy scoring or LMEM, and synchronization is not applicable even if event timestamps
are supplied. Legacy research manifests without the field retain their original matched-study
interpretation; authors must correct any erroneous attestation.

Case reports show native skeleton proportions, initial-pose discontinuities, camera sensitivity,
and the two FBX projections over sampled reference video frames. These diagnostics do not choose
the camera fit by wrist error, remove preparation frames, or assert that either method must win.
Pose differences across repetitions combine performance variation, skeleton proportions, tracking,
and projection. Changing alignment cannot isolate capture error from those components.

For a capture-accuracy study, obtain a synchronized reference of **each actual captured take**.
When the two capture methods require separate takes, each needs its own corresponding reference;
the current three-file interface is a similarity comparison for that arrangement. Compare the
resulting per-take errors across a prespecified balanced study, with camera geometry, reference
uncertainty, and skeleton definitions verified independently of the desired ranking.

This research toolkit compares **two FBX reconstructions of the same recorded human action** with a third, independently recorded reference video of that exact performance. It does not change the SignSure upload API or claim that one method is better before a matched study is completed. A single camera supports **image-plane (2D)** wrist accuracy in units of reference shoulder width; it is not 3D millimetre ground truth.

## Install and prepare

From `backend/`, use your activated Python environment:

```sh
python -m pip install -r requirements-validation.txt
python -m pip install -r requirements-validation-video.txt
python -m pip install -r requirements-validation-secondary.txt
```

The video step needs a MediaPipe **Pose Landmarker `.task` model**, obtained from the [official Pose Landmarker model page](https://ai.google.dev/edge/mediapipe/solutions/vision/pose_landmarker). Keep the model file and record its version/hash in study notes. The research CLI takes its local path; no model is bundled with the application.

For each human performance, identify the exact suit FBX, non-suit FBX, and independent MP4. Confirm action, performer, repetition, and synchronization manually. The existing FBX files in `Downloads` have **not** been established as matched trials. To extract an editable landmark CSV:

```sh
python tools/validation_pipeline.py extract-video /absolute/path/reference.mp4 \
  --pose-model /absolute/path/pose_landmarker.task \
  --output /absolute/path/reference_pose.csv
python tools/validation_pipeline.py hash /absolute/path/suit.fbx \
  /absolute/path/non_suit.fbx /absolute/path/reference.mp4 \
  /absolute/path/reference_pose.csv
```

Review the CSV against the video, particularly hand crossings, occlusion, left/right identity, mirroring, and the neutral calibration interval. A blank joint is missing, never a zero-coordinate landmark. If corrected manually, recalculate its hash.

## Matched-trial manifest

Create a JSON file such as `study/trials.json` with this schema. Paths may be absolute or relative to the manifest. Use actual SHA-256 values, not the example placeholders.

```json
{
  "schema_version": 1,
  "trials": [
    {
      "performance_id": "P01-WAVE-01",
      "action_id": "WAVE",
      "performer_id": "P01",
      "repetition": "01",
      "pairing_verified_by": "reviewer name",
      "reference_independent": true,
      "suit_fbx": "/absolute/path/suit.fbx",
      "non_suit_fbx": "/absolute/path/non_suit.fbx",
      "reference_video": "/absolute/path/reference.mp4",
      "video_landmarks": "/absolute/path/reference_pose.csv",
      "sha256": {
        "suit_fbx": "<64 hex digits>",
        "non_suit_fbx": "<64 hex digits>",
        "reference_video": "<64 hex digits>",
        "video_landmarks": "<64 hex digits>"
      },
      "windows": {
        "suit": [0.2, 3.7],
        "non_suit": [0.0, 3.5],
        "video": [1.4, 4.9]
      },
      "calibration_phase": [0.0, 0.15]
    }
  ]
}
```

Each window is seconds from that source's first frame. The three windows must cover the **same action**, including its start and end. `calibration_phase` is a fraction of the annotated action, and must contain at least five clearly observed torso frames in a stable neutral orientation. The tool checks distinct performance/video/FBX identities, hashes, valid windows, and the researcher's independent-reference attestation. It cannot establish matching or reference independence from filenames alone.

```sh
python tools/validation_pipeline.py verify study/trials.json
python tools/validation_pipeline.py score study/trials.json --output study/scores
python tools/validate_motion.py study/scores/paired_scores.csv --output study/primary
```

The scorer supports the observed 60 FPS Rokoko Mixamo, 30 FPS Newton, and 25 FPS Blender skeleton layouts. An unseen skeleton or ambiguous bone mapping is rejected until its adapter is audited. It samples each FBX on its declared native clock and linearly maps each annotated action to 101 phases. For each file, it fits **one constant camera rotation and scale from torso landmarks** over the declared calibration interval. Shoulder-centred coordinates use a fixed median shoulder-width scale. There is no per-frame camera refit or nonlinear time warp in the primary score. Both methods use the exact same reference frames; short reference gaps at most 0.15 seconds are interpolated, longer gaps are missing. At least 80% of phases must show both wrists and shoulders. All trials must pass QC before a paired score table is written.

`study/scores/paired_scores.csv` has one row per **independent performance**: `performance_id,action_id,performer_id,reference_id,metric,suit_error,non_suit_error`. The metric is `wrist_position_error_2d_normalized`: mean Euclidean left/right wrist distance to the reference over shared visible phases, in reference shoulder widths. `qc.json` records file hashes, calibration transforms and residuals, coverage, native FPS, durations and raw-time duration errors. `traces/*.csv` contains phase-by-phase reference and method coordinates/errors; `traces/*.svg` overlays their wrist paths for visual review. Review at least one complete matched trial's overlay before batch inference; inspect flagged calibrations and occlusions for every trial.

`study/primary/primary_lmem.json` reports the geometric mean suit/non-suit error ratio, two-sided 95% interval, one-sided upper bound, random-effect variances, and fit warnings. A ratio below 1 favours the suit. The paired log error ratio is modelled with crossed action and performer random intercepts. The `superiority_supported` field requires an upper one-sided 95% bound below 1; `meaningful_improvement_supported` requires it below 0.80. The 20% threshold is a **provisional study margin**: justify and lock it before the held-out test. A non-converged or unreliable fit does not support a positive claim. Frames are never model rows. A single-performer study cannot support generality across performers.

## Pilot, secondary analysis, and reporting

Start with 8–10 diverse actions, repeated across performers, to confirm matching, axes, video visibility, calibration, and expected variance. Freeze the reference protocol, thresholds, exclusions, action set, and sample-size calculation before a held-out validation study. Keep held-out performances separate from method tuning. Calculate power from pilot variability and the prespecified target effect; do not treat a planning number as a guaranteed sample size.

```sh
python tools/validation_pipeline.py power study/pilot/scores/paired_scores.csv \
  --actions 8 16 32 48 --performers 3 --repetitions 3 \
  --assumed-true-reduction 0.30 --meaningful-threshold 0.20 \
  --simulations 100 \
  --output study/pilot/power.json
```

The assumed true reduction must exceed the meaningful-improvement threshold. If the true reduction is exactly 20%, a one-sided test of **more than 20%** improvement cannot have high power, regardless of sample size.

```sh
python tools/validation_pipeline.py floa study/scores --output study/floa.json
python tools/validation_pipeline.py spm1d study/scores --output study/spm1d.json
python tools/validation_pipeline.py dtw study/scores --output study/dtw.json
```

Functional limits of agreement are action-specific signed image-plane residual curves, with pointwise bias and 1.96-SD limits. Bootstrap intervals resample whole performer clusters, retaining repeated performances together. They describe bias and spread; they are not a superiority test. SPM1D tests paired, performer-averaged error curves within a homologous action, requiring five independent performers and at least 70 consecutive common phase samples. Its phase clusters are exploratory; control multiplicity before making claims across many actions. Neither method pools incomparable actions into a single waveform.

The constrained DTW sensitivity uses **one shared path for both wrists** and limits phase displacement to 10% of the action. It cannot replace the unwarped primary score or original-time duration analysis because time warping can conceal timing errors.

The toolkit currently reports wrist position and action duration. Handshape, face, transition quality, and ISL comprehension **remain separate outcomes** and must not be inferred from these wrist scores. Add each only with a validated reference measurement and mapping. Blinded fluent-ISL evaluation is required for linguistic claims. Report all exclusions, missing/occluded coverage, action and performer counts, confidence intervals, and negative findings alongside any supported improvement.

## Single-performance case study

Use the additive `case-study` command for one matched physical performance. It compares the
original MotionCaptureFBX and oldFBX against estimated video landmarks and reports **statistical
equivalence not established**. It does not run the population LMEM or treat frames as independent
replications. The repository example is `study/trials_torsofree.json`, relative to the repository
root. Its historical score directories remain unchanged.

Install `requirements-validation-video.txt`, then run from the repository root using the Python
that runs your backend (the example below uses the root `.venv`):

```sh
.venv/bin/python backend/tools/validation_pipeline.py extract-video videos/action.mp4 \
  --pose-model study/models/pose_landmarker_full.task \
  --output study/landmarks/action_pose.csv --include-elbows
.venv/bin/python backend/tools/validation_pipeline.py verify study/trials_torsofree.json
.venv/bin/python backend/tools/validation_pipeline.py case-study study/trials_torsofree.json \
  --output study/action_case_report
```

Extraction produces an eight-joint CSV plus `action_pose.metadata.json`. After re-extraction,
update the manifest's landmark hash and `case_study.video_metadata_sha256` using the `hash`
command. Each report must use a fresh output directory. On macOS the MediaPipe native task can
require access to graphics services even with the CPU delegate selected; an abort inside a
restricted environment requires rerunning extraction where those services are available.

The manifest keeps the existing trial schema and adds a top-level `case_study` object:

```json
{
  "video_metadata": "landmarks/action_pose.metadata.json",
  "video_metadata_sha256": "<actual metadata SHA-256>",
  "pose_model": "models/pose_landmarker_full.task",
  "review": {
    "tracking": "sampled",
    "boundaries": "provisional",
    "calibration": "provisional"
  },
  "review_notes": ["Document actual review and remaining measurement limitations."],
  "synchronization": {
    "suit": {"clock_verified": false},
    "non_suit": {"clock_verified": false}
  }
}
```

Only mark a review field `reviewed` after completing that review. Pairing is a human attestation,
not something the program infers. The current pairing field records the user's confirmation in
Codex. Reference tracking was inspected on eight sampled frames; exhaustive reference validation,
source-window correspondence, and the physical playback speed remain unresolved.

For **each** source, a verified synchronization entry uses a reviewed physical event and explicit
clock evidence, for example:

```json
{
  "clock_verified": true,
  "clock_evidence": "<how the source clocks were verified>",
  "event": {
    "description": "<matching physical event>",
    "reviewed": true,
    "video_seconds": 1.0,
    "fbx_seconds": 0.2
  },
  "video_seconds_per_fbx_second": 1.0
}
```

The numeric example is illustrative, not an annotation for ACTION. Mapping uses
`fbx_time = event_fbx + (video_time - event_video) / rate`. A non-unit rate also needs
`rate_evidence` documenting the export or recording-speed change. Do not estimate synchronization
or rate by minimizing the evaluation wrist error. Until both mappings are verified, synchronized
scores and timing-tolerance results remain indeterminate. Duration sensitivity uses the mapped
reference-video clock; it is not physical milliseconds when that video clock is slowed.

The report converts image-normalized coordinates to pixels before shoulder-width normalization.
It measures shoulder-relative 2D position, not whole-body translation or absolute 3D position.
One fixed camera rotation/scale per source is fitted only from torso joints. Multiple initial
orientations expose competing calibrations: solutions within 0.005 shoulder widths of the best
torso RMSE are retained, and target-error spread above 0.01 flags unresolved sensitivity. These
settings are numerical sensitivity diagnostics, not scientifically justified equivalence bounds.
Calibration is modelled as scaled orthographic projection; perspective, tracking uncertainty,
and calibration ambiguity remain limitations. The original skeleton proportions are preserved.

The separately labelled phase-normalized comparison stretches each action to 101 phases, so its
position scores do not measure speed agreement. Both FBXs use the same observed reference samples
for shoulders, wrists, and elbows. Confidence must be at least 0.70; gaps above 0.15 seconds are not
interpolated; at least 80% of phases must observe every target joint. Per-joint mean, median, P95,
signed coordinate bias, and projected elbow-angle errors are reported. Positive
`oldFBX error − MotionCaptureFBX error` favours MotionCaptureFBX; percentage reduction divides by
oldFBX error. Per-fit metrics and score ranges expose uncertainty rather than selecting the camera
that minimizes wrist error.

Outputs are a self-contained `report.html`, `summary.json`, CSV traces, and SVG/PNG plots. The HTML
contains the reference review images, trajectory overlays, position/angle errors, timing diagnostics,
and all provenance. Exploratory position thresholds and timing thresholds describe sensitivity;
no threshold is used to declare equivalence. No p-values or population confidence intervals are
reported. FBX parsing runs in an isolated worker that retains native wrapper owners, writes copied
arrays, then exits without invoking faulty ufbx 0.0.5 destructors; worker faults and timeouts become
validation errors.

### Camera sensitivity diagnostic

The report also applies a fixed frontal, upright-view assumption to both native skeletons. Shoulder direction and world up define the camera; hip aspect ratio and wrist/elbow residuals are not optimized. This diagnostic does not replace torso-calibrated primary scores or establish capture accuracy. Its projected target coordinates are included in trace columns prefixed `frontal_assumption_`.

### Upper-body action shape (case report v3)

The additional `action_shape` section is exploratory. It compares projected
shoulder tilt, torso lean, upper-arm/forearm direction and elbow bending. It
uses unit directions/angles rather than raw segment lengths. Camera fits still
come from torso calibration, so proportions can influence projection. Torso
and shoulder scores are partly in-sample calibration diagnostics.

A single monotone DTW path per FBX uses the mean of four arm-direction angular
residuals, with steps (1,1), (1,2), (2,1) and a ±10% phase band. Intermediate
points are included; both endpoints and every frame are represented. The same
path applies to all body regions and alternative camera fits. Per-video-frame
means give each reference sample equal weight. This explicitly optimizes visible
shape similarity and cannot establish timing accuracy. `action_alignment.csv`
records every match. Original position and synchronized scores remain available.
Projected segments shorter than 0.05 shoulder widths have undefined direction
for scoring. Region scores require 80% common usable reference samples across
both methods and all admitted camera solutions. Missing scores are never zero.

Optional hand model: configure `SIGNSURE_ANALYSIS_HAND_MODEL` (default
`study/models/hand_landmarker.task`). Official model:
https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task
Downloaded model SHA-256 for the October 2026 audit:
`fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1`.
No video leaves the machine. Pose extraction writes a hashed `.upper.npz`
sidecar with all pose landmarks and anatomically associated hand landmarks.
Hand detection uses 0.70 thresholds and missing-hand crop fallback (radius 0.60
reference shoulder widths). Assignment must be unique within 0.35 widths of the
pose wrist and at least 0.10 widths closer than the opposite wrist. Handedness
classification confidence is not used as landmark confidence. Projected finger
segments below 3 pixels are rejected; estimated hand landmarks require review.
Model and source hashes are checked before hand scoring. Hand mappings to
Mixamo chains are provisional, not a claim of anatomical 3D ground truth.

Native finger diagnostics independently measure 15 3D bend-angle excursions
per hand on original FBX frames inside the selected action. The 1° flag means
"effectively fixed bends" and is not an agreement tolerance. More articulation
is not automatically better capture accuracy. Native curves are available in
`finger_animation_traces.csv` and `finger_animation.svg`.

Head/neck and individual spinal joints are explicitly unassessed: video
nose/ears do not correspond directly to FBX head/neck pivots. Torso lean is only
a torso proxy. No complete upper-body accuracy or linguistic accuracy claim is
made. Gloves/occlusion may prevent all finger reference scores, even though
native finger articulation can still be inspected.

Method references: Google's [Hand Landmarker documentation](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker)
and Müller's [DTW tutorial](https://www.audiolabs-erlangen.de/resources/MIR/FMP/C3/C3S2_DTWbasic.html).
