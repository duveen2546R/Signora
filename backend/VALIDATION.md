# Independent motion validation

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
