# Calibrating two uncalibrated, unsynchronised phone videos of one person (software only, no re-recording)

Scope: improve the accuracy and stability of the two-view calibration that SignSure uses to triangulate RTMW
keypoints for the 9-angle suit-vs-video equivalence test, using only the existing videos (After, Action) and
code. Labels used below: **[published]** = backed by the cited source; **[in-house]** = my own reasoning or
arithmetic, not taken from a source, and should be checked before relying on it.

Code facts checked in this session (so the report writer need not re-check):
- `backend/app/validation/single_take_job.py:25` uses `DEFAULT_FOCAL_35MM = 28.0` for both cameras, and
  `multiview.py:90-92` converts with the **diagonal** convention `f_px = f35 * hypot(W,H) / hypot(36,24)`.
  For 1920x1080 this gives 1425 px at 28 mm and 1324 px at 26 mm.
- `multiview.py:43` `FOCAL_PRIOR_SD = 0.15` (log scale); bundle adjustment already uses
  `least_squares(..., loss="huber", f_scale=2.0)` (`multiview.py:281-300`).
- `video_replicates.py:106` reads frame time from `cv2.CAP_PROP_POS_MSEC`, i.e. container timestamps rather
  than `index / fps`. Good for the variable-frame-rate 480p files, but OpenCV's POS_MSEC is known to be
  unreliable for some VFR streams in some backends. **[in-house]** It is worth checking it against the true
  per-frame PTS.
- A byte scan of `After-Side.mp4` and `Action--Front.mp4` (the iPhone 17 files) finds QuickTime keys
  `camera.focal_length.35mm_equivalent`, `camera.lens_model`, `camera.lens_irisfnumber`,
  `video-orientation`, two `apple-maker-note` keys (74, 97), and timed-metadata (`mebx`) tracks with
  `detected-face` (bounds, roll and yaw angle), `scene-illuminance` and `live-photo-info`. No intrinsic matrix,
  distortion or stabilisation keys were found. `After-Front.mp4` (480p) has no Apple keys at all.

---

## 1. Human-pose-based camera calibration: accuracy on real data, especially two-view, and which constraints help

### Takeaway
Published person-based calibration methods reach about 2° camera rotation error and 7–14 cm position error,
but only with 4 cameras, walking people, a ground plane, and usually known intrinsics or a person-height
prior. CasCalib states that two views give insufficient constraints for bundle adjustment under noisy keypoints.
Its single-view focal estimates still err by about 11% on average. SignSure's setup (two views, one mostly
stationary signer, upper body only, unknown focals) is outside the regime these methods were validated in.
That makes the focal/baseline instability the expected behaviour, not a bug.

### Cited Findings
- **CasCalib (Tang, Suri, Ajisafe, Wandt, Rhodin; IEEE FG 2024)** fully automates temporal sync and intrinsic
  and extrinsic calibration, using persons in the scene as calibration objects. It runs a cascade:
  1. single-view focal and ground plane by DLT+RANSAC, with the principal point fixed at the image centre;
  2. sync from ankles projected on the ground plane;
  3. 2D rotation search;
  4. ICP;
  5. bundle adjustment over the top-k poses that excludes head and arm keypoints.

  — [CasCalib arXiv 2405.06845](https://arxiv.org/abs/2405.06845); [HTML](https://arxiv.org/html/2405.06845v1)
- CasCalib's assumptions: people stand upright in some frames, have a constant metric height (1.6–1.7 m was
  used), and share a ground plane. In the authors' words, two views were judged insufficient for bundle
  adjustment under noisy keypoints. Detection noise above about 15 px degrades the early stages, and errors
  propagate between stages without recovery. — [CasCalib HTML](https://arxiv.org/html/2405.06845v1)
- CasCalib's single-view focal error averages about 11%, ranging from 0.66% to 18.4% per camera, against
  0.35–10.7% for Fei et al. On EPFL Terrace with sync, rotation and position errors are 2.18° and 0.069 m.
  Synchronised BA on Terrace reaches 138 mm and 1.82°. Human3.6M with a 200-frame offset still leaves
  16.9° and 0.21 m, with a failure case where focal was estimated at 70 vs 209 ground truth.
  — [CasCalib HTML](https://arxiv.org/html/2405.06845v1)
- **Pätzold, Bultmann and Behnke (2022)** do online marker-free extrinsic calibration from person keypoints
  with factor graphs. They *assume known intrinsics* and need a rough initial pose estimate. They report lower
  reprojection error than an offline checkerboard reference after a few minutes of people walking through the
  scene. — [arXiv 2209.07393](https://arxiv.org/abs/2209.07393)
- **Lee, Nishino et al., "Extrinsic Camera Calibration From a Moving Person" (RA-L / IROS 2022)** use 2D and 3D
  pose estimators' outputs as oriented 3D points, solve the extrinsics linearly, optionally refine with bundle
  adjustment, and require synchronised cameras. They recover extrinsics and 3D pose *up to scale*. Error
  numbers were not retrieved in this session. — [IEEE/unpaywall record](https://unpaywall.org/10.1109%2FLRA.2022.3192629);
  [preprint PDF](https://vision.ist.i.kyoto-u.ac.jp/pubs/SLee_RAL22.pdf)
- **Moliner, Huang and Åström (ICPR 2020)** note that pose-estimator keypoints are much less accurate than
  patch-based features and that ambient motion may not suit calibration. They improve extrinsic accuracy with a
  robust reprojection loss built on how pose-estimation errors arise, plus a 3D human-pose likelihood prior
  learned from mocap. — [Lund portal](https://portal.research.lu.se/en/publications/better-prior-knowledge-improves-human-pose-based-extrinsic-camera/)
- Earlier keypoint calibrations (Takahashi et al.; Liu et al.) estimate extrinsics from per-view 2D keypoints
  with classical fundamental-matrix estimation. — survey in [CasCalib arXiv PDF](https://www.arxiv.org/pdf/2405.06845)
- **Pose2Sim** (current docs) recommends "scene" extrinsics: manually measure 10 or more 3D points, which also
  works for unsynchronised cameras. Its "keypoints" extrinsic calibration (a person walking and waving) is
  marked **COMING SOON** and requires synchronised cameras. Its quality targets are intrinsic error ≤0.5 px
  and extrinsic error <1 cm, with up to 2.5 cm "potentially acceptable". It syncs on the speed of vertical
  keypoint motion. — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)

### Inferences
- **[in-house]** The constraints that help most in the literature are ones SignSure lacks: many cameras, a
  ground plane with feet, metric person height, people walking through a large volume, and known intrinsics.
  The one SignSure has, bone-length constancy across frames, is scale-free. It cannot fix the
  focal–depth–baseline ambiguity of a distant, compact subject. That matches the reported symptoms: focal
  drifting to 2.1× nominal, and a 56°→65° baseline shift when the hand point definition changed.
- **[in-house]** Dense hand and face keypoints add many correspondences, but they are noisier at 480p and in
  profile views. Face points are near-rigid, so a *rigid-head* constraint (one 6-DoF pose per frame for the
  face-plus-ear cluster, with fixed shape across frames) is stronger than a bone-length constraint. Its spatial
  extent is small, though, so it mainly helps rotation, not focal.
- **[in-house]** Temporal smoothness on the 3D trajectories (for example the 6 Hz filter already used) reduces
  the effective noise per frame, but it does not break the degeneracy (see §2). It is a second-order gain.

### Gaps
- No published accuracy figures were found for **two-view, single stationary person, upper-body-only**
  self-calibration with unknown focals. CasCalib's statement that two views are insufficient is the closest
  evidence.
- Error numbers from Lee et al. (RA-L 2022) and Moliner et al. (ICPR 2020) were not retrieved (PDF not
  extractable in this session).
- EasyMocap's calibration-from-people mode and the 2026 sports self-calibration preprint (human keypoints plus
  a stick of known length; seen only in a search snippet, [arXiv 2602.13901](https://arxiv.org/pdf/2602.13901v1)
  was a different pose-driven calibration paper) were not examined.

---

## 2. Using known or derivable intrinsics: the iPhone 17 at 1080p and the 480p phone without metadata

### Takeaway
The single biggest evidence-based lever is that **two cameras whose principal axes intersect** (both aimed at
the signer) are the textbook singular configuration for focal self-calibration from two views. Both focals are
then not separately identifiable, which explains the drift. Fixing or tightly constraining the iPhone focal from
metadata leaves only *one* unknown focal. For one unknown focal, the degenerate case is the much rarer one where
the calibrated camera's centre lies on the other camera's principal axis, which is not the case here. The
iPhone's 26 mm-equivalent tag pins the unstabilised focal to about 1442 px at 1920 px width. Stabilisation crop
is the remaining unknown, plausibly +0–20%.

### Cited Findings
- **Kocur, Kyselica and Kukelova (CVPR 2024)** estimate focal lengths from F. Singularities "occur in very
  common camera configurations when the principal axes of the cameras are coplanar", i.e. when they intersect.
  With equal focals, failures occur when the axes are parallel or intersect with the camera centres equidistant
  from the intersection. **With one unknown focal, the degenerate case is when the calibrated camera's centre
  lies on the uncalibrated camera's principal axis.** — [arXiv HTML 2311.16304](https://arxiv.org/html/2311.16304)
- On real data, Kocur et al.'s method with priors gets a median focal error of 14.6% (PhotoTourism) and 19.9%
  (Aachen). Bougnoux gets 19.7% and 25.0%; the prior alone (1.2 × the maximum image dimension, about 50° FOV)
  gets 20.6% and 19.5%. Their priors assume the principal point at the image centre. Code:
  github.com/kocurvik/robust_self_calibration. — [arXiv HTML 2311.16304](https://arxiv.org/html/2311.16304);
  [abstract](https://arxiv.org/abs/2311.16304)
- Apple defines `videoFieldOfView` as the format's horizontal field of view in degrees. It varies by format,
  because binned formats use the sensor differently.
  — [Apple AVCaptureDevice.Format docs](https://developer.apple.com/documentation/avfoundation/avcapturedevice/format.md);
  [search summary of Apple forum](https://developer.apple.com/forums/thread/97353)
- Forum reports of main-camera `videoFieldOfView`: iPhone 13 Pro Max **67.1°**; 14 Pro Max 39.3°, which the
  poster called a bug; 15 Pro 41.2°, also called wrong. These are anecdotal and not Apple-confirmed.
  — [Apple developer forum thread 714978](https://origin-devforums.apple.com/forums/thread/714978)
- Apple's documentation says standard stabilisation uses a low-latency algorithm with a *reduced field of
  view*, and cinematic stabilisation reduces it further. No crop percentage is published.
  — [AVCaptureVideoStabilizationMode](https://developer.apple.com/documentation/avfoundation/avcapturevideostabilizationmode.md);
  [Apple TN2409](https://developer.apple.com/library/ios/technotes/tn2409/_index.html)
- iOS intrinsic matrices (`AVCameraCalibrationData`) are given relative to a reference size, for example
  4032×2268 for a 1280×720 video, and must be rescaled. They are only available from a capture app, not from
  an ordinary Camera-app recording.
  — [Apple forum 675664](https://developer.apple.com/forums/thread/675664);
  [CMCameraIntrinsicMatrix docs](https://developer.apple.com/documentation/coremedia/cmcameraintrinsicmatrix.md)
- **OpenCap** does not self-calibrate intrinsics. It keeps a per-device-model intrinsics database
  (`opencap-core/CameraIntrinsics`, folders up to `iPhone17,1`, i.e. iPhone 16-era identifiers) measured with
  checkerboards for its fixed capture settings. Its developers say intrinsics are specific to the hardware and
  to the capture settings. — [opencap-core CameraIntrinsics](https://github.com/stanfordnmbl/opencap-core/tree/main/CameraIntrinsics);
  [SimTK forum](https://simtk.org/plugins/phpBB/viewtopic.php?p=44358)
- CasCalib estimates single-view focal from a person's height and the ground plane, using standing and walking
  people with visible feet. — [CasCalib HTML](https://arxiv.org/html/2405.06845v1)

### Inferences
- **[in-house] Arithmetic for the iPhone 17 at 1080p.**
  - Apple's "26 mm equivalent" refers to the 4:3 still frame. A 4:3 frame with the 35 mm diagonal (43.27 mm)
    is 34.62 mm wide, so the horizontal FOV is 2·atan(17.31/26) = **67.3°**. That matches the 67.1° reported
    for a 13 Pro Max main camera.
  - 16:9 video that uses the full sensor width therefore has **fx ≈ 1920 × 26 / 34.62 ≈ 1442 px**.
  - With a standard-stabilisation crop of c, fx ≈ 1442 / (1 − c). For c = 10–20% that is about 1600–1800 px.
  - SignSure's diagonal convention gives 1324 px at 26 mm and 1425 px at 28 mm. **The current 28 mm default
    happens to land within about 1% of the no-crop value.** Typing "26" from the metadata into the existing
    formula would be about 8% too short. Any metadata-based fix must convert using the 4:3 *width*, not the
    16:9 diagonal.
- **[in-house]** It is unknown whether the QuickTime tag already includes the stabilisation crop. Three ways
  to pin it from the existing data:
  1. **Single-view vanishing-point calibration of the 1080p frame.** Room edges such as wall–ceiling lines,
     door frames and corners give orthogonal vanishing points v1, v2 and f = sqrt(−(v1−c)·(v2−c)).
  2. **Profile the BA cost over the iPhone focal** with the 480p focal free, i.e. 1-unknown-focal mode.
  3. **Accept a narrow prior.** For example log-normal centred on 1520 px with SD ≈ 0.08, covering roughly
     1442 to 1800 px, instead of 0.15.

  Even option 3 converts the problem from two unknown focals (degenerate here) to one well-constrained and one
  free focal.
- **[in-house] The 480p phone.** With the iPhone focal fixed, Kocur et al.'s one-unknown-focal case applies.
  Degeneracy would need the iPhone's centre on the 480p camera's optical axis, which a 56–65° yaw rules out, so
  that focal becomes identifiable from body correspondences. Cross-check it independently with vanishing
  points from room lines in the 480p frame, if there are enough straight edges. Agreement between the two is a
  quality gate. "Person height" focal methods need metric height and visible feet; for an upper-body signing
  video they are weak unless the user's real height is known and the full body is in view.
- **[in-house]** The 480p file was likely re-encoded by a messaging app, which can also have cropped or
  rescaled the frame. Assume a centred principal point and square pixels, and do not assume any
  35 mm-equivalent value for it.

### Gaps
- No published 1080p video-mode FOV, stabilisation crop or intrinsic matrix for the iPhone 17 main camera was
  found. Apple publishes none, forum values are inconsistent, and OpenCap's database for this model was not
  inspected.
- It is unknown which stabilisation mode was active (Standard, Cinematic, Action) and whether the 35 mm tag
  reflects it. The `apple-maker-note` timed tracks are undocumented and were not decoded. They might contain
  per-frame data, but this is unverified.
- No source was fetched quantifying vanishing-point focal accuracy for phone frames. The method is classical
  (Caprile and Torre 1990), but no URL was retrieved in this session.

---

## 3. Static scene structure (background) as a calibration target

### Takeaway
Feature matching on the static background between the two fixed phones is feasible only if both views see the
same background surfaces at a 56–65° viewpoint change. Classical SIFT usually breaks down at such baselines.
Learned matchers (LightGlue, LoFTR, MASt3R) are much better on wide-baseline benchmarks. Background points
would greatly improve the *extrinsic rotation* (hundreds of well-localised, sub-pixel, spatially spread
points versus 4–7 px body keypoints). However, they do **not** remove the focal degeneracy, which depends on
camera geometry, not on what is matched. Each phone is static, so there is no within-video parallax and COLMAP
structure-from-motion per video is impossible; it is strictly a two-view problem.

### Cited Findings
- On MegaDepth with LO-RANSAC, MASt3R reaches relative-pose AUC@5/10/20° of about 63.5/76.3/85.2, against
  58.1/70.4/79.6 for DUSt3R (third-party evaluation). — [CoMatcher arXiv 2504.01872](https://arxiv.org/pdf/2504.01872)
- MASt3R reports leading relative-pose results on CO3Dv2 and RealEstate10k *without ground-truth focals*. On
  RealEstate10k its mAA is at least 8.7 points above the best multi-view methods and 15.2 above pairwise
  DUSt3R. — [MASt3R arXiv 2406.09756](https://arxiv.org/pdf/2406.09756)
- DUSt3R recovers focal and pose from predicted pointmaps by Procrustes or PnP. — [DUSt3R arXiv 2312.14132](https://arxiv.org/pdf/2312.14132)
- Moliner et al. state that classical SfM calibration needs special equipment to get accurate point
  correspondences between views, while pose keypoints are much less accurate than patch-based features.
  — [Lund portal](https://portal.research.lu.se/en/publications/better-prior-knowledge-improves-human-pose-based-extrinsic-camera/)
- The coplanar-principal-axes singularity is a property of the two-camera configuration in focal-from-F
  estimation. — [Kocur et al. CVPR 2024](https://arxiv.org/html/2311.16304)

### Inferences
- **[in-house] Feasibility test, cheap, about one day of code.**
  1. Take a median (person-masked) background frame from each video, using the RTMW person box or a
     segmentation mask.
  2. Run LightGlue+SuperPoint (or DISK) and MASt3R between them.
  3. Count geometrically verified inliers.
  4. If there are, say, 50 or more well-spread inliers, add them to the bundle adjustment as static points,
     one 3D point each, observed in every frame, and weighted by their much lower noise.
  5. Background points plus body points constrain rotation and the translation direction better, and they
     reduce the dependence of the baseline estimate on the hand-point definition, which is the observed
     56°→65° instability.
- **[in-house]** Background depth spread matters. A wall 1–2 m behind the signer adds depth variation the
  compact upper body lacks, which improves the conditioning of the focal–baseline coupling once one focal is
  fixed.
- **[in-house] Risks.**
  - The 480p re-encoded frame has heavy compression, weak texture and possible blur.
  - Front and side views may share little background; walls visible in one may be behind the other camera.
  - Electronic stabilisation makes the iPhone's effective extrinsics/principal point vary slightly frame to
    frame; use a per-frame homography check on background tracks to test this.
  - MASt3R's own focal estimate is a learned monocular prior. Use it only as a weak, independent cross-check,
    never as the calibration.
- **[in-house]** Expected accuracy versus body-only calibration: on the literature evidence, patch features
  give ~0.2–0.5 px against 4–7 px for body keypoints, and Pose2Sim's board-based targets are ≤0.5 px.
  Even 50 background inliers could therefore carry information comparable to thousands of body observations,
  but only if overlap exists. No published head-to-head number for this exact setting was found.

### Gaps
- No study comparing background-SfM versus body-keypoint calibration for two fixed phones filming one person
  was found.
- MASt3R/DUSt3R focal-estimation accuracy was not found as a separate benchmark.
- Whether the After/Action backgrounds overlap enough is unknown; it needs the feasibility test above.

---

## 4. Robustness: fixing intrinsics, decoupling calibration from the tested angle definitions, robust losses, honest uncertainty

### Takeaway
Two changes are both defensible and cheap:
- **Remove the dependence of the calibration on the hand point.** Calibrate from torso, shoulder, hip, face and
  ear, plus elbow/wrist reprojection *without* a bone-length term on any segment whose definition is being
  tested.
- **Propagate calibration-model uncertainty**, especially the focal prior, into the Monte Carlo instead of only
  refitting under keypoint noise.

A Huber loss is already in use. A Laplace/Hessian uncertainty would understate the ridge-shaped focal–baseline
uncertainty. A bootstrap or profile over the focal, plus a pre-registered sensitivity envelope, is more honest.

### Cited Findings
- CasCalib's final bundle adjustment *excludes head and arm keypoints*. Its authors note that errors propagate
  through stages and cannot be recovered later. — [CasCalib HTML](https://arxiv.org/html/2405.06845v1)
- Moliner et al. derive a robust reprojection loss from the error structure of pose estimators and add a
  learned 3D-pose likelihood prior, improving extrinsic calibration on four public datasets. No numbers were
  retrieved. — [Lund portal](https://portal.research.lu.se/en/publications/better-prior-knowledge-improves-human-pose-based-extrinsic-camera/)
- Kocur et al.'s prior-regularised focal estimator is robust to inaccurate priors and principal-point errors,
  while Bougnoux degrades. On Aachen, though, the prior alone had a median focal error (19.5%) slightly lower
  than the full method's (19.9%). In near-degenerate data, a well-chosen prior is about as good as the data.
  — [arXiv HTML 2311.16304](https://arxiv.org/html/2311.16304)
- Pätzold et al. and OpenCap both treat intrinsics as known and fixed, from a database or a separate
  calibration, and estimate only extrinsics from people. — [arXiv 2209.07393](https://arxiv.org/abs/2209.07393);
  [SimTK forum](https://simtk.org/plugins/phpBB/viewtopic.php?p=44358)

### Inferences
- **[in-house] Decoupling.** The observed 56°→65° baseline shift after changing the hand point means the
  bone-length residuals on the forearm/hand segment dominate the weak focal–baseline direction. Options:
  - (a) Drop bone-length terms that include `*_index`/wrist-to-hand; keep upper arm, forearm (elbow–wrist),
    shoulder width and torso.
  - (b) Keep hand points in reprojection only. Reprojection consistency does not depend on the angle
    definitions; it only adds correspondences.
  - (c) As a stability test, calibrate on the torso+head subset alone and report the difference.

  Calibration should be invariant to the angle definitions under test. Pre-register this change before the next
  take.
- **[in-house]** Weight each 2D keypoint residual by its measured noise. SignSure already has TTA spread and
  the still-frame noise model, so use per-joint σ from those instead of uniform pixels (Huber `f_scale=2 px`
  is in units that differ between 480p and 1080p). Use a per-camera robust scale, roughly σ480 ≈ 2×σ1080 in
  pixels per unit body size.
- **[in-house] Honest uncertainty.**
  1. Profile the BA objective over the (free) 480p focal, and over the iPhone stabilisation-crop factor, on a
     grid. If the profile is flat over more than ±10%, the data do not identify the focal and the prior is
     doing the work. Report that.
  2. In the parametric Monte Carlo, draw the focal(s) from the stated prior in each draw, not just re-fit from
     noisy keypoints, so the RMS upper bound includes prior uncertainty.
  3. Laplace (inverse Gauss–Newton Hessian) is unreliable here because the posterior is non-Gaussian and
     ridge-shaped along the focal–depth–baseline direction. Use it only as a diagnostic: its condition number
     flags near-degeneracy.
  4. Report a pre-registered "calibration-variant envelope" (focal ±1 SD, point-subset variants). An
     equivalence claim should hold across the envelope, not only at the best fit.
- **[in-house]** Joint angles are scale-invariant, so absolute scale does not matter. What matters is the
  *relative rotation and the focal ratio*, because these shear the triangulated depth axis and directly bias
  elbow and shoulder angles in the depth direction. This is why focal uncertainty maps into the angle results.

### Gaps
- No published study quantifies how calibration focal error maps into 3D joint-angle error for two-view phone
  setups. SignSure's own simulation tool (`single_take_simulation.py`) could produce it in-house by perturbing
  the focal and measuring the RMS angle change.

---

## 5. Lens distortion and rolling-shutter correction in software

### Takeaway
For the iPhone main (wide) camera, residual lens distortion in Camera-app video is probably small, because
Apple applies geometric distortion correction by default at least on the ultra-wide. It cannot be estimated
reliably from body keypoints and is best left at zero, or estimated from straight room lines. Rolling shutter
is a potentially larger, unmodelled effect for fast hand motion. A per-row time offset can be added in code
using the existing sub-frame sync, but the sensor readout times are unknown.

### Cited Findings
- On iPhones, geometric distortion correction is enabled by default for the ultra-wide camera, and it blocks
  delivery of calibration data. — [Apple forum 741815](https://developer.apple.com/forums/thread/741815)
- Pose2Sim expects intrinsic calibration (including distortion) from a board at ≤0.5 px and does not estimate
  it from people. — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)
- CasCalib estimates no distortion and fixes the principal point at the image centre.
  — [CasCalib HTML](https://arxiv.org/html/2405.06845v1)

### Inferences
- **[in-house] Distortion.** Distortion k1 and the focal are partly confounded with keypoints concentrated near
  the image centre (a centred signer). Fitting k1 from body points would add a near-unidentifiable parameter.
  If straight lines (door frames, wall edges) are visible, a plumb-line fit per camera can test whether k1 is
  ≈0. If it is, keep the zero-distortion model and state it as an assumption. The 480p re-encode may also have
  been rescaled but not cropped; distortion there is unknowable without lines.
- **[in-house] Rolling shutter.** In a rolling-shutter sensor, row y is exposed at t0 + (y/H)·t_readout.
  - For a hand at 2 m/s, about 3 m from the camera, with fx ≈ 1500 px, the image speed is about 1000 px/s.
  - A 10 ms row-time difference therefore shifts the hand by about 10 px, comparable to or larger than the
    3 px keypoint noise.
  - Software fix: give each 2D keypoint a time stamp t_frame + (y/H)·t_ro and interpolate the other view's
    trajectory at that time before triangulation.
  - t_ro is unknown for both phones (plausibly about 5–30 ms). It can be estimated as one extra parameter per
    camera by the existing `refine_lag` reprojection minimisation, since it acts like a row-dependent lag, or
    profiled on a grid.
  - This mostly affects the moving-frame triangulation (hands, wrists), not static-hold calibration.
  - **Priority depends on magnitude:** test it by checking whether reprojection error correlates with keypoint
    image speed times row position.
- **[in-house] Variable frame rate.** The 480p file is VFR. `CAP_PROP_POS_MSEC` is used, which is correct in
  principle. Verify it equals the true PTS for every frame (for example by comparing against a demuxer such as
  PyAV or ffprobe). A few dropped or duplicated frames would act like local sync errors, indistinguishable from
  calibration error in the reprojection residuals.

### Gaps
- No published rolling-shutter readout times were found for the iPhone 17 main camera at 1080p60, nor for the
  unknown 480p phone.
- No published distortion coefficients were found for iPhone main-camera video after in-camera correction.

---

## 6. Is any limited, non-circular use of the FBX defensible for calibration?

### Takeaway
Fitting camera poses to FBX joint trajectories or angles (for example Procrustes alignment of FBX joints to
2D keypoints) is circular and must not be done. Two uses are *arguably* defensible if pre-registered and
reported with a sensitivity analysis:
- **(a) Time-invariant segment-length ratios** from the FBX skeleton as a bone-length prior. These are scale-free
  and carry no angle information, but they inject the suit's body model.
- **(b) The FBX timeline for the sign window and sync**, which is already done.

The cleaner alternative to (a) is to use the person's own measured or self-reported height and population
anthropometric ratios.

### Cited Findings
- Published person-based calibrations use generic human priors (a learned 3D pose likelihood from mocap
  databases, assumed person height 1.6–1.7 m) rather than the evaluated system's output.
  — [Moliner et al.](https://portal.research.lu.se/en/publications/better-prior-knowledge-improves-human-pose-based-extrinsic-camera/);
  [CasCalib HTML](https://arxiv.org/html/2405.06845v1)
- The Pose2Sim scene method calibrates from independently measured 3D points in the room, not from the motion
  being measured. — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)

### Inferences
- **[in-house]** Why (a) is weakly but not fully non-circular. Joint angles are invariant to segment *lengths*,
  so a length prior cannot directly pull video angles toward FBX angles. It can change the calibration,
  though, as the 56°→65° shift shows, and through that the depth shear, i.e. the angles. Any FBX-derived
  prior should therefore be:
  - pre-registered;
  - limited to segments not used in the hand point (upper arm, forearm, shoulder width);
  - reported both with and without, with the conclusion required to hold in both.
- **[in-house]** A second defensible use: the FBX as a **held-out diagnostic only**. Compute the calibration
  without the FBX, then report the suit-vs-video rest-pose segment-ratio agreement as a sanity check. This does
  not influence the test statistic.
- **[in-house]** Not defensible: using FBX world orientation or gravity (IMU frame) to fix camera pitch/roll,
  aligning FBX 3D trajectories to the triangulation to choose the focal, or selecting the calibration variant
  that gives the best suit agreement. All of these condition the calibration on the outcome.

### Gaps
- No methodological source was found that addresses using a reference instrument's skeleton for calibrating
  the comparator instrument in method-comparison studies. This section is reasoning, not literature.

---

## 7. Overall ranking: software-only calibration improvements by expected accuracy and stability gain

### Takeaway
Rank order, from evidence plus in-house reasoning:
1. **Constrain the iPhone 17 focal** from its 26 mm metadata, correctly converted to about 1442 px plus an
   unknown stabilisation crop, so only one focal is unknown. This leaves the singular two-unknown-focal
   configuration identified by Kocur et al.
2. **Decouple the calibration from the angle definitions under test** (no hand-point bone-length terms;
   residuals weighted by measured noise).
3. **Add static background correspondences** (LightGlue/MASt3R), if the backgrounds overlap.
4. **Independently cross-check focals** with vanishing points from room lines.
5. **Propagate focal-prior uncertainty** and report a pre-registered calibration-variant envelope.
6. **Model rolling shutter** as a per-row lag, after checking its magnitude.
7. **Verify VFR timestamps.**
8. Lens distortion: leave it at zero unless a plumb-line test says otherwise.

### Cited Findings
- Two-camera focal self-calibration is singular when principal axes intersect. One unknown focal is degenerate
  only if the calibrated camera's centre lies on the other camera's principal axis.
  — [Kocur et al. CVPR 2024](https://arxiv.org/html/2311.16304)
- Person-based calibration benchmarks reach about 2° rotation error only with 4 cameras, ground-plane cues and
  sync; two views are deemed insufficient for noisy-keypoint bundle adjustment.
  — [CasCalib](https://arxiv.org/html/2405.06845v1)
- Production pipelines (OpenCap, Pose2Sim, Pätzold et al.) fix intrinsics from an external source rather than
  self-calibrating them from people.
  — [OpenCap forum](https://simtk.org/plugins/phpBB/viewtopic.php?p=44358);
  [Pose2Sim](https://github.com/perfanalytics/pose2sim); [arXiv 2209.07393](https://arxiv.org/abs/2209.07393)
- Learned wide-baseline matchers give much better relative pose than older methods on MegaDepth.
  — [CoMatcher](https://arxiv.org/pdf/2504.01872); [MASt3R](https://arxiv.org/pdf/2406.09756)

### Inferences
**[in-house]** Ranking, with expected effect and cost:

| Rank | Change | Why / expected effect | Cost | Evidence level |
|---|---|---|---|---|
| 1 | Tight prior or fixed value for the iPhone focal: 26 mm eq. converted by 4:3 width gives about 1442 px at 1920 px width; prior spans 1442–1800 for the stabilisation crop (e.g. log-SD 0.08) instead of the shared 28 mm diagonal default with SD 0.15 | Removes the two-unknown-focal singularity; the 480p focal becomes identifiable; should stop 2× focal runaways and shrink the baseline swing | Hours | Published degeneracy result + in-house arithmetic |
| 2 | Calibration independent of the tested definitions: drop hand-point bone-length terms; residuals weighted by TTA/still-frame σ per joint and camera | Directly targets the observed 56°→65° baseline shift; makes calibration invariant to angle-definition changes (protocol hygiene) | Hours | Observed in-project symptom + CasCalib practice of excluding arm/head points |
| 3 | Static background matches (masked median frames; SuperPoint+LightGlue and/or MASt3R) as extra BA points | Sub-pixel, spatially spread points with depth beyond the body; better rotation and baseline conditioning; no effect on the focal degeneracy itself | About 1 day; feasibility unknown | Published matcher benchmarks; in-house applicability |
| 4 | Vanishing-point focal per camera from room lines; profile likelihood of BA over the 480p focal | Independent check of both focals; the stabilisation crop becomes measurable | About 1 day | Classical method (source not fetched) + in-house |
| 5 | Monte Carlo draws the focal from its prior; pre-registered calibration-variant envelope; Laplace only as a degeneracy diagnostic | Does not improve accuracy, but makes the ±15° upper bound honest | Hours | In-house (statistical reasoning) |
| 6 | Rolling-shutter per-row time offset (t_ro profiled or fitted inside `refine_lag`) | Possibly 5–10 px on fast hand frames at 1080p; matters for moving-frame triangulation more than calibration | About 1 day; first test correlation of residual with speed × row | In-house estimate; readout times unknown |
| 7 | Verify VFR timestamps (`CAP_PROP_POS_MSEC` against demuxer PTS) | Cheap check; would remove a hidden sync-error source if it fails | An hour | In-house |
| 8 | Lens distortion: plumb-line test only, otherwise keep k = 0 | Low expected gain for the iPhone main camera; unknowable for the 480p file without lines | Hours | Apple forum (distortion correction on ultra-wide) + in-house |

**[in-house]** All of these changes, if applied to After and Action, are **exploratory** under the project's
pre-registration rules. They become confirmatory only if committed before analysing a future take.
Re-analysing the existing takes cannot be confirmatory, and the report should say so.

### Gaps
- No study in the 2019–2026 literature gives the expected improvement in 3D joint-angle RMS from fixing
  intrinsics in a two-phone person-calibration setup. The gains above are qualitative. They should be
  quantified with SignSure's own synthetic simulation (`single_take_simulation.py`) by comparing (i) both
  focals free with a 15% prior against (ii) one focal fixed or with an 8% prior, and (iii) with background
  points added.
