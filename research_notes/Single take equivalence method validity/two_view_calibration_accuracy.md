# Two-view self-calibration from body keypoints: accuracy for 3D elbow flexion

Context: two uncalibrated phones (front, plus 30–45° oblique, 2–3 m away). Cameras are self-calibrated from RTMW/DWPose keypoints using essential-matrix init, multi-start yaw, reprojection plus bone-length bundle adjustment, and a ±15% focal prior. Then DLT triangulation, a 6 Hz low-pass filter, and the elbow angle from shoulder→elbow and elbow→wrist vectors. In-house simulation recovered yaw within about 2–3°, but the reprojection error landscape was flat and the linearised covariance underestimated yaw error by about 5x.

Search note: the research ran about 15 tool calls. The PMC and ElliPose PDFs could not be read (CAPTCHA, and no PDF text tool). The Frontiers mirror gave the Lahkar numbers. Consensus returned only 3 papers per query on the free tier.

## Q1. Published methods for calibrating from human keypoints, and their accuracy vs checkerboard

### Takeaway
"Human as calibration pattern" is an established research line (2008–2025), but the validated, widely used biomechanics pipelines do not rely on it:
- OpenCap uses a checkerboard.
- Pose2Sim's keypoint calibration was still marked "Coming soon" with no accuracy data.

Published keypoint-calibration results are mostly from computer vision work. They report camera rotation errors of about 0.4–2° (sometimes 13–17° when unsynchronised) and focal errors of about 1–18%. Most use 4 or more cameras and none report joint-angle accuracy against marker-based mocap. I found no peer-reviewed study validating elbow (or any) joint angles from a 2-camera, keypoint-only self-calibrated setup against optical mocap.

### Cited Findings
**Takahashi et al. 2018 (CVPRW)**
- One algorithm uses 2D human joints for synchronisation, camera pose estimation and 3D pose estimation from unsynchronised, uncalibrated multi-view video, aimed at sports scenes. — [Takahashi et al., CVPRW 2018](https://openaccess.thecvf.com/content_cvpr_2018_workshops/w34/html/Takahashi_Human_Pose_As_CVPR_2018_paper.html)
- CasCalib describes Takahashi as estimating sync and extrinsics but **not intrinsics**, and Liu et al. as estimating intrinsics and extrinsics but not sync. CasCalib gives no numbers for either. — [CasCalib, arXiv 2405.06845](https://arxiv.org/html/2405.06845v1)

**CasCalib (FG 2024)**
- Estimates focal length, extrinsics and time offsets from 2D keypoints only, with a cascade of DLT+RANSAC, temporal search, ground-plane ICP and bundle adjustment. Experiments use **4 cameras**. — [CasCalib](https://arxiv.org/html/2405.06845v1)
- The authors state that **two views give too few constraints for bundle adjustment under noisy keypoints**. — [CasCalib](https://arxiv.org/html/2405.06845v1)
- Single-view focal errors were 11.31%, 0.66%, 18.36% and 13.18% on four sequences (about 11% on average). The Fei et al. baseline got 0.35–10.74%. — [CasCalib](https://arxiv.org/html/2405.06845v1)
- On Terrace (synchronised): 138 mm position error and 1.82° rotation error.
  - Unsynchronised at a 50-frame offset: 13.07° rotation error without sync, 2.18° with sync.
  - Human3.6M at a 200-frame offset: 73.04° without sync, 16.89° with sync. — [CasCalib](https://arxiv.org/html/2405.06845v1)
- Failure modes:
  - Periodic motion locks sync onto the wrong minimum.
  - Errors propagate between stages.
  - Focal and sync estimation fail above about 15 px of keypoint noise.
  - Failure rate rises with fewer people in the scene. — [CasCalib](https://arxiv.org/html/2405.06845v1)

**"Humans as a Calibration Pattern" (ICCV 2025)**
- Uses SLAHMR body motion, DTW sync and Procrustes alignment, then joint refinement. Camera rotation error was 5.46° at initialisation and 0.41° after refinement, translation 25.08 cm → 0.22 cm (CMU Panoptic). — [arXiv 2412.19089](https://arxiv.org/html/2412.19089v1)
- It **assumes intrinsics are known** and uses 29–30 cameras, which is far from a 2-camera setup. — [arXiv 2412.19089](https://arxiv.org/html/2412.19089v1)

**Other keypoint-calibration methods**
- Lee et al. 2022 ("Extrinsic Camera Calibration From a Moving Person", IEEE RA-L) lifts 2D poses to oriented 3D joints and solves extrinsics linearly. It requires synced cameras, and the scene is recovered **up to scale**. — [Lee et al. 2022](https://consensus.app/papers/details/f3e995897e6d5a68be6713b9b23c47ad/?utm_source=claude_code)
- Pätzold et al. 2022 does online extrinsic calibration from person keypoints with factor graphs. It **assumes known intrinsics** and a rough initial pose. It reached lower reprojection error than a checkerboard reference calibration, but reprojection error is not 3D accuracy. — [Pätzold et al. 2022](https://consensus.app/papers/details/fd78cf08e3155a8c8bf3510a00f74581/?utm_source=claude_code)
- Tresadern & Reid (2008) self-calibrate from human motion, then refine with full bundle adjustment to estimate segment lengths and joint angles. This is an early precedent for a bone-length-constrained bundle adjustment. — [Tresadern & Reid, IVC 2008](https://digital.library.adelaide.edu.au/items/955ce9ce-d96b-4f7a-8d3a-575568b705f3)
- ElliPose (WACV 2023) jointly estimates 3D pose and cameras for a stereo, smartphone-like setup, relying on constant bone lengths. This is the closest published analogue to the user's method. I could not extract its numbers (PDF unreadable). — [ElliPose, WACV 2023](https://pages.iai.uni-bonn.de/gall_juergen/download/jgall_ellipose_wacv23.pdf)
- Patents also describe this approach: camera pose from minimising joint triangulation error with scale from measured skeleton length ([USPTO 11544872](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11544872)), and bundle-adjustment-like human-motion calibration with limb-length distributions to trigger recalibration ([USPTO 11475595](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11475595)).

**Pose2Sim**
- Keypoint extrinsic calibration (`extrinsics_method = 'keypoints'`) is marked **"Coming soon!"**. It needs synchronised cameras and a subject visible in at least 2 cameras who walks, waves and holds a T-pose. It estimates **extrinsics only**, with intrinsics from a board. No accuracy is reported. — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)
- Pose2Sim's targets for board or scene calibration: extrinsic error below 1 cm ("potentially acceptable up to 2.5 cm") and intrinsic error of about 0.5 px or less. — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)

**OpenCap**
- Calibrates with a checkerboard, not keypoints. Intrinsics come from a pre-computed per-iPhone-model database. Extrinsics come from one image of a checkerboard; an A4-printed 210×175 mm board gave minimal kinematic differences compared with a 720×540 mm board. — [Uhlrich et al., PLOS Comput Biol 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)

### Inferences
- The method is a reasonable synthesis of published ideas: keypoint bundle adjustment as in CasCalib and Takahashi, bone-length constancy as in ElliPose and Tresadern & Reid, and a focal prior. But **two views, with focal length estimated and one small subject, is the hardest and least-validated regime**. CasCalib says two views are under-constrained, and most methods either assume known intrinsics or use 4 or more cameras.
- Reported rotation accuracies of about 0.4–2° come from many-camera or known-intrinsics settings. The in-house 2–3° yaw recovery is in a plausible range but is not backed by a comparable 2-view published benchmark.

### Gaps
- No published numbers found for Takahashi 2018's own calibration accuracy, ElliPose's camera and MPJPE errors, or EasyMocap's or FreeMan's calibration. FreeMan's supplement mentions a "two-stage, pixel-alignment" calibration, but the details were not retrieved. — [FreeMan supplement](https://openaccess.thecvf.com/content/CVPR2024/supplemental/Wang_FreeMan_Towards_Benchmarking_CVPR_2024_supplemental.pdf)
- No study found that compares joint angles from keypoint self-calibration with joint angles from checkerboard calibration of the same recordings.

## Q2. 3D joint-angle accuracy (especially elbow flexion) of few-camera markerless setups vs marker-based mocap

### Takeaway
With **checkerboard-calibrated** cameras, markerless systems typically reach about 4–6° RMSE/MAE across joints (OpenCap with 2 iPhones: 4.5° MAE, mostly lower limb). For elbow flexion specifically, even a 10-camera commercial system (Theia3D) shows about 7° RMSD with a −5 to −6° bias. Upper-limb marker errors are larger than lower-limb ones (OpenCap: 39 vs 27 mm). There is no published 2-smartphone elbow-flexion validation, so elbow RMSE of 5–10° is a realistic expectation before adding any self-calibration error.

### Cited Findings
**OpenCap (Uhlrich et al. 2023), 2 iPhones at ±45°**
- 4.5° MAE across 18 rotational DOFs (range 1.7–10.3°) and 12.3 mm translational error. RMSE was 2.0–10.2° across lower-extremity DOFs. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- Upper-extremity marker error was **39 mm vs 27 mm** for lower extremity. **Elbow and shoulder angles were not evaluated**; the angle evaluation covered pelvis, hips, knees, ankles and lumbar only. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)

**Later OpenCap validations (lower limb)**
- Gait (21 participants, 2 phones): RMSE 5.8° (SD 1.8), peak error 11.3°. These are "above clinically desirable thresholds of two to five degrees". — [Horsak et al., J Biomech 2023](https://consensus.app/papers/details/e9c6da483a905903af8e7053f53a999e/?utm_source=claude_code)
- Return-to-sport tasks (437 trials): 3.85° MAE and 4.34° RMSE. Frontal and transverse plane agreement was poor (CMC 0.47–0.78). — [Turner et al., J Biomech 2024](https://consensus.app/papers/details/9245df4285745451bb5953b029c5e7b1/?utm_source=claude_code)
- Meta-analysis (12 studies): pooled RMSE 5.88°, or 4.94–5.20° after adjustment. Performance varies with task complexity. — [Çabuk et al., Biol Sport 2025](https://consensus.app/papers/details/f59b1304923c517d90baa460ab4de789/?utm_source=claude_code)

**Upper limb**
- Theia3D (10 calibrated Qualisys video cameras) vs markers, boxing:
  - Elbow flexion/extension: RMSD **7.4°** (bias −6.2°, R² 0.99) and **7.0°** (bias −5.4°, R² 0.87).
  - Shoulder flexion: 10° / 7.3°. Shoulder internal/external rotation: 12° / 8.1°.
  - Elbow joint-centre difference: about **3.1 cm**, larger than shoulder (2.3 cm) and wrist (1.8–2.2 cm). — [Lahkar et al., Front Sports Act Living 2022](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2022.939980/full)
- A markerless upper-limb study (10 participants) found ICC >0.91 for the elbow but a **systematic underestimation of maximum flexion**, attributed to occlusion and joint geometry. — [Francia et al., Applied Sciences 2026](https://consensus.app/papers/details/9fabcdafd4645eb7ac96cfb586d2f6b9/?utm_source=claude_code)
- Two Azure Kinects (front, plus side at 2.3 m) met an RMSE ≤8° threshold for most movements **except sagittal elbow flexion**. — [MARS study, PMC12300943](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12300943/)
- Stroke rehab poster with smartphone/tablet markerless capture: elbow flexion-extension MAE 12.23°. This is not peer-reviewed full text. — via [search result, physoc.org](https://www.physoc.org/?p=123540)
- In multi-view upper-limb tracking, triangulation is most accurate when detections are consistent but "degrades rapidly under occlusions or missing keypoints". — [Bajrami et al. 2025](https://consensus.app/papers/details/342a9ce4922c5c72af5b04684310942f/?utm_source=claude_code)

**Pose2Sim (calibrated, lower limb)**
- Mean errors of 3.0°, 4.1° and 4.0° for walking, running and cycling. — [Pagnon et al., Sensors 2022](https://consensus.app/papers/details/8ac7757bd5a556999b15ffdd599152fc/?utm_source=claude_code)

### Inferences
- Elbow flexion error is dominated by the 2D detector's elbow and wrist localisation and by occlusion, not only by calibration. A bias of about −5 to −6° appears even with 10 calibrated cameras, so the pipeline's elbow error floor with perfect calibration is likely around 5–8°.
- Self-calibration error adds on top of this floor. Simple raw-vector elbow angles, with no musculoskeletal model, may be noisier than the OpenSim-IK results reported by OpenCap and Pose2Sim.
- For an equivalence or TOST study, these figures suggest equivalence margins of at least about 5° for elbow flexion are needed even in well-calibrated systems.

### Gaps
- No OpenCap or Pose2Sim peer-reviewed elbow-flexion RMSE vs markers was found. The OpenCap forum mentions an upper-extremity model, but no validation numbers were retrieved.
- No study found on elbow angles from 2 uncalibrated smartphones vs optical mocap.

## Q3. Is two cameras enough? Baseline angle, and the bas-relief / focal-depth ambiguity

### Takeaway
With checkerboard calibration, OpenCap found **2 cameras at ±45° (about 90° apart)** as good as 3–5 for lower-limb kinematics. The user's setup is narrower (30–45° total baseline) and self-calibrated, which removes both of OpenCap's safeguards. Theory and empirical work on focal self-calibration from two views show it is **ill-conditioned**: median focal errors of about 15–25% on real data, with a singularity when the optical axes are near-coplanar. This matches the flat cost landscape seen in the user's simulation.

### Cited Findings
**Number of cameras and placement**
- OpenCap: 3 cameras did not improve accuracy. 5 cameras only mildly reduced marker error (29 vs 32 mm), and kinematics "did not substantially improve when using more than two cameras". — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- OpenCap recommended placement: **about ±45°** from the subject's forward direction for squats and jumps, and about ±30° from the walking direction for walking. Distance 2–10 m, never closer than 2 m. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- Pose2Sim robustness (calibrated): 4 vs 8 cameras gave a 0.90° sagittal error during walking. A 1 cm calibration error gave only 0.19°. Overall mean absolute errors vs the reference condition were 0.35–1.6°. — [Pagnon et al., Sensors 2021](https://consensus.app/papers/details/339cee43060c5ae6a19f3d4368fb9132/?utm_source=claude_code)
- CasCalib: two views give insufficient constraints for bundle adjustment with noisy keypoints. — [CasCalib](https://arxiv.org/html/2405.06845v1)

**Focal-length self-calibration from two views**
- The Bougnoux and related formulas have a generic singularity when the principal axes are coplanar (intersecting), and accuracy degrades significantly even near that configuration.
  - Imaginary focal lengths can occur in more than 20% of noisy samples (citing Kanatani).
  - On real data, median focal errors were 0.197 (Bougnoux) and 0.146 (best method) on Phototourism, and 0.250 / 0.199 on Aachen.
  - A prior-only baseline (f = 1.2 × max image dimension) gave about 0.20 median error, so two-view estimates barely beat a prior. — [Kocur et al., arXiv 2311.16304](https://arxiv.org/html/2311.16304v3)
- Degenerate configurations include one camera's optical axis lying in the plane of the other's, or coplanar axes. With coplanar axes, unique focal lengths cannot be determined. — [Sturm, BMVC 1999 / related](https://bmva-archive.org.uk/bmvc/1999/papers/07.pdf); [Sturm et al., "On Focal Length Calibration from Two Views"](https://hal-univ-tlse3.archives-ouvertes.fr/IMAG/inria-00525660)
- Errors in the principal point significantly distort Bougnoux focal estimates. — [Kocur et al.](https://arxiv.org/html/2311.16304v3)

### Inferences
- Two tripods aimed at the same torso at similar height almost always have **near-coplanar, intersecting optical axes**. This is exactly the focal-length singularity, so the focal length is not identifiable from the data and is effectively set by the ±15% prior.
- The bas-relief ambiguity is general SfM theory and is not sourced here. When the subject has small depth extent relative to distance (a body about 0.5 m deep at 2–3 m) and a small field of view, perspective cues are weak. Rotation angle and depth scale then trade off nearly freely, which explains the flat landscape and why a linearised (Laplace) covariance underestimates error. Bone-length constancy helps only if limb directions vary across frames.
- Practical implication: focal error mostly scales depth and distorts angles of segments pointing toward the cameras. In-plane elbow flexion seen in the front view is relatively robust; out-of-plane flexion is the most sensitive.
- Literature-supported recommendations:
  - (a) Fix intrinsics from a one-off per-phone checkerboard or ChArUco calibration, or a device database as OpenCap does, instead of estimating focal length.
  - (b) Widen the baseline toward OpenCap's about 90° separation.
  - (c) Add a third camera with elevation, or a quick A4 checkerboard capture for extrinsics, if accuracy must be certified.

### Gaps
- I found no peer-reviewed source that quantifies the bas-relief ambiguity specifically for human-keypoint calibration with a small subject. Classic references (Szeliski & Kang 1997; Belhumeur et al. 1999) were not retrieved in this session.
- No study found comparing 30–45° vs 90° baselines for upper-limb angle accuracy.

## Q4. Smartphone video specifics: stabilisation, rolling shutter, unsynchronised clocks, focal uncertainty

### Takeaway
Validated smartphone pipelines manage these explicitly:
- OpenCap fixes focus, uses per-device intrinsics, records 60 Hz, and syncs in software by cross-correlating keypoint velocities.
- Digital stabilisation changes the image geometry frame by frame, which invalidates a single static calibration.
- Unsynchronised cameras badly degrade keypoint-based calibration unless sync is solved first (CasCalib: 13° vs 2° rotation error).

### Cited Findings
- OpenCap recorded 720×1280 at 60 Hz with fixed focus distance. Sync is done in software by cross-correlating keypoint velocities, with no hardware sync. The paper does not discuss video stabilisation. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- Pose2Sim's keypoint calibration requires synchronised cameras; otherwise its separate synchronisation step must run first. — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)
- CasCalib rotation error without vs with sync: 13.07° vs 2.18° (Terrace, 50-frame offset), and 73.04° vs 16.89° (Human3.6M, 200-frame offset). Sync fails on periodic motion. With predicted rather than true focal length, sync error SD rises from about 10 to about 14–15 frames. — [CasCalib](https://arxiv.org/html/2405.06845v1)
- Phone digital stabilisation uses gyroscope-driven warps that correct shake and rolling-shutter distortion. It changes the effective image geometry per frame. — [Karpenko et al., Stanford 2011](https://graphics.stanford.edu/papers/stabilization/); [Hanning et al. 2011](https://users.isy.liu.se/cvl/perfo/abstracts/hanning11.html)
- Rolling shutter exposes rows at different times and warps fast motion. Phone mocap work has built rolling-shutter compensation into tracking filters. — [Pustka et al., ISMAR 2012](https://campar.in.tum.de/pub/pustka2012ismar/pustka2012ismar.pdf)
- Single-phone ARKit body tracking vs Vicon gave weighted MAE 18.80° (range 3.75–47.06°). This shows the scale of error without multi-view geometry. — [Reimer et al. 2022](https://portal.fis.tum.de/en/publications/evaluating-3d-human-motion-capture-on-mobile-devices/)

### Inferences
- **Turn off digital and cinematic stabilisation and lock focus and zoom.** Otherwise the effective focal length and principal point drift, and no static calibration (keypoint or checkerboard) is valid. Some phones change lens or crop when stabilisation is enabled.
- Rolling shutter mostly matters for fast hand and wrist motion in signing. Readout is typically 10–30 ms per frame (an unsourced general figure). At 30–60 fps this is comparable to residual sync error after cross-correlation (sub-frame to about 1 frame) and adds triangulation error at the wrist, which feeds directly into the elbow angle.
- A sync error of Δt with wrist speed v gives an epipolar inconsistency of about v·Δt. For example, at 1 m/s and 16 ms that is about 16 mm, close to OpenCap's total marker error. It also biases the keypoint-based calibration itself.
- A ±15% focal prior is about the same as the real-data median focal error of two-view self-calibration (about 15–25%), so the data adds little beyond the prior. A per-device intrinsic database or a one-off checkerboard calibration reduces focal uncertainty to well under 1%; this is not sourced here, but board calibration routinely reaches 0.5 px or less reprojection, as Pose2Sim's target states.

### Gaps
- I found no source quantifying how inter-camera sync error or rolling shutter propagates into elbow-angle error for smartphone markerless capture.
- I found no source measuring how stabilisation on vs off changes markerless joint-angle accuracy.
