# Making two-phone markerless measurement of upper-body and wrist angles more precise

Scope: how to reduce 2D keypoint noise and bias, mainly for hands and wrists, so the suit-vs-video
single-take equivalence test (±15° RMS) passes more often. Current pipeline: RTMW `rtmw-dw-x-l`
with 5 test-time augmentations (TTA), board-free self-calibration, DLT, 6 Hz Butterworth. Weak
points: side-view hand TTA spread of about 11 px, wrist-angle Monte Carlo SD of 10–21°, and video
reading shoulder elevation 13–24° lower than the suit during arm-raised holds.

Evidence quality: benchmark AP and PCK numbers come from primary papers or official model pages. I
found no controlled study that isolates resolution, frame rate or shutter speed for hand keypoints,
and none that measures the effect of averaging several models. Those points are marked as gaps or
inferences.

## Q1. Which current models give the most accurate 2D hand and wrist keypoints?

### Takeaway
Among open whole-body models, RTMW-l/x at 384×288 is still the most accurate published option on
COCO-WholeBody hands (hand AP 66.3–66.4), ahead of DWPose-l (62.1) and RTMPose-x (59.3). Hand AP is
the lowest of all body parts for every model, and the RTMW authors say this is because hands get
little input resolution. A dedicated hand model such as RTMPose-m hand or HaMeR/WiLoR on a hand crop
is the obvious upgrade path. Sapiens (308 keypoints, ViT up to 1B–2B parameters) is a heavier
candidate with weak hand-specific evidence, and its licence is non-commercial.

### Cited Findings
- **COCO-WholeBody v1.0 val, hand AP / AR:**

  | Model | Input | Hand AP / AR |
  |---|---|---|
  | RTMW-x | 384×288 | 66.4 / 75.5 |
  | RTMW-l | 384×288 | 66.3 / 75.2 |
  | RTMW-x | 256×192 | 61.0 / 71.0 |
  | RTMW-l | 256×192 | 59.8 / 70.1 |
  | RTMW-m | 256×192 | 49.1 / 60.4 |
  | ZoomNAS | 384×288 | 62.5 / 74.0 |
  | DWPose-l | 384×288 | 62.1 / 72.0 |
  | RTMPose-x | 384×288 | 59.3 / 68.7 |
  | ZoomNet | 384×288 | 57.9 / 73.4 |
  | HRNet | 384×288 | 51.6 / 60.4 |

  For comparison, RTMW-x reaches face AP 88.4 and body AP 76.3, so hands are by far the weakest
  part. — [RTMW paper, arXiv 2407.08634 (HTML v1, Table 1)](https://arxiv.org/html/2407.08634v1)
- Going from 256×192 to 384×288 input raises RTMW-l hand AP from 59.8 to 66.3 (+6.5 AP), the largest
  gain of any body part. — [RTMW paper](https://arxiv.org/html/2407.08634v1)
- The RTMW authors give three reasons hands are hard. Hands occupy a small share of the image, so
  input resolution limits accuracy. Fingers and wrists have many degrees of freedom. Point-wise
  losses are dominated by the torso and face. The PAFPN and HEM modules, which raise feature
  resolution, lift hand AP from 56.4 to 59.9 at 256×192. RTMW has no separate hand-crop
  re-inference stage. — [RTMW paper](https://arxiv.org/html/2407.08634v1)
- RTMW is trained on "Cocktail14": 14 public datasets, of which InterHand is the only hand-specific
  one; the others are whole-body, body and face sets. — [RTMW paper](https://arxiv.org/html/2407.08634v1);
  [MMPose RTMPose project README](https://github.com/open-mmlab/mmpose/blob/main/projects/rtmpose/README.md)
- Checkpoint naming: in the MMPose README, the RTMW-l rows link to `rtmw-dw-x-l_simcc-cocktail14_…`
  checkpoints and the RTMW-x rows to `rtmw-x_simcc-cocktail14_…`. So `rtmw-dw-x-l` is RTMW-l (a
  DWPose-style distillation from x into l), not RTMW-x. FLOPs are 17.7 G for RTMW-l and 29.3 G for
  RTMW-x at 384×288. — [MMPose RTMPose README](https://github.com/open-mmlab/mmpose/blob/main/projects/rtmpose/README.md)
- **Dedicated hand model:** RTMPose-m hand (256×256, marked alpha, 2.6 GFLOPs) scores PCK@0.2 81.5
  on COCO-WholeBody-Hand. On the Hand5 combination (COCO-WholeBody-Hand, OneHand10K, FreiHand2d,
  RHD2d, Halpe) it scores PCK@0.2 96.4 and AUC 83.9. The paired hand detector is RTMDet-nano with
  76.0 AP on OneHand10K. — [MMPose RTMPose README](https://github.com/open-mmlab/mmpose/blob/main/projects/rtmpose/README.md)
- **HaMeR** (ViT-H, 3D hand mesh) on the in-the-wild HInt benchmark, PCK@0.05 / 0.1 / 0.15:

  | Subset | All joints | Visible joints | Best prior method (all joints) |
  |---|---|---|---|
  | New Days | 48.0 / 78.0 / 88.8 | 60.8 / 87.9 / 94.4 | MeshGraphormer 16.8 / 42.0 / 59.7 |
  | VISOR | 43.0 / 76.9 / 89.3 | 56.6 / 88.0 / 94.7 | |
  | Ego4D | 38.9 / 71.3 / 84.4 | | |

  HaMeR scores 6.0 mm PA-MPJPE on FreiHAND. — [HaMeR, arXiv 2312.05251 (HTML)](https://arxiv.org/html/2312.05251v1)
- **WiLoR** (CVPR 2025) is a two-stage pipeline: a real-time fully convolutional hand detector that
  also gives handedness, then a transformer that lifts the hand to 3D. It is trained on more than
  2M in-the-wild hand images (the WHIM dataset), and the authors claim it beats prior methods on 2D
  and 3D benchmarks (FreiHAND, HO3D). I could not retrieve its exact 2D PCK table.
  — [WiLoR CVPR 2025 paper](https://openaccess.thecvf.com/content/CVPR2025/papers/Potamias_WiLoR_End-to-end_3D_Hand_Localization_and_Reconstruction_in-the-wild_CVPR_2025_paper.pdf);
  [arXiv 2409.12259](https://arxiv.org/html/2409.12259v1)
- **Sapiens** pose models (0.3B / 0.6B / 1B) predict 308 keypoints, including 40 hand points. The
  checkpoints are selected on Goliath AP at 1024×768-class input and released under CC BY-NC 4.0.
  — [Hugging Face model card, sapiens-pose-1b](https://huggingface.co/facebook/sapiens-pose-1b-torchscript)
- A secondary source says Sapiens-2B beats DWPose-L by +7.1 AP on Humans-5K. I did not verify this in
  the paper. — [LearnOpenCV Sapiens overview](https://learnopencv.com/sapiens-human-vision-models/)
- **Sign language, downstream only:** in a 2026 sign language translation study (O'Brien et al.),
  SDPose and Sapiens gave the best translation, around BLEU 11.5 against about 10 for MediaPipe.
  Estimators that often drop hand keypoints scored lower, and Sapiens handled occlusion best. This
  measures translation quality, not keypoint error.
  — [Evaluation of Pose Estimation Systems for Sign Language Translation, arXiv 2604.24609](https://arxiv.org/pdf/2604.24609);
  [ACL Anthology](https://aclanthology.org/2026.signlang-1.39/)
- **Sign language, qualitative:** a 2023 Ghent study found that MediaPipe Holistic's dedicated hand
  model predicted the distinguishing right-hand keypoints accurately where OpenPose and MMPose were
  noisy. MediaPipe also gave better downstream recognition and ran at 4.8 fps against 1.1 and 1.3
  fps, but it gives no per-keypoint confidence. That MMPose baseline predates RTMW.
  — [Towards robust sign embeddings, arXiv 2306.17558](https://arxiv.org/pdf/2306.17558)

### Inferences
- The pipeline already uses one of the most accurate open whole-body models. Swapping in RTMW-x
  instead of `rtmw-dw-x-l` would barely change hand AP (66.4 vs 66.3). Real gains have to come from
  more pixels on the hand: a dedicated hand stage, higher source resolution, or both.
- HaMeR and WiLoR give a 3D hand mesh per view, which yields a wrist and knuckle geometry with
  anatomical priors. That could stabilise the wrist → knuckle-centroid vector even when individual
  2D knuckles are uncertain. Their 2D keypoints, reprojected from the mesh, are also usable as DLT
  input. HaMeR's ViT-H is heavy, so it would need a GPU or be very slow on CPU. WiLoR is designed to
  run in real time.
- Sapiens is the highest-capacity option, but it is non-commercial, needs about 1024 px input, and
  has no published hand-specific AP that I could find. Treat it as an experiment, not a default.

### Gaps
- No published head-to-head 2D hand-keypoint error (EPE in px or PCK) on sign language footage for
  RTMW, RTMPose-hand, HaMeR, WiLoR, Sapiens and MediaPipe. The sign language papers I found report
  only downstream task metrics.
- Exact WiLoR 2D PCK and Sapiens hand AP numbers were not retrieved.
- The MMPose release notes say RTMW hand accuracy improved in later checkpoints, but no hand-specific
  numbers are published for them.

## Q2. Does a dedicated hand model on a high-resolution hand crop beat whole-body models?

### Takeaway
Probably yes, but no study directly measures it. The best evidence is the resolution sensitivity:
hands gain the most from larger inputs (+6.5 AP from 256×192 to 384×288). Hand-specific models and
hand-specialised heads (ZoomNet and ZoomNAS crop hand regions) report much higher in-domain hand
accuracy. A two-stage hand crop pays off only when the source video actually has pixels on the hand.
At 480p it mostly re-samples the same few pixels.

### Cited Findings
- ZoomNet and ZoomNAS are top-down models with separate hand and face heads that work on zoomed-in
  feature crops. ZoomNAS explicitly searches the hand crop size and feature stage. On COCO-WholeBody
  v1.0 they reach hand AP 57.9 and 62.5 at 384×288, against 51.6 for single-stage HRNet at the same
  input. — [RTMW paper table](https://arxiv.org/html/2407.08634v1);
  [ZoomNAS, arXiv 2208.11547](https://ar5iv.labs.arxiv.org/html/2208.11547)
- ZoomNet ablation (COCO-WholeBody v0.5): joint training of hand features gave hand AP 0.401 against
  0.393 with reused features. A fully independent hand model added two extra models for limited
  gain. — [ZoomNet ECCV 2020 supplement](https://www.ecva.net/papers/eccv_2020/papers_ECCV/papers/123540188-supp.pdf)
- RTMW-x at 384×288 (hand AP 66.4, single stage with high-resolution features) already beats the
  zoom-crop ZoomNAS (62.5). Large-scale data and architecture can outweigh an explicit crop stage.
  — [RTMW paper](https://arxiv.org/html/2407.08634v1)
- Dedicated hand estimators score high on hand-only benchmarks: RTMPose-m hand reaches PCK@0.2 96.4
  on Hand5, and HaMeR reaches PCK@0.1 of 72–78 on in-the-wild HInt against 36–48 for earlier methods.
  These are different metrics and datasets from COCO-WholeBody AP, so the numbers cannot be compared
  directly. — [MMPose README](https://github.com/open-mmlab/mmpose/blob/main/projects/rtmpose/README.md);
  [HaMeR](https://arxiv.org/html/2312.05251v1)
- For low-resolution sign language video, Tasyurek et al. (FG 2024) used fine-tuned U-Net and
  Attention U-Net super-resolution (the best was BWA-UNet). It reduced frames with undetected hands
  and improved hand keypoint accuracy over standard upsampling on low-resolution TV news footage.
  Only the abstract was available. — [Refining Hand Pose Estimation in Low-Resolution Sign Language Videos (FG 2024)](https://avesis.hacettepe.edu.tr/yayin/e0baeb7c-3cf0-44ef-aa53-5f181ad73caf/towards-better-communication-refining-hand-pose-estimation-in-low-resolution-sign-language-videos)
- A community model, "RTMPose-m Distill", is advertised as blur-robust 2D hand keypoints for sign
  language video. It is unvetted, and I found no paper or benchmark for it.
  — [Hugging Face: tasmulaev/rtmpose-m-distill](https://huggingface.co/tasmulaev/rtmpose-m-distill)

### Inferences
- **Why the side-view hand spread is so large, estimated with project numbers.** RTMW resizes the
  whole person box to 384×288. For an upper-body signer, the hand is roughly 10–15% of box height,
  about 40–60 model pixels. At 480p, the native hand may be only about 30–50 px tall. The wrist →
  knuckle-centroid segment is perhaps 15–25 native px. Pointing-direction error is about
  atan(σ⊥ / L), so σ⊥ ≈ 5 px on L ≈ 20 px gives about 14°. This matches the observed 10–21° wrist
  Monte Carlo SD.
  - Each halving of keypoint error, or doubling of segment length in pixels, roughly halves wrist
    angle noise.
  - Wrist angles therefore respond much more to pixels on the hand than to model choice.
- **Recommended crop design**, given the evidence above:
  - Crop around each hand from the whole-body wrist and hand points, at 1.5–2× hand size, from the
    full-resolution frame.
  - Run RTMPose-hand at 256×256, or WiLoR or HaMeR, and replace the 21 hand points, or at least the
    wrist and four MCP points.
  - Compare TTA spread and stillness noise against the current values. This is cheap to test
    because the noise model already exists.
- If the source is 480p, the crop has fewer native pixels than the 256×256 model input. A dedicated
  model may still help, because it has hand-specific priors and training data, but the main fix is
  recording the hands at higher native resolution.

### Gaps
- No study found that compares, on the same footage, whole-body hand keypoints against a two-stage
  hand-crop model's keypoints in pixel error. This should be measured on the project's own takes, for
  example as TTA spread and still-hold SD.

## Q3. How much do resolution, frame rate, shutter speed and camera distance affect hand keypoint error?

### Takeaway
I found no controlled quantitative study for hand keypoints. Indirect evidence:
- Model input resolution is the biggest lever for hand accuracy (Q1).
- Pose estimators miss or degrade hands in low-resolution sign language video.
- Biomechanics labs routinely use fast shutters and 1080p to limit blur.
- Whole-pipeline robustness tests (Pose2Sim) show small angle changes under simulated blur, but for
  large body joints, not hands.

### Cited Findings
- Model input resolution: hand AP rises by 6.5 points from 256×192 to 384×288 for RTMW-l, more than
  any other body part. — [RTMW paper](https://arxiv.org/html/2407.08634v1)
- Low-resolution sign language footage: standard extractors (OpenPose, MediaPipe) often fail to
  detect hands at all. Super-resolution reduced undetected-hand frames.
  — [Tasyurek et al., FG 2024](https://avesis.hacettepe.edu.tr/yayin/e0baeb7c-3cf0-44ef-aa53-5f181ad73caf/towards-better-communication-refining-hand-pose-estimation-in-low-resolution-sign-language-videos)
- The How2Sign dataset paper is cited in search summaries as showing a sharp drop in OpenPose hand
  confidence at low resolution. I did not verify this in the paper.
  — [How2Sign, arXiv 2008.08143](https://arxiv.org/pdf/2008.08143)
- Pose2Sim robustness study: image degradation was simulated with an 11 px Gaussian blur and 0.5
  gamma. Joint-angle mean absolute errors relative to the reference condition stayed between 0.35°
  and 1.6° averaged over joints. That range appears to cover the tested perturbations together; I
  could not retrieve the full text to separate the blur effect. These are whole-body sports
  kinematics, not fingers.
  — [Pose2Sim Part 1: Robustness (Univ. of Bath record)](https://researchportal.bath.ac.uk/en/publications/pose2sim-an-end-to-end-workflow-for-3d-markerless-sports-kinemati-2/)
- In the Theia3D vs marker-based gait study, the setup used 8 high-resolution cameras with shutter
  speed "decreased as much as possible" to limit motion blur. The authors suggest blur may explain
  differences in rapid movements, and they list resolution, lighting, shutter speed and capture rate
  as levers. None of these was tested. — [Song et al., J Biomech 2023 (PMC10494994)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10494994)
- A 2D OpenPose study found that the occluded side's hip and knee angles had about double the bias
  SD and limits of agreement of the camera-side joints. Visibility affects error more than other
  factors. — [Examination of 2D frontal and sagittal markerless motion capture, PLoS ONE (PMC10635560)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10635560/)
- Single-camera work reports that a camera perpendicular to the main plane of motion performs best,
  with slightly larger RMSD in fast movements. This source is a conference slide deck.
  — [OHCOW RSI computer-vision slides](https://ohcow.on.ca/wp-content/uploads/2025/02/OCHOW-RSI-Computer-Vision.pdf)

### Inferences
- **Resolution:** COCO-style keypoint error is roughly proportional to object size in pixels. Once a
  hand spans more pixels than the model's input region (about 60+ px), more source resolution adds
  little. Below that, error in body-relative units grows.
  - The 480p front phone is clearly below that threshold for hands, so recording both phones at
    1080p or higher is the cheapest win.
  - 4K helps mainly if the hand is cropped from the full-resolution frame. A whole-body model
    downsamples the person box to 384×288 anyway.
- **Distance:** framing the signer tighter (upper body only, hands always in frame) raises hand pixels
  linearly with zoom. Use optical zoom or a closer camera, not digital zoom.
- **Shutter and frame rate:** ISL hand movements can exceed 1–2 m/s. At a 1/30 s shutter that is 3–7
  cm of blur, roughly the length of the wrist → knuckle segment. A 1/500–1/1000 s shutter with good
  lighting cuts blur below 0.5 cm.
  - 60 fps also improves sync precision and gives the Butterworth filter more samples per
    oscillation.
  - These are physics estimates, not measured keypoint errors.
- **Viewpoint:** the wrist-deviation plane is best seen roughly perpendicular to the palm. The side
  phone often sees the hand edge-on, with knuckles foreshortened, which inflates angular noise. A
  third camera, or a placement chosen to keep the dorsum of the hand visible, is worth considering.

### Gaps
- No quantitative study found of hand keypoint error versus resolution, shutter speed or frame rate.
  It needs an in-house experiment, for example recording the same sign at 480p, 1080p and 4K, and at
  1/60 vs 1/1000 s, then comparing still-hold SD and TTA spread.
- Could not retrieve the Pose2Sim robustness paper's per-condition numbers (MDPI returned 403).

## Q4. Do temporal refiners and filters reduce error without biasing joint angles?

### Takeaway
Learned temporal refiners such as SmoothNet strongly reduce jitter (acceleration error), but they
barely reduce, and sometimes worsen, per-frame position error. They are trained on body motion
datasets, not sign language hands, so they risk flattening fast, meaningful wrist motion. Simple
zero-lag low-pass filtering, which the pipeline already does, plus noise-aware fusion is the safer
choice for an equivalence test.

### Cited Findings
- SmoothNet is a temporal-only refinement network attached after any pose estimator. In the official
  tables, acceleration error falls sharply (AIST++/SPIN: 33.19 → 4.17; 3DPW/VIBE: 23.59 → 7.24),
  while MPJPE changes little (107.17 → 95.21; 84.27 → 83.14). A mirror lists slightly different
  values. — [SmoothNet GitHub](https://github.com/cure-lab/SmoothNet);
  [SmoothNet ECCV 2022 paper](https://www.ecva.net/papers/eccv_2022/papers_ECCV/papers/136650615.pdf)
- The SmoothNet authors say it is hard to optimise precision and smoothness together, and that
  smoothing introduces a "biased error" between the ground truth and the smoothed poses. With an
  already over-smoothed base (TCMR), SmoothNet cannot further reduce MPJPE.
  — [SmoothNet paper, arXiv 2112.13715](https://ar5iv.labs.arxiv.org/html/2112.13715)
- A third-party 2025 comparison on Human3.6M reports SmoothNet at MPJPE 53.91 mm and the lowest
  angle-acceleration error (MPJAE 0.98). A diffusion refiner reached MPJPE 38.91 but with higher
  MPJAE. — [Liu, Waseda 2025](https://www.ams.giti.waseda.ac.jp/data/pdf-files/2025_liu_mt.pdf)

### Inferences
- For a test whose primary statistic is RMS difference after removing systematic offsets, jitter is
  only part of the problem. Wrist noise also includes slowly varying, correlated error from TTA,
  calibration and occlusion, which smoothers do not remove.
- A smoother that lowers RMS by flattening peaks would be biased towards agreement with a suit that is
  itself smooth, which is a validity concern. If any temporal method is added, the Monte Carlo has to
  run the same filter on simulated noise, which the pipeline already does for the Butterworth.
- **Lower-risk temporal improvements:**
  - Confidence-weighted triangulation: down-weight low-score or high-TTA-spread views per joint and
    frame.
  - A per-view one-euro or Kalman filter on 2D hand points before DLT, with cutoffs tuned on still
    holds and checked against a known synthetic trajectory.
  - A cutoff chosen from the residual analysis of the suit signal rather than a fixed 6 Hz. Hand and
    wrist motion in signing may hold power above 6 Hz, so 6 Hz could itself attenuate wrist peaks.
    The cutoff should be checked against the FBX spectrum.
  - These are design suggestions, not published results.

### Gaps
- No study found that tests SmoothNet-type refiners on hand keypoints or sign language, or that
  measures their bias on joint angles against mocap.
- No source found that compares one-euro or Kalman filtering against Butterworth for markerless joint
  angles.

## Q5. Does markerless video systematically underestimate shoulder elevation or abduction?

### Takeaway
The evidence does not show a consistent direction. Two findings point the other way or to no
consistent bias:
- Theia3D shoulder angles were mostly higher than marker-based angles.
- A 2D camera-position study found no consistent directional bias.

What the evidence does consistently show:
- Shoulder abduction or elevation is one of the least accurate markerless angles (MAE 6–21° in a
  pitching study).
- Agreement worsens near the top of the range.
- The root cause is that the shoulder keypoint is not the glenohumeral joint centre, and its skin and
  silhouette location shifts with arm elevation and scapular motion.

The project's 13–24° underestimate during arm-raised holds is in the reported error range. It is most
plausibly a definition offset between keypoint geometry and suit skeleton geometry, and it may change
with arm elevation.

### Cited Findings
- **Pitching from broadcast video (2026):** shoulder abduction was the only clinically relevant metric
  outside its 1° threshold, with MAE 6.2° for the throwing arm and 21.4° for the glove side. The
  authors blame the shoulder joint centre being hidden under soft tissue and clothing, so small
  localisation errors become large abduction errors.
  — [Scalable Injury-Risk Screening in Baseball Pitching, arXiv 2603.04864](https://arxiv.org/pdf/2603.04864)
- **Theia3D vs marker-based shoulder kinematics:** the trajectories had similar patterns, with the
  largest differences near movement inflection points and markerless angles "mostly greater" than
  marker-based. This is the opposite direction to the project's finding.
  — [Single camera markerless with OpenSim IK, upper-limb ADLs (PMC12416023)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12416023/)
  (from the search summary; Theia3D attribution as given there).
- **Single-camera Azure Kinect with OpenSim IK (2025):** about 8° average RMSE for sagittal shoulder
  elevation in upper-limb activities of daily living. — [PMC12416023](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12416023/)
- **MediaPipe smartphone shoulder abduction (Sensors 2023):** 10 volunteers, 10–160° abduction
  against a goniometer. Raw MediaPipe angles were inaccurate enough that the authors trained an ML
  correction on goniometer ground truth.
  — [Measurement of Shoulder Abduction Angle with Posture Estimation AI (PMC10416158)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10416158/)
- **Glenohumeral osteoarthritis study:** markerless abduction and flexion agreed less with
  marker-based models as angles neared the maximum functional range.
  — [AAOS 2026 abstract](https://index.mirasmart.com/AAOS2026/PDFfiles/AAOS2026-008260.pdf)
- **HumanTrak:** valid shoulder flexion, extension and abduction only when the movement stays in one
  plane and the spine is assumed neutral.
  — [Macquarie University record](https://researchers.mq.edu.au/en/publications/accurate-shoulder-angles-can-be-detected-in-single-plane-motions-/)
- **Anatomical zero for shoulder pose:** how the zero position is defined during bilateral arm
  abduction materially changes the reported shoulder angles. Definition choices drive offsets.
  — [Definition of anatomical zero positions, PMC4673792](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4673792/)
- **Lower-body Theia3D:** RMSE 7.8° ± 2.6°, with some biases attributed to joint-centre definition
  differences between systems; hip flexion offsets came from differing pelvis definitions.
  — [Song et al. 2023, PMC10494994](https://pmc.ncbi.nlm.nih.gov/articles/PMC10494994)

### Inferences
- **Likely mechanism for the project's arm-raised underestimate.** COCO "shoulder" keypoints sit on
  the visible lateral shoulder contour. When the arm is raised:
  - the deltoid bulges and the scapula and clavicle elevate and upwardly rotate;
  - the visible shoulder point rides up and medially;
  - the shoulder → elbow vector becomes less steep relative to the trunk, so elevation is
    underestimated.

  The Rokoko skeleton instead has a rigid upper-arm bone from a fixed shoulder joint, plus a separate
  clavicle bone. This would give an elevation-dependent offset: near zero at rest, growing with
  elevation. The pre-sign-hold offset rule, measured with the arms down, cannot remove that. This is
  a hypothesis consistent with the direction of errors in the pitching paper; no source measures it
  directly.
- **Practical mitigations,** all to be pre-registered before any new take:
  1. Define elevation from a trunk-anchored shoulder centre, for example the midpoint between the
     shoulder keypoint and a point a fixed fraction down the trunk. This approximates the
     glenohumeral centre the way OpenCap and Pose2Sim marker-augmentation do.
  2. Estimate an elevation-dependent offset from a calibration movement (slow arm raise)
     rather than a single static offset.
  3. Report shoulder elevation over the sign window separately for low and high elevation.
- OpenCap's LSTM marker augmenter, which predicts anatomical markers from video keypoints, exists to
  correct exactly this kind of keypoint-to-anatomy mismatch. I did not retrieve its shoulder
  validation numbers in this session.

### Gaps
- No source found that gives a signed, quantified bias of markerless humerothoracic elevation against
  marker-based capture as a function of elevation angle.
- OpenCap upper-extremity validation numbers were not retrieved.
- The Perek et al. 2026 2D humerothoracic camera-position study was seen only as a snippet, without
  numeric bias.

## Q6. Does ensembling several models' keypoints reduce variance?

### Takeaway
I found no published study that measures multi-model 2D keypoint ensembling for joint-angle accuracy.
The general logic of variance reduction applies, but the gain depends on how correlated the models'
errors are. Models from the same family (RTMW, DWPose, RTMPose) share training data and probably
make correlated errors. Multi-view geometric fusion and test-time augmentation are the established,
already-used forms of ensembling.

### Cited Findings
- RTMW, DWPose and RTMPose share architecture lineage (RTMPose, SimCC) and training data
  (COCO-WholeBody, UBody, Halpe and others). DWPose is a distillation of RTMPose. Their errors are
  therefore unlikely to be independent.
  — [RTMW paper](https://arxiv.org/html/2407.08634v1);
  [MMPose RTMPose README](https://github.com/open-mmlab/mmpose/blob/main/projects/rtmpose/README.md)
- Architecturally different hand models (HaMeR: ViT-H mesh regression; WiLoR: detector plus
  transformer; MediaPipe: lightweight landmark regressor; Sapiens: 1B-parameter ViT) come from
  different design families. — [HaMeR](https://arxiv.org/html/2312.05251v1);
  [WiLoR](https://openaccess.thecvf.com/content/CVPR2025/papers/Potamias_WiLoR_End-to-end_3D_Hand_Localization_and_Reconstruction_in-the-wild_CVPR_2025_paper.pdf);
  [Ghent 2023](https://arxiv.org/pdf/2306.17558)

### Inferences
- Averaging n models with error SD σ and pairwise correlation ρ gives an SD of
  σ·sqrt(ρ + (1−ρ)/n).
  - With ρ ≈ 0.7 (same family), three models cut SD by only about 10%.
  - With ρ ≈ 0.3 (different families), they cut it by about 35%.
  - Ensembling a whole-body model with a structurally different hand model (RTMW plus WiLoR or HaMeR)
    is therefore more promising than adding more RTMW variants or TTA modes.
- **Weight by measured noise, not equally.** Use each model's per-joint stillness SD from the existing
  noise model and inverse-variance weights. Reject frames where models disagree by more than a
  threshold, which also flags occlusion.
- The current 5-way TTA spread (~11 px for side-view hands) is a precision estimate. TTA does not
  reduce bias shared across augmentations. A second model family gives an independent bias check,
  which may matter more for the equivalence claim.
- Any ensemble changes the measurement method. It must be fixed and documented before analysing a
  new take, under the project's pre-registration rule, and the Monte Carlo noise model must be
  re-estimated for it.

### Gaps
- No empirical study found on multi-model keypoint averaging for biomechanical angles. It should be
  evaluated in-house on still holds (SD) and on synthetic and real takes against the suit.

## Summary of options, ranked by expected wrist-angle gain per effort (inference)

1. **Recording protocol (largest, cheapest):**
   - Both phones at ≥1080p and 60 fps, with a fast shutter (about 1/500 s or faster) and bright
     light.
   - Tighter framing so each hand spans ≥80–100 native px.
   - Side phone placed so the back of the hand is not seen edge-on.
2. **Two-stage hand refinement:** crop each hand from the full-resolution frame and run RTMPose-m
   hand (cheap, CPU-friendly) or WiLoR or HaMeR (GPU). Use the refined wrist and MCP points for the
   wrist angle.
3. **Confidence and noise-weighted triangulation and cross-model fusion:** combine RTMW with a hand
   model from a different family.
4. **Shoulder elevation definition fix:**
   - Use a glenohumeral-centre approximation for the shoulder point.
   - Calibrate offsets from a slow arm raise rather than a static hold.
   - Pre-register both before any new take.
5. **Temporal methods:** keep a zero-lag low-pass filter whose cutoff is checked against the suit
   spectrum. Avoid learned smoothers such as SmoothNet for the confirmatory analysis, because they
   reduce jitter much more than position error and add smoothing bias.
