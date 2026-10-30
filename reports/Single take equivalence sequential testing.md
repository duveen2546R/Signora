# One Angle Should Not Void the Rest — and a Near Miss Is Still a Miss

The single-take protocol used to give one overall verdict. EQUIVALENT required all nine upper-body angles to pass (intersection–union). In both real takes (After and Action), every angle passed except the right wrist, so each whole take was INCONCLUSIVE. Two fixes went in on 2026-10-30.

1. **Fixed-sequence testing** ([Maurer, Hothorn & Lehmacher 1995](https://doi.org/10.1002/bimj.4710370202)) replaces the all-or-nothing verdict.
   - Angles are tested in a pre-registered order:
     1. trunk twist;
     2. shoulder elevation pair;
     3. shoulder abduction pair;
     4. elbow pair;
     5. left wrist;
     6. right wrist.
   - Each test uses the full α = 0.05. A pair must pass on both sides.
   - Testing stops at the first group that does not pass.
   - Every angle confirmed before the stop is claimed with familywise error ≤ 5%. No α splitting is needed. Bonferroni at α/9 would have widened every bound.
   - The overall result is EQUIVALENT, PARTIALLY EQUIVALENT (confirmed angles listed), or the first group's own decision.
2. **A more precise hand point.** The wrist angle used to point from the wrist to the index knuckle alone, 3–4 cm away. It now points to the centre of the four finger knuckles (index to pinky), on both the video (four RTMW hand keypoints) and the FBX (the `Hand*1` bones).

What was **not** done: the margin was not widened, and the wrist was not dropped. A take whose upper bound is 16.1° against a 15° margin really cannot exclude a difference larger than 15°. Calling that a pass would make the test meaningless.

Both changes were chosen after the After and Action takes had been seen. Applied to those two takes they are therefore **exploratory**. They are confirmatory for every later take.

## The bound is not over-conservative, so it stays

Before considering any loosening, the RMS upper bound was checked against known truth.
- **Setup:** synthetic two-view takes with the true suit–video RMS placed exactly at the 15° margin, 100 takes per row.
- **Decision rule, fixed in advance:** recalibrate only if the false-equivalence rate fell below 1%.

| Noise | True error shape | P(EQUIVALENT), RMS claim | RMS-bound coverage | Bound − truth (5th / 50th pct) |
|---|---|---|---|---|
| 3 px | constant +15° from onset | 0.040 | 0.96 | +0.3° / +5.0° |
| 3 px | sine, RMS 15° | 0.050 | 0.95 | +0.2° / +2.6° |
| 4.5 px | constant +15° from onset | 0.010 | 0.99 | +1.8° / +8.3° |
| 4.5 px | sine, RMS 15° | 0.000 | 1.00 | +2.0° / +5.2° |

At realistic noise (3 px) the RMS test sits at its nominal 5% rate. The bound therefore stays unchanged. A sequence of tests that are each at level ≤ 5% keeps the familywise rate ≤ 5%.

The mean claim again passed 99% of the cancelling sine takes, which confirms it should not be primary. Three simulated takes (out of 400) were refused because dropouts left a hold uncovered. They count as not equivalent.

Data: `study/sim_sequential/all.jsonl`. Command: `tools/simulate_conditional_equivalence.py --summary`.

## After: all nine angles equivalent (exploratory)

- **Protocol:** pre-registered pipeline, new rules.
- **Calibration:** baseline 64.8°, reprojection error 4.6 px. The baseline was 56.1° before: wrist-to-hand bone lengths enter the self-calibration, so a new hand point moves the camera solution.
- **Lags:** view −0.155 s, FBX −0.393 s.

| Angle | RMS (upper bound) | Before the change |
|---|---|---|
| Trunk twist | 2.1° (2.8) | 2.0° (2.8) |
| Shoulder elevation L / R | 1.3° (1.7) / 10.0° (10.6) | 1.4° (1.8) / 10.4° (11.0) |
| Shoulder abduction L / R | 1.8° (2.1) / 9.3° (10.1) | 1.8° (2.2) / 6.6° (7.5) |
| Elbow flexion L / R | 1.0° (1.6) / **12.5° (14.4)** | 0.9° (1.5) / 6.0° (8.0) |
| Wrist deviation L / R | 2.9° (5.1) / **9.4° (11.9)** | 5.0° (7.0) / 13.1° (16.1), INCONCLUSIVE |

- **The right wrist now passes because its measurement became more precise, not because anything was loosened.** Its Monte Carlo standard deviation fell from 14.4° to 9.9° (to 69% of before; the target was ≤ 60%). Replicate pose spread on the side-view hand point fell from 12.2 px to 11.4 px.
- **The right elbow got worse**, from an upper bound of 8.0° to 14.4°, close to the margin. This comes through the calibration shift, not the elbow itself. Results this sensitive to calibration are a reason for caution.
- **The right shoulder elevation still reads about 13–15° low** while the arm is held up, as before.

## Action: only trunk twist confirmed (exploratory)

- **Protocol.** Action has no still hold before the sign, so the pre-registered protocol refuses it. The run used the exploratory variant: offsets taken from 0.8 s of the post-sign hold, and the focal length fixed at the nominal value.
- **Result: PARTIALLY EQUIVALENT.** Trunk twist is confirmed. Testing stopped at the shoulder-elevation pair.
- **Why it stopped there.** Left shoulder elevation's RMS upper bound is 14.8°, just inside the margin. But its replicate check fails, and the video reads 20–24° lower than the suit for 42% of the sign. That is a real, sustained disagreement, not noise. This is the fixed sequence working as intended: a doubtful early angle blocks the later claims.
- **Angles that would have passed but were not tested in sequence:**
  - shoulder abduction (2.7° and 3.5° upper bounds);
  - elbows (6.9° and 11.1°).

  They cannot be claimed.
- **Wrists:**
  - left wrist: NOT EQUIVALENT, 20.8° RMS (upper bound 24.8°);
  - right wrist: INCONCLUSIVE, 19.4° upper bound.

  The side video is 480p, where hand keypoints are only a few pixels across. The knuckle centre helped the right wrist (standard deviation 27.9° → 21.3°) but not the left (11.3° → 15.4°).

## What this means

Fixed-sequence testing removes an unfair rule, not a fair one. A late, hard-to-measure angle can no longer erase well-measured ones. But it is not a way to pass more often: in Action it confirmed *fewer* angles than the old per-angle view would suggest. That happened because an early angle (left shoulder elevation) is genuinely doubtful.

Near misses are handled by measuring better, not by moving the margin. The knuckle centre was enough to bring After's right wrist inside the margin, but not Action's 480p side view.

For confirmatory results, record new takes with:
- a 1–2 s still hold before and after the sign;
- the side phone at 1080p, 60 fps;
- stabilisation off;
- hands visible to the side camera.

Analyse them with the now-locked order and hand point.

Whatever the verdict, a pass shows agreement with the two-phone video for that one take. It is not a claim about suit accuracy in general.
