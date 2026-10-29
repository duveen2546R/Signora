# Pose-estimator keypoint noise: measurement and modelling assumptions (RTMW/DWPose)

Scope: whether the SignSure noise model holds up. The model takes still-pose σ at its 95% upper confidence bound plus AR(1), then a TTA spread lower bound, then max(still, TTA) in a Monte Carlo. The question is how large keypoint error and jitter are for modern whole-body estimators during fast upper-limb and hand motion.

Search notes: the Consensus MCP was rate-limited at first, then returned only 3 results per query. Two key PDFs (arXiv 2303.04566 and the PDF of 2604.24609) were unreadable as raw PDF, so the HTML version of 2604.24609 was used instead. All numbers below come from fetched pages or search abstracts. Items without a source are listed under Gaps.

## Q1. Reported localisation error and jitter of RTMPose/RTMW/DWPose/MediaPipe/OpenPose/ViTPose keypoints, especially wrists and hands, static vs dynamic

### Takeaway
Hands are by far the weakest part of whole-body estimators. On COCO-WholeBody, RTMW-x reaches only about 66 hand AP, against roughly 70 whole-body AP. Published jitter numbers are almost all from moving (signing) video and use acceleration or jerk metrics, not pixel σ. I found no peer-reviewed static noise floor in pixels for RTMW or DWPose.

### Cited Findings
- On COCO-WholeBody, RTMW-x (384×288) scores 70.2 whole-body AP and 66.4 hand AP. The same table lists DWPose-l at 62.1 hand AP and RTMPose-m (256×192) at 47.5 hand AP. — [RTMW paper, arXiv 2407.08634](https://arxiv.org/pdf/2407.08634)
- DWPose distillation raises RTMPose-l whole-body AP from 64.8% to 66.5%. The hand AR reported for DWPose-l differs slightly between the DWPose paper (71.0) and the RTMW paper (72.0), so cross-paper settings are not identical. — [DWPose, arXiv 2307.15880](https://arxiv.org/pdf/2307.15880); [RTMW](https://arxiv.org/pdf/2407.08634)
- MMPose release notes give RTMW-l at 70.1 and RTMW-x at 70.2 whole-body AP (384×288) and say hand accuracy was "notably improved". — [MMPose releases](https://github.com/open-mmlab/mmpose/releases)
- O'Brien, Sant, Müller and Ebling (2026) compared 8 estimators on signing video: MediaPipe Holistic, OpenPose, MMPose Wholebody (RTMPose/DWPose family), OpenPifPaf, SDPose, Sapiens, AlphaPose and SMPLest-X. They reported median per-sequence jitter (×100, all non-leg keypoints, n=20 sequences per dataset).
  - On Signsuisse (higher resolution), Jjerk/Jacc were: MediaPipe 2.46/1.44, OpenPose 6.84/3.97, MMPose Wholebody 8.58/4.95, Sapiens 7.77/4.42 and SDPose 14.97/8.45.
  - On RWTH-PHOENIX (about 5.3× fewer pixels), they were: MMPose Wholebody 14.47/8.75 and OpenPose 26.36/14.74.
  - For hands only on Phoenix, OpenPose Jjerk was 67.74 (highest) and SMPLest-X 7.40.
  - The authors caution that violin plots overlap, so some rankings are unreliable. — [Evaluation of Pose Estimation Systems for Sign Language Translation, arXiv 2604.24609](https://arxiv.org/html/2604.24609)
- In the same study, the share of signing frames with a missing hand was: OpenPifPaf left 67.65% / right 59.19%, MediaPipe 20.22% / 23.61%, OpenPose 8.43% / 3.88%. MMPose Wholebody, AlphaPose, Sapiens, SDPose and SMPLest-X were at 0%, because they never output confidence 0. The top-down models always place a point, so their failures show up as wrong locations, not as missing keypoints. — [arXiv 2604.24609](https://arxiv.org/html/2604.24609)
- On 15 hand-picked occlusion instances, the share of correct poses was: Sapiens 100%, MediaPipe 73.3%, OpenPose 66.7%, SDPose 46.7%, AlphaPose 40.0%, MMPose Wholebody 33.3%, OpenPifPaf 6.7% and SMPLest-X 0%. — [arXiv 2604.24609](https://arxiv.org/html/2604.24609)
- MediaPipe Holistic on the Phoenix train split: the mean per-video fraction of frames with a fully missing hand is 28.6% for the left hand (max 100%) and 23.9% for the right (max 84%). This figure comes from search-snippet level only. — [search result summary of sign-language papers; see arXiv 2604.24609 and related](https://arxiv.org/html/2604.24609)
- A practitioner blog (not peer-reviewed, setup not described) claims raw per-frame keypoints jitter by 3–4 px even when the subject is still. — [Forasoft 2026 guide](https://www.forasoft.com/learn/ai-for-video-engineering/articles-ai/openpose-mediapipe-rtmpose-pose-tracking)
- Biomechanics context:
  - Pose-estimation joint centres (OpenPose, AlphaPose, DeepLabCut, triangulated at 200 Hz) show systematic offsets of about 30–50 mm at hip and knee, attributed to training-label conventions. Where bias was low, as at the ankle, differences were 1–15 mm depending on activity. — [Needham et al. 2021, Sci Rep](https://consensus.app/papers/details/aa33d7bd92135d3fbbb6de2b7237908d/?utm_source=claude_code)
  - Two-webcam OpenPose gait angles had errors up to 14.0° ± 1.8°, falling to 1.6° ± 0.3° when the joint was visible in both cameras throughout. — [D'Antonio et al. 2021, IEEE Sensors J](https://consensus.app/papers/details/5f7f1b3d8dc45222bdcb962e5c6842f7/?utm_source=claude_code)
  - Monocular OpenPose hip and knee errors were 3.7 ± 1.3° and 5.1 ± 2.5° over the gait cycle. — [Washabaugh et al. 2022, Gait & Posture](https://consensus.app/papers/details/7d2c287059d55f45a3dade40b00c17a2/?utm_source=claude_code)

### Inferences
- The observed TTA spread of 3.3–7.5 px per joint, largest at the wrists and index fingers, matches the literature's ranking of hands as the least reliable region. It is the same order of magnitude as the unsourced 3–4 px "still subject" anecdote. Because the 4K video has many pixels per limb, the absolute px values are not directly comparable with low-resolution benchmarks.
- Systematic offsets (Needham) are a separate error component from jitter. A jitter-only Monte Carlo cannot capture bias such as a consistent wrist-keypoint offset from the true joint centre. For elbow angles, bias that is constant across takes may partly cancel in equivalence comparisons, but bias that depends on pose will not.
- MMPose Wholebody (the RTMPose/DWPose lineage) had relatively high jitter and poor occlusion correctness in the 2026 sign-language study. That suggests RTMW-family noise during signing is probably not small compared with alternatives.

### Gaps
- I found no published static (performer-still) per-joint pixel σ for RTMW or DWPose, so the still-σ approach has no literature value to check against.
- I found no per-joint (wrist vs elbow vs index fingertip) pixel RMSE for RTMW on video with ground truth. COCO-WholeBody reports AP by body part (body, foot, face, hand), not per joint.
- The 2604.24609 jitter metrics are normalised (×100) and not in pixels, so they cannot be converted directly into σ_px.

## Q2. Does keypoint error increase with motion speed, motion blur or occlusion?

### Takeaway
Yes, qualitatively and strongly. Motion blur is among the most damaging corruptions for 2D pose models. On COCO-C, AP drops by roughly 40–45% on average, and hand detectors like MediaPipe lose half or more of their hands under blur. Sign-language papers attribute hand failures to fast-movement blur. I found no study that quantifies error as a function of speed in px/frame for RTMW. The literature therefore contradicts the assumption that motion noise is no larger than rest noise, but it does not give the size of the multiplier.

### Cited Findings
- PoseBench (COCO-C, mean across severity levels) compared clean mAP with motion-blur mAP:

  | Model | Clean mAP | Motion-blur mAP | mRR |
  |---|---|---|---|
  | HRNet-W48 | 75.58 | 43.73 | 57.85% |
  | SimCC-Res50 | 72.07 | 38.65 | 53.63% |
  | ViTPose-B | 75.75 | 43.29 | — |
  | ViTPose-H | 78.84 | 46.43 | 58.89% |

  Motion blur and contrast had the most significant impact, and human pose models were "especially vulnerable to compression and blur". The synthetic blur levels may be harsher than real 4K video. — [PoseBench, arXiv 2406.14367](https://arxiv.org/html/2406.14367v1)
- COCO-C, MPII-C and OCHuman-C were introduced to show that pose estimators fail under corruptions, blur included, that humans handle easily. — [Wang et al. CVPR 2021, arXiv 2105.06152](https://arxiv.org/pdf/2105.06152)
- In metamorphic robustness testing of hand pose models, at least 50% of hands could not be identified by MediaPipe Hands under diagonal motion blur. None of the tested models, including OpenPose, was robust to blur, and occlusion, illumination and blur were the main obstacles. — [Robustness Evaluation in Hand Pose Estimation Models using Metamorphic Testing, arXiv 2303.04566](https://arxiv.org/pdf/2303.04566)
- MediaPipe fails to detect more than 50% of hands per frame on WLASL. The authors attribute this to rapid hand movements producing blurry frames. — [Preprocessing MediaPipe Keypoints…, SignLang 2024 (ACL Anthology)](https://aclanthology.org/2024.signlang-1.36.pdf)
- OpenPose fails on hand-to-hand interactions, producing ambiguous shape, distortion or position. Complex hand-to-body interactions are described as a common point of failure. — [Ivashechkin et al., Improving 3D Pose Estimation for Sign Language, SLTAT 2023](https://personalpages.surrey.ac.uk/r.bowden/publications/2023/IvashechkinSLTAT2023.pdf)
- Anecdotally, one tracker fails to track the left wrist of a waving swimmer because of strong blur from rapid arm movement (single video). — [OPPH, arXiv 2408.09409](https://arxiv.org/pdf/2408.09409)
- In 3D hand tracking, accuracy drops considerably for fast-moving hands. This concerns depth sensors, not RGB 2D keypoints. — [3D Hand Tracking in the Presence of Excessive Motion Blur](https://www.researchgate.net/publication/339245659_3D_Hand_Tracking_in_the_Presence_of_Excessive_Motion_Blur)
- Sapiens was noted anecdotally to err on fast movements. There are no quantitative fast-motion results. — [arXiv 2604.24609](https://arxiv.org/html/2604.24609)

### Inferences
- The key untested assumption (motion noise ≤ rest noise) runs against all directional evidence found. The simulated 1.5× scenario, which drops coverage to about 0.73–0.79, should be treated as plausible, not as a pessimistic edge case. For hand and wrist keypoints during fast signing with hand-over-face, multipliers above 1.5× are plausible, given the AP drops and detection-loss rates above. This is extrapolation, since no study gives a px-level multiplier.
- Top-down whole-body models such as RTMW never output "missing". Under blur or occlusion they fail by placing confident but wrong points, which produces heavy-tailed (outlier) errors rather than inflated Gaussian σ. A Gaussian AR(1) model, even with σ scaled up, may under-represent these gross errors.
- Blur depends on shutter speed and frame rate. A 4K capture at high shutter speed may reduce blur, so the actual capture settings matter for which literature regime applies.

### Gaps
- I found no dataset or study that reports RTMW/DWPose 2D error binned by keypoint speed (px/frame) or blur kernel length.
- I found no quantitative error comparison for hand-over-face specifically.

## Q3. Is test-time-augmentation spread a valid (calibrated) uncertainty estimate, or known to underestimate?

### Takeaway
TTA is an established proxy for input-dependent (aleatoric) uncertainty. However, I found no study validating TTA spread against true keypoint error for human pose. Pose confidence itself is known to be miscalibrated, and wrong predictions can receive high confidence. Treating TTA spread as a lower bound, rather than an estimate, is the defensible reading.

### Cited Findings
- TTA using geometric and colour transforms yields useful estimates of input-dependent predictive uncertainty. It was proposed for heteroscedastic aleatoric uncertainty in medical imaging. — [Ayhan & Berens 2018](https://consensus.app/papers/details/976b90c30daf5b7ba6de9036be4cab16/?utm_source=claude_code)
- Wang et al. formalise TTA as Monte Carlo sampling over an image-acquisition model. TTA-based aleatoric uncertainty beat test-time dropout alone and reduced overconfident incorrect predictions in segmentation. — [Wang et al. 2018/2019, Neurocomputing](https://consensus.app/papers/details/d11ce8157137538192afa6fd15be7922/?utm_source=claude_code)
- A general survey notes that deep networks suffer from over- or under-confidence. It treats TTA, ensembles, MC dropout and Bayesian networks as distinct approaches with practical limitations in safety-critical use. — [Gawlikowski et al. 2021/2023, AI Review](https://consensus.app/papers/details/d3c04ef245895ad3bf61e24bf71f2a67/?utm_source=claude_code)
- Gu, Chen and Yao (CVPR 2024) found that pose estimation confidence is "poorly calibrated" with respect to OKS.
  - Keypoint-level Pearson r between confidence and OKS on COCO val is only 0.643 for SimpleBaseline heatmaps (0.718 after the CCNet correction) and 0.700 for RLE (0.782 after).
  - For heatmaps, the confidence at the mean follows l̃²/σ̂², a "scaling gap" that widens when the prediction is imperfect.
  - TTA and MC dropout are not evaluated. — [On the Calibration of Human Pose Estimation, arXiv 2311.17105](https://arxiv.org/html/2311.17105)
- "Due to distribution bias between training and test data, the pose estimation model can give high confidence to very wrong predictions." — [UDF-GMA, arXiv 2507.04814](https://arxiv.org/pdf/2507.04814)
- In online test-time adaptation for 3D pose, the gap between using estimated 2D and ground-truth 2D grows as the number of confident keypoints falls. 2D confidence is used as a proxy for unknown 2D accuracy and is weak on hard cases. — [arXiv 2503.11194](https://arxiv.org/html/2503.11194v1)
- A 2026 preprint notes that scale augmentations in heatmap TTA can push peripheral keypoints out of bounds ("multi-scale heatmap poisoning"). It proposes aggregating distributions instead. — [Human Pose Estimation by Probabilistic Mixtures of Gaussian and Uniform Distributions, arXiv 2610.14093](https://arxiv.org/html/2610.14093)
  - The same preprint separates aleatoric uncertainty (blur, occlusion) from epistemic uncertainty and models keypoints as a Gaussian plus uniform-outlier mixture. That supports heavy-tailed error modelling. Not peer-reviewed. — [same source](https://arxiv.org/html/2610.14093)
- Split and inductive conformal prediction have been used to build calibrated keypoint confidence regions with coverage guarantees, mostly in object pose. — [Deterministic Object Pose Confidence Region Estimation, arXiv 2506.22720](https://arxiv.org/pdf/2506.22720)
- MC dropout (p=0.1, M=50 passes) has been applied to markerless biomechanics keypoint-to-landmark mapping. The snippet does not report whether the uncertainty tracks error. — [arXiv 2603.26844](https://arxiv.org/pdf/2603.26844)

### Inferences
- TTA spread reflects only the sensitivity to the chosen transforms (flip, ±8% scale, ±4% shift). It cannot reflect errors shared by every augmented copy: blur is identical in all copies, occlusion is identical, and label-convention bias is identical. Those errors are perfectly correlated across replicates and therefore invisible to the spread. This is the mechanistic reason TTA should be treated as a lower bound, as the pipeline already assumes. The flip replicate also captures left/right model asymmetry, which may inflate the spread somewhat in a way unrelated to motion.
- Because heatmap or SimCC confidence correlates only moderately with error (r ≈ 0.64–0.78 at keypoint level), it should not be used to rescale σ without calibration on labelled data.

### Gaps
- I found no paper that measures TTA spread against ground-truth keypoint error for 2D human or hand pose, so the degree of underestimation (for example a ratio of TTA σ to true RMSE) is unknown.
- I found no calibration study for RTMW's SimCC confidence specifically.

## Q4. Is temporal autocorrelation of keypoint errors documented? Are AR(1) or similar models used in practice?

### Takeaway
Temporally correlated error is documented. SmoothNet's "long-term jitter" consists of persistent multi-frame errors that low-pass filters cannot remove. Standard toolkits model noise only implicitly, through low-pass, Kalman or One Euro filtering. I found no published use of an explicit AR(1) parameterisation of 2D keypoint error.

### Cited Findings
- SmoothNet splits pose error into jitter between adjacent frames and biased error relative to ground truth. It distinguishes sudden jitters from long-term jitters, which "usually entangle with ambiguous biased errors". Existing low-pass, TCN and RNN smoothers "cannot deal with such a long-term jitter problem without considering the significant and persistent errors within the jittering segment". Smoothness is measured by mean per-joint acceleration error. — [SmoothNet, ECCV 2022, arXiv 2112.13715](https://arxiv.org/pdf/2112.13715)
- OpenCap applies a 4th-order zero-lag Butterworth filter (12 Hz cutoff for gait, 30 Hz otherwise) and fills occluded keypoints with cubic splines, using left-right confidence to detect occlusion. — [OpenCap supplementary (bioRxiv 2022)](https://www.biorxiv.org/content/biorxiv/early/2022/07/10/2022.07.07.499061/DC1/embed/media-1.pdf?download=true)
- Pose2Sim offers Butterworth, Gaussian, LOESS, median, Kalman and (recently) One Euro filters. Its accuracy paper used a 4th-order 6 Hz Butterworth. Triangulation logs report per-keypoint mean reprojection error in mm and px. — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim); [Pose2Sim Part 2: Accuracy](https://www.researchgate.net/publication/359691401_Pose2Sim_An_End-to-End_Workflow_for_3D_Markerless_Sports_Kinematics-Part_2_Accuracy)
- The jitter metrics in sign-language evaluation (Jacc, Jjerk) are second and third differences. They are sensitive to the frequency content of the noise, not only its variance. — [arXiv 2604.24609](https://arxiv.org/html/2604.24609)

### Inferences
- An AR(1) model is a reasonable first-order description and is consistent with the existence of persistent errors. However, SmoothNet's observation implies a mixture: short-correlation jitter plus long, segment-level excursions, typically during hard frames. A single AR(1) ρ estimated at rest will likely underestimate how persistent errors are during motion.
- Persistence matters for the Monte Carlo. With positive autocorrelation, errors average out less over a movement window, so intervals built assuming low ρ will be too narrow.

### Gaps
- I found no paper reporting measured lag-1 autocorrelation of 2D keypoint errors for any detector, static or dynamic.
- I found no published explicit AR(1) noise model in markerless pipelines. Kalman filters in Pose2Sim imply a process and measurement noise model, but I did not locate documented parameter values.

## Q5. Better alternatives for estimating measurement error without ground truth

### Takeaway
The most-used ground-truth-free signals are multi-view triangulation reprojection residuals, which Pose2Sim logs per keypoint in px. Others are cross-model disagreement, conformal calibration on a small labelled subset, and ensemble or MC-dropout variance. All of these except a labelled calibration set share the TTA weakness that errors common to all sources are invisible.

### Cited Findings
- Pose2Sim reports per-keypoint mean reprojection error (px and mm) after triangulation. These residuals act as a per-joint, per-frame error proxy without marker ground truth. — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)
- In OpenPose two-webcam gait work, accuracy depended strongly on visibility in both cameras (1.6° ± 0.3° when visible throughout vs up to 14°). More cameras and optimised triangulation were recommended. — [D'Antonio et al. 2021](https://consensus.app/papers/details/5f7f1b3d8dc45222bdcb962e5c6842f7/?utm_source=claude_code)
- Multi-model comparison on the same signing videos reveals large differences in missing rate, jitter and occlusion correctness across 8 estimators. Inter-model disagreement is therefore informative. — [arXiv 2604.24609](https://arxiv.org/html/2604.24609)
- MEOM (preprint) and ProbPose treat heatmaps as calibrated spatial distributions, with temperature scaling and OKS decoding, for multi-view triangulation. — [MEOM, arXiv 2608.30521](https://arxiv.org/html/2608.30521)
- Conformal prediction gives distribution-free keypoint error bounds once a small labelled calibration set exists. — [arXiv 2506.22720](https://arxiv.org/pdf/2506.22720); [Test-time augmentation improves efficiency in conformal prediction, arXiv 2505.22764](https://arxiv.org/pdf/2505.22764)
- MC dropout is an epistemic alternative to TTA, and Wang et al. found TTA plus dropout better than dropout alone. — [Wang et al., Neurocomputing](https://consensus.app/papers/details/d11ce8157137538192afa6fd15be7922/?utm_source=claude_code)

### Inferences
Ranked by how much each would strengthen the SignSure method:
1. **Labelled calibration set.** Hand-annotate wrist, elbow and shoulder on a few hundred frames of fast signing, including blurred and hand-over-face frames, using the same camera and settings. Then fit σ_motion directly, or conformally calibrate the TTA spread by finding the scale factor k such that k·σ_TTA covers 90% of errors. This directly tests the "motion ≤ rest" assumption.
2. **Second synchronised view and epipolar or reprojection residuals.** These capture errors that TTA cannot, such as occlusion-induced and view-dependent errors. They still miss bias shared across views, such as label-convention offsets.
3. **Cross-model disagreement.** Compare RTMW with Sapiens, ViTPose-WholeBody or MediaPipe as a further lower-bound signal. Model errors are partly independent, but they are correlated on hard frames.
4. **Speed-conditional σ.** Estimate σ as a function of keypoint speed or blur from TTA or multi-view residuals, rather than a single max(still, TTA) scalar. Pair it with a heavy-tailed (Gaussian plus outlier) error model in the Monte Carlo.
5. **Sensitivity analysis instead of point σ.** Given the absence of a literature multiplier, report coverage across a grid of motion/rest ratios (1.0, 1.5, 2.0, 3.0) and outlier rates.

### Gaps
- I found no study that validates epipolar or reprojection residuals as calibrated estimates of 2D keypoint error for hands.
- I found no ground-truth-free method in the literature that is shown to recover errors common to all augmentations, views or models, such as label-convention bias. Only labelled data or marker-based reference addresses that component.
