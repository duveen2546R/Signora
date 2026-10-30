# Single-take conditional equivalence at a ±15° margin: in-house simulation results

All evidence here comes from simulations run on 2026-10-29 with the project's own code. Sources are local files, cited by path:
- Pipeline: `backend/app/validation/conditional_equivalence.py` (`evaluate_conditional`), referred to below as [pipeline].
- Simulator: `backend/app/validation/single_take_simulation.py` (`Scenario`, `simulate`), referred to as [simulator].
- Driver (written for this study, not in the repo): `/private/tmp/claude-501/-Users-duveen-Projects-SignSure/535f702a-3ddb-4287-9769-f86cfb7bfc0f/scratchpad/sim15.py`, adapted from `backend/tools/simulate_conditional_equivalence.py`; referred to as [driver].
- Raw output, one JSON line per take: `/private/tmp/claude-501/-Users-duveen-Projects-SignSure/535f702a-3ddb-4287-9769-f86cfb7bfc0f/scratchpad/out/*.jsonl` (590 rows); referred to as [sim-data]. The summary table is in `.../scratchpad/summary.md`. The scratchpad is temporary, so copy these files if they need to be kept.

## Setup: what was simulated and how

### Takeaway
There were 17 scenarios of the right elbow, each run through the full `evaluate_conditional` pipeline at a 15° margin on the `action.fbx` motion. Most scenarios had 40 seeds (20–30 for a few). Every number below is a share of simulated takes.

### Cited Findings
- **Fixed settings.** Margins were `{'left_elbow_flexion': 15.0, 'right_elbow_flexion': 15.0}`, with `claim="rms"`, `draws=200`, `calibration_refits=40`, `replicates=5`, no separate noise recording (noise was estimated from the holds before and after the sign), simulation seed `10_000 + seed`, and pipeline seed `seed`. The base `Scenario` was `noise_px=3.0, joint_offset_m=0.0, hold_s=1.0` with all other fields at their defaults: oblique 35°, 5% focal error, AR(1) jitter 0.7, 2% dropout, replicate noise fraction 0.5 — [driver], [simulator].
- **Decisions recorded.** All three per-angle decisions (`rms_decision`, `mean_decision`, `curve_decision`) are returned on every call, whatever `claim` is set to. `claim` only selects which decision is gated by the replicate check, so "rms gated" below is the final RMS decision after that check — [pipeline] lines 395–431.
- **Injected errors.**
  - Constant offsets: +8°, +11°, +15°.
  - Sine: amplitude 15·√2 over the sign window, so true RMS ≈ 15° and true mean ≈ 0.
  - Bump: a Gaussian centred mid-window with σ = 8% of the window and a 15° peak. After filtering, the true maximum was 14.96°, the true RMS 5.65° and the true mean 3.0° — [driver], [sim-data].
- **Truth and coverage.** Truth is `SimulatedTake.true_difference(window)`: video-truth minus FBX, filtered the way the pipeline filters — [simulator].
  - "mean-CI cover" is the share of takes where the true mean lies inside `mean_ci_deg`. That interval is two-sided 90%, since alpha = 0.05 per tail.
  - "RMS-UB cover" is the share of takes where true RMS ≤ `rms_ci_deg[1]`. That is a one-sided 95% bound — [pipeline] lines 255–270.
- **Commands.** Everything was run from `/Users/duveen/Projects/SignSure/backend` with `PYTHONPATH=.` and `OMP_NUM_THREADS=OPENBLAS_NUM_THREADS=VECLIB_MAXIMUM_THREADS=1`, one process per scenario, 8 at a time (the machine has 8 cores):
  ```
  ../.venv/bin/python <scratchpad>/sim15.py --scenario "null n3.0" --seeds 40 --output <scratchpad>/out/null_n3p0.jsonl
  ../.venv/bin/python <scratchpad>/sim15.py --summary <scratchpad>/out/*.jsonl
  ```
  Launchers: `<scratchpad>/run_all.sh` (13 base scenarios, 40 seeds), `run_batch2.sh` (6 px, motion 2.0 and their `hold2.0` variants, 30/25 seeds) and `run_batch3.sh` (0.5 and 1.0 px null, 20 seeds). A scenario name with the suffix `" holdX"` reuses that scenario with `hold_s=X` — [driver].
- **Runtime.** Wall clock was 16:07:49 to 16:40:24, about 33 minutes. One evaluation took 10.6 s on an idle core and a median 23 s with 8 running at once — [sim-data] `secs` field.

### Inferences
- With 40 takes, an observed 0/40 gives a 95% Clopper–Pearson upper bound of about 8.8% on the true rate, and 1/40 gives about 13%. These runs can rule out gross type-I inflation but cannot confirm a 5% rate precisely.

### Gaps
- Only one motion (`action.fbx`), one elbow (right) and one camera geometry (35° oblique, 3 m) were tested. Results may not carry over to other signs or setups.

## Results table (right elbow, margin 15°)

### Takeaway
At 15°, RMS is the only claim that is both achievable at realistic noise and protected against cancelling errors. Mean is always achievable but blind to sign-alternating errors. Whole-curve is safe but needs ≤ about 1 px of noise.

### Cited Findings
P(EQ) = share of completed takes declared EQUIVALENT. Refused takes (pipeline error, see the stillness-bug section) are counted separately and never yield EQUIVALENT — [sim-data], [driver] `--summary`.

| scenario | n | true mean | true RMS | true max | P(EQ) rms | P(EQ) rms gated | P(EQ) mean | P(EQ) curve | mean-CI cover | RMS-UB cover | median RMS UB | median band max | replicate spm1d pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| null n0.5 | 20 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.95 | 1.00 | 1.00 | 1.9 | 12.4 | 0.95 |
| null n1.0 | 20 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.55 | 1.00 | 1.00 | 2.6 | 14.9 | 0.95 |
| null n1.5 | 40 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.10 | 0.97 | 1.00 | 3.6 | 17.9 | 0.72 |
| null n3.0 | 40 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.93 | 1.00 | 7.1 | 28.6 | 0.00 |
| null n4.5 | 40 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.80 | 1.00 | 10.6 | 39.6 | 0.00 |
| null n6.0 (hold 1.0 s) | 17 (+13 refused) | 0.00 | 0.00 | 0.00 | 0.82 | 0.82 | 1.00 | 0.00 | 0.47 | 1.00 | 13.0 | 55.8 | 0.00 |
| null n6.0 hold2.0 | 25 | 0.00 | 0.00 | 0.00 | 0.80 | 0.80 | 1.00 | 0.00 | 0.28 | 1.00 | 14.4 | 46.8 | 0.00 |
| null n3.0 motion1.5 | 40 | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.80 | 1.00 | 10.6 | 39.6 | 0.00 |
| null n3.0 motion2.0 (hold 1.0 s) | 17 (+13 refused) | 0.00 | 0.00 | 0.00 | 0.82 | 0.82 | 1.00 | 0.00 | 0.47 | 1.00 | 13.0 | 55.8 | 0.00 |
| null n3.0 motion2.0 hold2.0 | 25 | 0.00 | 0.00 | 0.00 | 0.80 | 0.80 | 1.00 | 0.00 | 0.28 | 1.00 | 14.4 | 46.8 | 0.00 |
| null n3.0 offset 1 cm | 40 | 0.76 | 3.51 | 8.14 | 0.93 | 0.93 | 1.00 | 0.00 | 0.75 | 0.97 | 8.3 | 32.3 | 0.00 |
| const+8 n3.0 | 40 | 7.85 | 7.94 | 8.32 | 0.93 | 0.93 | 1.00 | 0.00 | 0.90 | 1.00 | 13.5 | 35.6 | 0.00 |
| const+11 n3.0 | 40 | 10.82 | 10.91 | 11.42 | 0.05 | 0.05 | 0.93 | 0.00 | 0.85 | 1.00 | 16.3 | 38.2 | 0.00 |
| **const+15 n3.0** (type I) | 40 | 14.79 | 14.87 | 15.53 | **0.00** | 0.00 | **0.00** | **0.00** | 0.88 | 1.00 | 20.1 | 42.4 | 0.00 |
| **const+15 n4.5** (type I) | 40 | 14.79 | 14.87 | 15.53 | **0.00** | 0.00 | **0.00** | **0.00** | 0.68 | 1.00 | 23.2 | 51.2 | 0.00 |
| **sine RMS 15 n3.0** (type I for rms) | 40 | -0.08 | 14.99 | 21.22 | **0.03** (1/40) | 0.03 | 1.00 | 0.00 | 0.90 | 0.97 | 17.5 | 41.5 | 0.00 |
| **bump peak 15 n3.0** (type I for curve) | 40 | 3.01 | 5.65 | 14.96 | 1.00 | 1.00 | 1.00 | **0.00** | 0.88 | 1.00 | 11.1 | 32.4 | 0.00 |

Breakdown of decisions — [sim-data]:
- **const+15 n3.0.** RMS: 38 INCONCLUSIVE, 2 NOT EQUIVALENT. Mean: 36 INCONCLUSIVE, 4 NOT EQUIVALENT. Curve: 33 INCONCLUSIVE, 7 NOT EQUIVALENT.
- **const+15 n4.5.** RMS: 33 INCONCLUSIVE, 7 NOT EQUIVALENT. Mean: 28 INCONCLUSIVE, 12 NOT EQUIVALENT. Curve: 23 INCONCLUSIVE, 17 NOT EQUIVALENT.
- **sine.** Curve was NOT EQUIVALENT in 22 of 40 takes. The one RMS EQUIVALENT (seed 33) had true RMS 14.99° and RMS CI [8.37, 14.47]. True RMS was 0.01° inside the margin, so the decision was technically correct.
- **bump.** Curve: 38 INCONCLUSIVE, 1 NOT EQUIVALENT.
- **null n0.5.** Curve: 19 EQUIVALENT and 1 NOT EQUIVALENT, a false difference with no true error.
- **null n1.0.** Curve: 11 EQUIVALENT, 9 INCONCLUSIVE.
- **The replicate gate never changed the RMS decision.** "rms gated" equals "rms" in every row.

### Inferences
- **False equivalence (type I) at 15°**:
  - RMS: 0/80 at a constant +15° (3.0 and 4.5 px) and 1/40 for the sine, which was technically correct as described above.
  - Mean: 0/80 at a constant +15°.
  - Whole-curve: 0/40 for the bump and 0/80 for the constant.
  - No claim showed type-I inflation, and the 95% upper bound per scenario is about 9%.
- **Power with no true difference**:
  - RMS: 100% from 0.5 to 4.5 px, 93% with a 1 cm skeleton offset, and about 80% at 6 px. Its median upper bound grows roughly linearly with noise, about 2.4° per px: 3.6° at 1.5 px, 7.1 at 3, 10.6 at 4.5, 14.4 at 6 (hold 2 s).
  - Mean: 100% at every noise level tested.
  - Whole-curve: 95% at 0.5 px, 55% at 1.0, 10% at 1.5, 0% at ≥ 3 px.
- **Truth inside the margin (3 px)**:
  - RMS: 93% at +8° but only 5% at +11°. Its upper bound of about truth + 5.4° limits it to cases where true RMS is under about 9–10° at 3 px.
  - Mean: 100% at +8° and 93% at +11°.
- **Mean claim and cancelling errors.** The mean claim passed 100% of sine takes where the true RMS was 15° and the peak 21°. This is the same weakness as at 5°: on its own it cannot protect against errors that cancel out.
- **RMS and localized errors.** The RMS claim passed 100% of bump takes with a 15° peak, because the bump's true RMS is only 5.65°. This is correct for an RMS claim, but it means RMS equivalence at 15° says nothing about the local maximum error.

### Gaps
- No negative-offset type-I run (−15°) was done. Because of the mean bias described below, that run is needed before the mean claim can be called safe.

## At what noise level does each claim become achievable at ±15°?

### Takeaway
- **RMS:** achievable up to about 4.5 px (100%), still about 80% at 6 px.
- **Mean:** achievable at every noise level tested (up to 6 px).
- **Whole-curve:** only at ≤ about 1 px (55% at 1.0 px, 95% at 0.5 px). It is never passable at the realistic 3 px.

### Cited Findings
- The median whole-curve band maximum was 12.4° at 0.5 px, 14.9° at 1.0, 17.9° at 1.5, 28.6° at 3.0, 39.6° at 4.5, and 46.8–55.8° at 6.0. The margin is crossed between 1.0 and 1.5 px — [sim-data].
- The replicate spm1d TOST (the independent whole-curve check) passed 95% at 0.5–1.0 px, 72% at 1.5 px, and 0% at ≥ 3 px — [sim-data].
- With no true difference, RMS power was 1.00 at noise ≤ 4.5 px. At 6 px it was 0.82 over completed 1 s-hold takes, but 13 of 30 takes were refused, so the effective rate was 14/30. With 2 s holds it was 0.80 (20/25, no refusals) — [sim-data].

### Inferences
- **Whole-curve.** At the 5° margin the band was never passable (band maximum ±17–38°). At 15° it becomes passable only when keypoint noise is about 1 px or less. Realistic phone pose estimation (about 3 px) gives bands of about ±29°, so at ±15° the whole-curve claim stays out of reach in practice.
- **RMS.** Compared with 5° (96% at 1.5 px, 0% at 3 px), 15° moves RMS power to 100% at 3 and 4.5 px. That makes RMS the claim that works at realistic noise.

### Gaps
- The 1.0 and 0.5 px estimates rest on 20 seeds each, so the 55% figure has roughly ±22% 95% uncertainty.

## Calibration: CI coverage, bias and the skeleton offset

### Takeaway
The RMS upper bound is conservative (coverage 0.97–1.00 against a nominal 0.95). The mean CI under-covers as noise rises, because the observed mean difference is biased positive by an amount that grows with noise and that the Monte Carlo error model does not fully reproduce.

### Cited Findings
- **Mean CI coverage**, nominal 0.90 two-sided — [sim-data]:
  - 1.00 at 0.5–1.0 px, 0.97 at 1.5, 0.93 at 3.0, 0.80 at 4.5.
  - At 6 px: 0.47 over the 1 s-hold takes that completed, 0.28 with 2 s holds.
  - With a constant +15° offset: 0.88 at 3 px and 0.68 at 4.5 px.
- **Where the misses fall.** Except for the offset scenario, every miss had the truth below the CI, so the CI sat too high. Examples: 13/40 below and 0 above for const+15 at 4.5 px; 18/25 below for 6 px with 2 s holds — [sim-data].
- **Size of the bias.** The median of (observed mean − true mean) was +0.21° at 0.5 px, +0.55 at 1.0, +0.88 at 1.5, +2.5 at 3.0, +4.4 at 4.5, and +6.0 / +7.1 at 6 px (1 s / 2 s holds). The between-take SD was 0.2–1.8°. The bias is the same with and without injected offsets — [sim-data].
- **Skeleton offset.** A 1 cm random joint offset (`joint_offset_m=0.01`) produced true mean 0.76°, true RMS 3.51° and true max 8.1°. RMS power dropped to 93% (3/40 INCONCLUSIVE). Mean-CI coverage was 0.75, with misses on both sides (5 and 5). RMS-UB coverage was 0.97 — [sim-data].

### Inferences
- **Why the CI sits high.** The positive bias makes the measured elbow flexion read larger than the truth. This looks like noise inflating the measured angle. The CI is centred on the biased estimate, and the Monte Carlo draws evidently under-reproduce the bias, so the CI sits too high.
- **Positive offsets are conservative.** The CI's upper end is further above +15° than it should be, so the bias makes positive offsets look worse and pushes towards not declaring equivalence. That is why the type-I rate stayed at 0.
- **Negative offsets are the risk.** A true −15° offset would be read at about −12.5° (3 px) or −10.6° (4.5 px), which could produce false EQUIVALENT decisions on the mean claim. The same applies to an RMS that the bias offsets. This was not simulated and is the most important follow-up.
- **The RMS claim keeps its protection.** Its upper bound deliberately keeps the noise in, per the pipeline comment at lines 262–266, and its coverage stayed at 0.97–1.00 in every scenario.

### Gaps
- The source of the positive bias (angle nonlinearity under keypoint noise versus calibration-refit bias) was not isolated.

## Stillness-detection bug at high noise (6 px, motion factor 2.0)

### Takeaway
With 1 s holds, 13/30 takes at 6 px effective noise were refused with "Need at least 1.0 s of stillness in every view". This was a pipeline bug, which the coordinator has since fixed in `still_mask`. With the fix, the `hold_s=1.0` versions of these high-noise scenarios would no longer error.

### Cited Findings
- **Refusals in this study.** In both `null n6.0` and `null n3.0 motion2.0` at `hold_s=1.0`, 13 of 30 seeds (0, 2, 6, 7, 9, 14, 19, 20, 23, 24, 25, 28, 29) raised a `ValidationError` from `estimate_keypoint_noise`. With `hold_s=2.0` there were 0/25 refusals — [sim-data], [pipeline] lines 141–151.
- **The bug, as reported by the coordinator.** The fixed limit of 0.35 shoulder-widths/s split genuine holds into fragments once jitter speed reached about 0.3–0.4. The fix in `still_mask` raises the limit to 2× the take's 10th-percentile speed, capped at 0.25× its 95th percentile, and comes with a regression test. The uncommitted diff is in `backend/app/validation/conditional_equivalence.py` (+7 lines) and `backend/tests/test_conditional_equivalence.py` (+9 lines) — [pipeline] working tree, `git diff`, file modified 16:38.
- **Check of the fix.** I re-simulated all 13 previously refused seeds for both scenarios (`replicates=0`, same simulation seeds) and ran the fixed `still_mask` and `estimate_keypoint_noise`. All 13/13 were accepted in each scenario. This check took 2 s; the full Monte Carlo was not re-run.
- **Which results the fix could change.** The fix's adaptive floor is above 0.35 (so the limit changes) in 0/20 views at 1.5 px and at 3.0 px, 10/20 views at 4.5 px, and 20/20 views at 6.0 px. Median floor values were 0.12, 0.24, 0.35 and 0.46. This was measured on 10 seeds × 2 views per noise level.

### Inferences
- **All runs used the old `still_mask`.** Every simulation process started (16:07 and 16:27) before the fix landed (16:38).
  - The 0.5–3.0 px scenarios are unaffected, because their limit stays at 0.35. That covers the null, offset, +8/+11/+15 and sine/bump runs at 3 px.
  - The 4.5 px rows (null n4.5, motion 1.5, const+15 n4.5) may shift slightly under the fix, because about half the views would get more still frames.
  - The 6 px 1 s-hold rows are both pre-fix and selection-biased, since the refused takes were dropped. The `hold2.0` rows remain valid as the 6 px reference.
- **Unconfirmed after the fix.** The 6 px figures (about 80% RMS power, 0.28 mean coverage) should be re-confirmed with the fixed code at `hold_s=1.0`. This was not done, per the instruction not to start new long runs.

### Gaps
- Decisions at 6 px and 4.5 px under the fixed `still_mask` were not measured.

## Simulator caveat: motion_noise_factor

### Takeaway
In the current simulator, `motion_noise_factor` multiplies detector noise on every frame, holds included. So "noise 3.0 × motion 1.5" is the same as noise 4.5 px, and "× 2.0" the same as 6 px. These scenarios do not test the case where noise is larger while moving than while still.

### Cited Findings
- `simulate()` builds `moving = lambda source: np.full(len(source), scenario.motion_noise_factor)`, a constant over the whole take including the holds, and passes it as `noise_scale` to `_film` — [simulator] lines 154–157.
- Per seed, `null n4.5` and `null n3.0 motion1.5` matched to a maximum difference of 2e-4° in the RMS upper bound across 40 seeds, and the 6 px and motion-2.0 rows (and their `hold2.0` variants) are identical — [sim-data].

### Inferences
- **Moving-only noise is untested.** In that case the hold-based noise estimate would understate the error during the sign, which is the situation the replicate check is meant to catch. The motion-noise rows here say nothing about that case.

### Gaps
- No scenario modelled noise that is elevated only while moving, because the simulator does not support it. Testing that would need a change to `simulate()`.
