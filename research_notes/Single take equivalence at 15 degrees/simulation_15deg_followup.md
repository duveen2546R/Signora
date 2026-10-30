# Single-take conditional equivalence at ±15°: follow-up simulation (motion-only noise, negative offset)

This follow-up was run on 2026-10-29, 16:51–16:59, using the project's own code. It follows `simulation_15deg.md` in this folder (called [earlier notes] below). Sources are local files, cited by path:
- **[pipeline]** `backend/app/validation/conditional_equivalence.py` (`evaluate_conditional`). This is the working tree, which includes the uncommitted adaptive-threshold fix to `still_mask` (lines 114–120).
- **[simulator]** `backend/app/validation/single_take_simulation.py`. This is the working tree, which includes the uncommitted fix that makes `motion_noise_factor` apply only while the arm moves (lines 154–159). The simulator also contains `inject_flexion` (lines 75–94).
- **[driver]** `/private/tmp/claude-501/-Users-duveen-Projects-SignSure/535f702a-3ddb-4287-9769-f86cfb7bfc0f/scratchpad/sim15_followup.py`. This is a copy of the earlier `sim15.py` with three scenarios added and nothing else changed. It is not in the repo, and no repository file was modified.
- **[fu-data]** `/private/tmp/claude-501/-Users-duveen-Projects-SignSure/535f702a-3ddb-4287-9769-f86cfb7bfc0f/scratchpad/out_fu/*.jsonl`, with 125 rows (one JSON line per take).
- **[old-data]** `/private/tmp/claude-501/-Users-duveen-Projects-SignSure/535f702a-3ddb-4287-9769-f86cfb7bfc0f/scratchpad/out/*.jsonl`, the earlier run, used here for paired comparisons on the same seeds.
- The scratchpad is temporary. Copy the files above if they need to be kept.

## Setup and commands

### Takeaway
I ran five scenarios of the right elbow, 25 seeds each (seeds 0–24), through the full `evaluate_conditional` pipeline at a 15° margin. Settings were otherwise identical to the earlier run, so each take is paired seed-for-seed with the earlier `null n3.0`, `null n4.5`, `const+15 n3.0` and `const+15 n4.5` rows.

### Cited Findings
- **Fixed settings** — [driver]:
  - Margins `{'left_elbow_flexion': 15.0, 'right_elbow_flexion': 15.0}`, `claim="rms"`, `draws=200`, `calibration_refits=40`, `replicates=5`, no separate noise recording.
  - Simulation seed `10_000 + seed`, pipeline seed `seed`.
  - Base `Scenario(noise_px=3.0, joint_offset_m=0.0, hold_s=1.0)`, other fields at their defaults.
- **Scenarios** — [driver] `scenario_table`:
  - `null n3.0 motion1.5`: 3 px while still, 4.5 px while moving.
  - `null n3.0 motion2.0`: 3 px while still, 6 px while moving.
  - `const+15 n3.0 motion1.5`: `injected={'right': 15.0}`.
  - `const-15 n3.0`: `injected={'right': -15.0}`.
  - `const-15 n4.5`: as above, at a uniform 4.5 px.
- **Motion-only noise.** The fixed simulator scales noise by `motion_noise_factor` only for video frames whose truth time is strictly between `hold_s` and `motion.times[-1] - hold_s`. Elsewhere the factor is 1.0 — [simulator] lines 154–159.
- **Commands.** Run from `/Users/duveen/Projects/SignSure/backend` with `PYTHONPATH=. OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1`. The launcher `/private/tmp/claude-501/-Users-duveen-Projects-SignSure/535f702a-3ddb-4287-9769-f86cfb7bfc0f/scratchpad/run_followup.sh` started 5 processes in parallel, one per scenario:
  ```
  ../.venv/bin/python <scratchpad>/sim15_followup.py --scenario "const-15 n3.0" --seeds 25 --output <scratchpad>/out_fu/constm15_n3p0.jsonl
  ...   (same for the other four scenarios)
  ../.venv/bin/python <scratchpad>/sim15_followup.py --summary <scratchpad>/out_fu/*.jsonl
  ```
- **Runtime.** Wall clock was 16:51:31 to 16:59:13, 7.7 minutes. The median was 17.1 s per evaluation with 5 jobs running at once — [fu-data] `secs`.

### Inferences
- **Precision of 25 takes.** With 25 takes, 0/25 gives a two-sided 95% Clopper–Pearson upper bound of about 13.7% on the true rate. Rates of about 50–65% carry roughly ±20% uncertainty.

### Gaps
- The same limits as before apply: one motion (`action.fbx`), the right elbow only, and one camera geometry.

## Results table (right elbow, margin 15°, 25 takes each)

### Takeaway
- **No refusals.** None of the 125 takes errored.
- **Positive errors.** Motion-only noise caused no false equivalence for a +15° error.
- **Negative offset.** A −15° injected offset gave a true error just inside the margin (mean −13.2°, RMS 14.5°). There, the RMS upper bound **under-covered** the true RMS: 0.72 at 3 px and 0.64 at 4.5 px, against a nominal 0.95. That is a new calibration failure.

### Cited Findings
"Bias" is the median of (observed mean − true mean). Coverage columns are as defined in [earlier notes]: the mean CI is two-sided 90%, and the RMS upper bound (UB) is one-sided 95% — [fu-data].

| scenario | n (errors) | true mean | true RMS | true max | P(EQ) rms | P(EQ) mean | P(EQ) whole_curve | mean-CI cover | RMS-UB cover | median bias | median RMS UB | median band max |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| null n3.0 motion1.5 | 25 (0) | 0.00 | 0.00 | 0.00 | 1.00 | 1.00 | 0.00 | 0.60 | 1.00 | +3.73 | 9.2 | 33.2 |
| null n3.0 motion2.0 | 25 (0) | 0.00 | 0.00 | 0.00 | 0.96 | 1.00 | 0.00 | 0.24 | 1.00 | +5.24 | 11.3 | 37.5 |
| **const+15 n3.0 motion1.5** (type I) | 25 (0) | 14.79 | 14.87 | 15.53 | **0.00** | **0.00** | **0.00** | 0.48 | 1.00 | +4.09 | 22.2 | 44.1 |
| **const−15 n3.0** | 25 (0) | −13.23 | 14.47 | 15.01 | 0.52 | 0.52 | 0.00 | 0.88 | **0.72** | +2.04 | 15.0 | 39.9 |
| **const−15 n4.5** | 25 (0) | −13.23 | 14.47 | 15.01 | 0.64 | 0.48 | 0.00 | 0.76 | **0.64** | +3.44 | 14.6 | 51.5 |

**Decision breakdowns** — [fu-data]:
- **null motion1.5.** RMS 25 EQUIVALENT. Mean 25 EQUIVALENT. Curve 25 INCONCLUSIVE.
- **null motion2.0.** RMS 24 EQUIVALENT, 1 INCONCLUSIVE. Mean 25 EQUIVALENT. Curve 23 INCONCLUSIVE, 2 NOT EQUIVALENT.
- **const+15 motion1.5.** RMS 14 INCONCLUSIVE, 11 NOT EQUIVALENT. Mean 13 INCONCLUSIVE, 12 NOT EQUIVALENT. Curve 21 NOT EQUIVALENT, 4 INCONCLUSIVE.
- **const−15 n3.0.** RMS 13 EQUIVALENT, 12 INCONCLUSIVE. Mean 13 EQUIVALENT, 12 INCONCLUSIVE. Curve 22 INCONCLUSIVE, 3 NOT EQUIVALENT.
- **const−15 n4.5.** RMS 16 EQUIVALENT, 9 INCONCLUSIVE. Mean 12 EQUIVALENT, 13 INCONCLUSIVE. Curve 22 INCONCLUSIVE, 3 NOT EQUIVALENT.

**Other observations** — [fu-data]:
- **Replicate gate.** It never changed the RMS decision: "rms gated" equals "rms" in all 125 takes. The replicate spm1d check passed 0/125.
- **Direction of mean-CI misses.** Every miss had the truth *below* the CI, never above. The counts were 10 (motion1.5), 19 (motion2.0), 13 (const+15 motion1.5), 3 (const−15 n3.0) and 6 (const−15 n4.5).
- **Errors.** The stderr log `/private/tmp/claude-501/-Users-duveen-Projects-SignSure/535f702a-3ddb-4287-9769-f86cfb7bfc0f/scratchpad/out_fu/errors.log` is empty, and no row has an `error` field.

### Inferences
- **No claim gave a false EQUIVALENT at a true +15° error under motion-only noise** (0/25 each). The 95% upper bound is about 14%.
- **The −15° EQUIVALENT decisions are technically correct but sit next to a coverage failure.** The true mean (−13.23°) and true RMS (14.47°) were both inside ±15°, so none of those EQUIVALENT calls is a false equivalence. The concern is the coverage failure, analysed in the negative-offset section below.

### Gaps
- Each scenario has 25 seeds, so the 0.52 / 0.64 / 0.48 pass rates and the 0.72 / 0.64 coverage figures carry about ±20% uncertainty.

## Motion-only noise (noise elevated while moving, base noise in the holds)

### Takeaway
The real "moving-only" assumption is worse for calibration than the uniform noise the earlier rows actually tested. The noise estimate taken from the holds stays at the 3 px level, so the mean CI under-covers badly: 0.60 at motion 1.5× and 0.24 at 2.0×. This compares with 0.93 for 3 px and 0.80 for 4.5 px uniform noise in the earlier run. The RMS bound stayed safe (coverage 1.00, type I 0/25), and the RMS claim kept 96–100% power with no true difference.

### Cited Findings
**The noise estimate does not see the motion noise.** The per-take measurement SD range (`sd_range`, seed 0) was:
- 3.51–6.59 under motion 1.5×;
- 3.48–6.63 under motion 2.0×;
- 3.52–6.45 for the earlier uniform 3 px run;
- 4.58–8.10 for uniform 4.5 px.

So the estimate tracks the 3 px holds, not the noise during the sign — [fu-data], [old-data].

**Paired against the same seeds at uniform 3 px** (median per-seed change, new minus old), the bias grows with the noise during motion — [fu-data] vs [old-data] `null_n3p0.jsonl`:

| change | motion 1.5× | motion 2.0× |
|---|---|---|
| observed mean | +1.41° | +2.98° |
| observed RMS | +2.11° | +4.22° |
| RMS UB | +2.27° | +4.25° |
| band max | +4.99° | +10.11° |
| mean-CI width | 4.25 → 4.53° | 4.25 → 4.45° |

The CI barely widens because its noise input is unchanged.

**Paired against uniform 4.5 px on the same seeds** (`null_n4p5.jsonl`), motion 1.5× gives:
- a similar bias (observed mean −0.47° vs 4.5 px);
- a narrower mean CI (5.56 → 4.53°);
- a lower RMS UB (−0.99°);

That combination is why its mean-CI coverage (0.60) is worse than uniform 4.5 px (0.80) — [fu-data], [old-data].

**A true +15° error under motion 1.5×** — [fu-data]:
- median observed mean 18.88°, observed RMS 20.07°;
- median RMS UB 22.2°;
- mean-CI coverage 0.48, with all 13 misses having the truth below the CI;
- RMS-UB coverage 1.00.

### Inferences
- **The RMS bound survives because the bias works in its favour.** Under positive or null truth, noise-induced positive bias raises the observed RMS. So the RMS UB stays conservative even though the noise estimate is too small. This protection depends on the sign of the bias relative to the error, as the negative-offset section shows.
- **The mean claim stays conservative only by luck of direction.** Its CI is centred too high (by +3.7° / +5.2°) and is too narrow. For positive or null truth that pushes towards INCONCLUSIVE or NOT EQUIVALENT rather than towards false equivalence, but the CI is not a valid 90% interval.
- **The replicate check did not flag motion-only noise.** It never changed a decision, so it gave no protection here. The replicate spm1d check was 0% everywhere at ≥ 3 px, so it cannot tell this case apart.

### Gaps
- Motion-only noise combined with a **negative** offset was not run, because it was outside the requested scenarios. That is likely the worst case, since the bias there is largest (+5.2° at 2.0×) and the CIs are narrowest.

## Negative offset (−15° injected): is the mean claim or the RMS claim falsely passed?

### Takeaway
An injected −15° does not produce a true −15° error: the true mean is only −13.23° (RMS 14.47°, max 15.01°). This run therefore tested a truth just inside the margin, not at it, and no false equivalence was possible by construction. Even so, it exposed two problems:
- The positive bias is confirmed for negative offsets (+2.0° at 3 px, +3.4° at 4.5 px).
- More importantly, the RMS upper bound **under-covers** (0.72 / 0.64 vs nominal 0.95), because the bias shrinks the magnitude of a negative error. The earlier claim that the RMS bound is "conservative in every scenario" holds only for positive or zero errors.

### Cited Findings
**Why the truth is not −15°.** `inject_flexion` rotates the forearm about the elbow by `delta_deg`, and flexion is an unsigned angle between the segments — [simulator] lines 75–94. Where the arm's base flexion is below 15°, a −15° rotation passes through full extension. The flexion then "folds" back up, so the realised error is smaller in magnitude. The truth was the same for every seed:
- true mean −13.23°;
- true RMS 14.47°;
- true max |error| 15.01°.

That compares with +14.79 / 14.87 / 15.53 for +15° — [fu-data], [old-data].

**Bias** — [fu-data]:

| | 3 px | 4.5 px |
|---|---|---|
| median observed − true mean (−15° offset) | +2.04° (SD 0.94) | +3.44° (SD 1.37) |
| same seeds with a +15° offset (earlier run) | +2.59° | +4.35° |
| median observed mean | −11.19° | −9.79° |
| median observed RMS | 13.23° | 12.57° |

The bias is slightly smaller for the negative offset, so it is not a pure additive constant. The observed RMS is well below the true 14.47°.

**Mean claim** — [fu-data]:
- P(EQ) was 0.52 (13/25) at 3 px and 0.48 (12/25) at 4.5 px.
- Mean-CI coverage was 0.88 and 0.76, with all misses having the truth below the CI. The median CI was [−14.86, −10.59] at 3 px and [−15.00, −9.38] at 4.5 px.
- The lower CI limits of the EQUIVALENT takes ranged from −14.86 to −12.89° at 3 px and from −14.97 to −10.94° at 4.5 px.

**RMS claim** — [fu-data]:
- P(EQ) was 0.52 (13/25) at 3 px and 0.64 (16/25) at 4.5 px.
- RMS-UB coverage was 0.72 at 3 px (7 of 25 takes had a UB below the true 14.47°) and 0.64 at 4.5 px (9 of 25).
- The median RMS UB was 14.99° at 3 px and 14.59° at 4.5 px.
- More noise gave *more* RMS EQUIVALENT decisions (0.52 → 0.64) and a *lower* UB, the opposite of the positive-offset case.
- Paired on the same seeds, the RMS UB was 5.05° lower (3 px) and 8.77° lower (4.5 px) than for +15°, although the true RMS differs by only 0.4°.

**Whole-curve claim.** P(EQ) was 0/50 across both noise levels. The median band maximum was 39.9° and 51.5° — [fu-data].

### Inferences
- **The earlier hypothesis is supported in direction.** The mean and RMS evidence are both pulled towards zero for negative errors, so negative errors near the margin are the failure mode. The size of the effect cannot be read directly from this run, because the truth was 1.8° (mean) and 0.5° (RMS) inside the margin.
- **A rough translation-invariance extrapolation**, assuming the observed distribution would shift by the same amount if the truth were exactly at the margin (this is not validated, and the bias is level-dependent):
  - Mean claim: a true mean of −15° would be declared EQUIVALENT whenever the current lower CI limit is above −13.23°. That happened in 3/25 takes at 3 px and 6/25 at 4.5 px, about 12% and 24%.
  - RMS claim: a true RMS of 15° would be falsely passed whenever the current UB is below 14.47°, which is exactly the coverage misses. That is 7/25 (28%) at 3 px and 9/25 (36%) at 4.5 px.
  - Both estimates are well above the 5% nominal rate. They are an indication, not a measurement.
- **The RMS claim is the bigger concern, not the mean claim.** The RMS claim is the recommended primary claim at 15° (see [earlier notes]), and its bound "keeps the noise in" only in the sense of adding variance. A systematic positive bias in measured flexion lowers |observed error| whenever the true error is negative, and the Monte Carlo draws do not reproduce that bias.
- **The likely mechanism** is noise inflating the measured flexion angle (angle nonlinearity), as hypothesised in [earlier notes]. This run does not isolate it.

### Gaps
- **A true type-I test at the margin for negative errors was not run.** It would need an injection of about −17° so that the realised true mean is −15°, or a separate run that targets true RMS = 15°. It was not run because no extra scenarios were to be started. It is the most important next step.
- Whether the bias depends on the base flexion level (it is smaller for −15° than for +15°) was not characterised.
- The left elbow was not tested, and neither were other signs, in which the arm may spend less or more time near full extension.

## Errors and the stillness-detection fix

### Takeaway
There were 0 errors in 125 takes. These scenarios exercise the adaptive `still_mask` threshold only weakly. Under motion-only noise the holds keep 3 px, so refusals were not expected, and uniform 4.5 px had no refusals before the fix either. The fix's main target (1 s holds at 6 px uniform noise) remains unconfirmed by a full Monte Carlo run.

### Cited Findings
- **This run.** No row carries an `error` field, and `errors.log` is empty — [fu-data].
- **Earlier run.** The old `null n3.0 motion2.0` (then effectively uniform 6 px) refused 13/30 takes at `hold_s=1.0`. The new motion-only `null n3.0 motion2.0` refused 0/25 — [old-data], [fu-data].
- **Run order.** All runs started at 16:51, after both fixes had landed: `conditional_equivalence.py` was modified at 16:38 and `single_take_simulation.py` at 16:49 (file timestamps).

### Inferences
- **The drop in refusals has two explanations here.** In the motion2.0 scenario it is explained by the simulator fix, since the holds are now quiet, independently of the `still_mask` fix. The two effects cannot be separated in this run.

### Gaps
- `null n6.0` at `hold_s=1.0` was not re-run with the fixed `still_mask`, because it was out of scope for this follow-up.

## Caveats

### Takeaway
These results are small-sample (25 seeds), cover a single motion and elbow, and use a −15° scenario that did not realise a −15° truth. The negative-offset conclusions are therefore directional.

### Cited Findings
- The sample is 25 seeds per scenario (seeds 0–24), with draws = 200 and calibration refits = 40, the same as the earlier run — [driver].
- The −15° injection realised a true mean of −13.23° and a true RMS of 14.47° because of the fold-back at full extension — [fu-data], [simulator] `inject_flexion`.

### Inferences
- **Recommended next runs**, in priority order:
  1. Negative injection calibrated to a true mean of −15°, and separately to a true RMS of 15°, at 3 and 4.5 px.
  2. The same with motion-only noise (motion 1.5×).
  3. A bias correction or bias-aware Monte Carlo in the pipeline, then re-checking RMS-UB coverage for negative errors.

### Gaps
- No pipeline change was attempted; this study only measures behaviour.
