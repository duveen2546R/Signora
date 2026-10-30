# Protocol to legitimately pass a single-take suit-vs-video elbow-angle equivalence test (±15°)

Scope note: the Consensus tool returned only 3 papers per query (free tier), and several searches found no direct quantitative evidence. Every number below has a source. Where nothing was found, it says so under Gaps. "Inferences" are my reasoning, not literature claims.

Ranked checklist summary (detail and sources in the sections below):
1. **Align skeleton and angle definitions, and remove the static offset** (largest, best-documented lever: offsets dominate inter-system RMSD).
2. **Widen camera angular separation to about 60–90°** (avoid about 30° "same quadrant"), keep cameras 2 m or more away, and make sure both views see both arms throughout.
3. **Use measured intrinsics** (a displayed or printed checkerboard per phone, fixed focus and zoom) and **a printed A4 checkerboard for extrinsics** in place of the 15% focal prior.
4. **Fresh IMU suit calibration** away from metal, check the magnetic environment (±0.15 G), keep the take short.
5. **Sync with an explicit event** (clap or flash, plus a sharp arm motion visible to the suit), refined by velocity cross-correlation, aiming for under 1 frame.
6. **Phone settings**: 60 fps, fixed exposure with a short shutter, locked focus and zoom, no stabilisation.
7. **Directly measure motion-time keypoint error** by hand-labelling a frame subset and feeding it into the Monte Carlo.
8. **Analysis choices**: report bias and offset-removed RMSD separately, pre-register the offset-removal rule, and use the raw suit skeleton, not the Mixamo retarget.

---

## 1. Skeleton and angle-definition alignment (suit vs video), and retargeted FBX

### Takeaway
In concurrent-validation studies, much of the between-system disagreement is a constant offset from differing joint-centre and segment definitions, not dynamic error. Removing it (a static-pose or mean-offset correction) routinely brings RMSD from above 6° to under 6–8°. This is the single biggest lever, but it has to be pre-specified and reported honestly, because it changes the question from "absolute agreement" to "agreement after calibration".

### Cited Findings
- Theia3D vs Vicon (36 clinical patients): RMSD was under 6° except several angles, which "mainly differed due to an offset between the curves. After adjusting for offsets, all RMSDoffset were < 6°" (under 8° for patients with deformities, orthoses or assistive devices). — [Wren et al. 2023, Gait & Posture](https://consensus.app/papers/details/671c9d767b3c56548b02cb1958ea198f/?utm_source=claude_code)
- Theia3D vs marker-based shoulder in pitching: fixed bias up to −19.1° (horizontal angle). "Participant-specific offsets were primary contributors to the limits of agreement." — [Uchida et al. 2026, Sports Biomechanics](https://consensus.app/papers/details/7c4f17fad7ec5204b4c9bdb1147dc0aa/?utm_source=claude_code)
- Ripic et al. call for improvements in "markerless keypoint model definitions, and standardization of comparison study protocols"; joint-centre RMSE was under 28 mm. — [Ripic et al. 2023, J Biomech](https://consensus.app/papers/details/37ed848240605735b559fbcbc13a6090/?utm_source=claude_code)
- Robert-Lachaine et al. (IMU vs optoelectronic): differences attributed to the **biomechanical model were significantly greater than technological error**. Mean RMSE was 2.8° for a long complex task vs 1.2° for short functional movements. — [Robert-Lachaine et al. 2017 (IRSST record)](https://pharesst.irsst.qc.ca/etudes-primaires/139)
- OpenCap's validation removes an average position offset from OpenCap after time-aligning to mocap (minimising mean marker difference). Using LSTM-predicted anatomical markers instead of raw keypoints reduced kinematic error by 3.4° on average, and raw keypoints alone gave 12.1–39.2° errors at some joints. — [Uhlrich et al. 2023, PLOS Comp Biol](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- Two indirect systems (CapturyStudio markerless vs Xsens IMU): **median elbow flexion discrepancy about 12°** (below 8° for shoulder, knee, hip). The authors stress this is an upper bound on the error of either system, not absolute accuracy. — [Francia et al. 2026, Sensors](https://consensus.app/papers/details/0cd0a4a588bd51eaa1a1ee7e867a5563/?utm_source=claude_code)
- Markerless upper-limb studies show a **systematic underestimation of maximum flexion** (magnitude bias, linked to occlusion and joint geometry) even with ICC > 0.91 at the elbow. — [Francia et al. 2026, Applied Sciences](https://consensus.app/papers/details/9fabcdafd4645eb7ac96cfb586d2f6b9/?utm_source=claude_code)
- Markerless vs marker-based upper extremity (children, Box and Blocks): RMSD of **demeaned** UE angles was under 6°, while Bland-Altman confirmed measurement bias between systems. — [Hansen et al. 2024, Biomed Eng Advances](https://consensus.app/papers/details/2c43500e8df45e6cabffd16853f2ac31/?utm_source=claude_code)
- IMU elbow calibration options compared (N-pose, functional flexion-extension and pronation-supination, manual alignment). Functional calibration estimates the joint axis from single-plane elbow movements. — [Frontiers Bioeng 2024 (PDF)](https://www.frontiersin.org/journals/bioengineering-and-biotechnology/articles/10.3389/fbioe.2024.1385750/pdf)

### Inferences
- The Francia (Captury vs Xsens) result is the closest analogue to this project (video vs IMU, two indirect methods). A median elbow discrepancy of about 12° says a ±15° margin is **not comfortably met by default**, even with 8 cameras. Offset handling and definition alignment are therefore necessary, not optional.
- Recommended actions:
  - (a) Compute the elbow angle from **the suit's native (raw) skeleton joint positions**, not the Mixamo retarget. Retargeting maps rotations onto a different rest pose and bone lengths, so the joint positions in the retargeted FBX are not where the suit's solver put them.
  - (b) Record a **static reference pose** (arms extended, T or A pose) plus a **slow full-range elbow flexion-extension clip** in the same session, before and after the take.
  - (c) Pre-register one offset-removal rule (for example, subtract the mean video−suit difference from the static clip) and apply it unchanged to the sign take.
  - (d) Report the equivalence test **both with and without** offset removal. Raw bias is a legitimate finding about definition mismatch; offset-removed agreement is the dynamic-tracking claim.
- If both systems are run through a common definition (for example, video keypoints mapped to the same joint-centre convention the suit uses, or both fitted to one kinematic model), the expected reduction is in the range shown by Wren (RMSD to RMSDoffset: from several degrees above 6° to under 6°). Exact gains for the elbow are not given.

### Gaps
- I found no study quantifying elbow-angle differences between a Mixamo-retargeted FBX and the raw IMU skeleton. This needs to be measured in-house: export both and compare on the same take.
- No elbow-specific number for how much static-pose offset removal reduces markerless-vs-IMU disagreement.

---

## 2. Camera baseline angle, distance, number, frame rate, shutter, resolution

### Takeaway
Two-camera agreement depends strongly on angular separation. About 28° ("same quadrant") gave RMSE above 10° in frontal and transverse planes, while about 70–80° separations gave the best agreement. Very wide (about 160°) did not help further. OpenCap's validated setup is ±45° (90° separation), at least 2 m away, 60 Hz, 720p. Adding cameras beyond two gave under 0.3° kinematic gain in OpenCap, so geometry and visibility matter more than count.

### Cited Findings
- 28 two-camera pairs vs an 8-camera Theia3D reference: front/back configurations with **68.6 ± 17.7° and 81.0 ± 22.4°** separation had the most favourable agreement (sagittal RMSE < 8°). **Same quadrant, 28.2 ± 3.8°**, was poorer (RMSE > 10°, CMC < 0.60 in frontal and transverse planes). Diagonal about 160° did not consistently improve agreement. — [Zhao et al. 2026, Frontiers Sports Act Living](https://consensus.app/papers/details/33bddc7f40ee5b92b2230269cc3da1dc/?utm_source=claude_code)
- Two-camera table tennis, elbow angle: increasing the baseline from 100 to 145 cm significantly improved accuracy (p < 0.01). With a fixed baseline, a right-front placement beat right-right. — [Cao et al. 2026, Frontiers Bioeng](https://consensus.app/papers/details/bb538d828d1c5952977ef564f563c47f/?utm_source=claude_code)
- Two webcams plus OpenPose vs IMU: errors up to 14.0 ± 1.8°, dependent on camera configuration. With the joint visible from both cameras for the whole trial, accuracy was 1.6 ± 0.3°. — [D'Antonio et al. 2021, IEEE Sensors J](https://consensus.app/papers/details/5f7f1b3d8dc45222bdcb962e5c6842f7/?utm_source=claude_code)
- OpenCap: two iPhones at ±45°, 1.5 m high, 3 m from centre, 720×1280 at 60 Hz, focus fixed. Subjects should be 2–10 m away, never closer than 2 m. Upper-extremity marker error 39 mm (vs 27 mm lower extremity). Three cameras did not improve accuracy; five cameras gave 29 vs 32 mm and under 0.3° kinematic gain. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- Monocular camera-angle study for upper limb: **elbow most accurate at 90° and 135°** camera positions (MediaPipe). — [Kim et al. 2025, IEEE Access](https://consensus.app/papers/details/fcc7f9ebfa815bc788c0b277ec185521/?utm_source=claude_code)
- OpenPose multi-camera: about 80% of joint-position MAEs under 30 mm, 10% over 40 mm, mainly from 2D tracking failures such as segment swaps. — [Nakano et al. 2020, Frontiers](https://consensus.app/papers/details/2f4f544108ad558dbf0071fe9e8e1d84/?utm_source=claude_code)
- Upper body is weaker than lower body with OpenCap's earlier model: overhead-squat upper-body RMSE was 36.7° (CMC 0.48). — [SKKU OpenCap overhead squat study](https://scholarx.skku.edu/item/fa60b317-005d-4e2b-89cd-fd2166b18730). OpenCap staff pointed users to an updated ISB-shoulder model (June 2023). — [SimTK forum](https://simtk.org/plugins/phpBB/viewtopic.php?p=51537)
- Motion blur blends limb boundary pixels with background and makes keypoint detection hard; the noisy 2D keypoints propagate to 3D. — [USPTO patent 12236616](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12236616). Rapid motion is temporally under-sampled and blurred; staggered exposure is one mitigation. — [Liu et al., PG2012](https://liuyebin.com/staggermocap/staggermocap.html)
- Pose2Sim: across all lower-limb joint angles, mean errors were 3.0°, 4.1° and 4.0° (walk, run, cycle) vs markers. A 1 cm calibration perturbation produced 0.19° sagittal error in walking. — [Pagnon et al. 2022 Part 2](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9002957/); [Part 1 (HAL)](https://hal-udl.archives-ouvertes.fr/LJK-GI-CVGI/hal-03581859v1)
- Stereo depth error grows quadratically with depth for a fixed baseline. — [Gallup et al. 2008, CVPR](https://consensus.app/papers/details/85f5858613465c5e9fc2aaaa5287aa5d/?utm_source=claude_code)

### Inferences
- The current setup (30–45° separation) sits in or near the "same quadrant" regime that Zhao found worst (RMSE > 10° off-sagittal). Elbow flexion in signing is largely non-sagittal relative to any fixed camera, so **moving to about 70–90° separation** is the clearest hardware fix: for example, front plus a side view at about 80°, or ±40–45° each side of the signer. Expected change from Zhao's numbers: from above 10° to under 8° RMSE class, though that is for lower limbs.
- Make sure **both arms are visible in both views** for the whole take. D'Antonio shows 1.6° vs up to 14° depending on joint visibility. A side camera may occlude the far arm, so two oblique cameras at about ±40–45° (OpenCap geometry) may beat front plus side for bilateral signing.
- Distance: put the signer 2–4 m away and frame so the upper body fills most of the frame (vertical orientation). Avoid wide shots, where the arms span few pixels.
- Phone settings, from first principles plus the blur evidence:
  - 60 fps.
  - Exposure lock with a short shutter. Practical target is 1/500 s or faster under bright lighting, because sign handshapes and wrists move fast.
  - Lock focus (OpenCap fixed focus) and zoom/lens (no auto lens switching).
  - Disable video stabilisation (EIS changes effective intrinsics frame by frame).
  - 1080p or more.
  - Numerical blur-vs-keypoint-error data was not found.

### Gaps
- No study found quantifying keypoint error vs shutter speed or frame rate for pose estimators.
- No elbow-specific triangulation error by baseline at exactly 30/45/60/90°. Zhao is lower-limb, and Cao reports DTW similarity, not degrees.
- The effect of EIS on triangulation was not found in the literature; this is an inference.

---

## 3. Intrinsic and extrinsic calibration without a dedicated board

### Takeaway
OpenCap uses per-device intrinsics precomputed with a large precision checkerboard, plus a **single image of an A4 printed checkerboard** for extrinsics, and found minimal kinematic difference vs the precision board. A checkerboard **shown on a flat monitor** is an accepted intrinsics target that can match or beat printed boards. Both options are cheap and remove the "focal from a 15% prior" weakness that two-view self-calibration cannot resolve.

### Cited Findings
- OpenCap intrinsics come from a database of iOS devices (focal length, principal point, distortion), computed with OpenCV from a precision 720×540 mm checkerboard. Extrinsics come from a single image of a **210×175 mm board printed on A4**, which produced minimal kinematic differences vs the precision board. Calibration error grows with distance from the board, so the activity should happen near the board position. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- A monitor-displayed (active) checkerboard outperformed a passive checkerboard on a stiff plate: best 0.16 px reprojection and 0.06 mm fiducial error, limited by the monitor pixel pitch. — [SPIE Electronic Imaging 2024](https://electronicimaging.spiedigitallibrary.org/conference-proceedings-of-spie/12903/129030E/Reliable-and-good-camera-calibration-based-on-machine-learning-inspired/10.1117/12.3000846.full)
- Gray-code patterns on an LCD estimated focal length 1.5× more precisely than a printed checkerboard (one camera; a reviewer questioned the reference). — [Camera Calibration Using Gray Code, PMC6359438](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6359438/); [review report](https://www.mdpi.com/1424-8220/19/2/246/review_report)
- Fronto-parallel board views give large focal-length errors; tilt the target across views. Monitors are "very accurate and flat" targets. — [Deepen.ai calibration guide](https://help.deepen.ai/deepen-ai-enterprise/calibration/data-collection-for-camera-intrinsic-calibration)
- Pose2Sim maintainers advise not over-trusting calibration reprojection error and checking post-triangulation reprojection error instead (maintainer comment). — [Pose2Sim GitHub issue #33](https://github.com/perfanalytics/pose2sim/issues/33)

### Inferences
- Protocol:
  - (1) **Intrinsics per phone**, in the exact video mode used: same resolution, fps, lens, focus lock and stabilisation off. Film a checkerboard or ChArUco on a laptop or monitor (known pixel pitch) or a flat A4 print, at 15–30 tilted poses covering the frame corners, and calibrate with OpenCV.
  - (2) **Extrinsics**: an A4 checkerboard held where the signer's hands will be, visible to both phones simultaneously, filmed at the start of the take without moving the phones. Use it directly (OpenCV stereoCalibrate or PnP per camera), or use it to validate and constrain the body-keypoint self-calibration.
- This converts the focal-length error from a 15% prior to a measured value with small uncertainty, and shrinks the Monte Carlo calibration-refit spread accordingly. No study gives the elbow-angle degrees saved, but OpenCap's ±45° checkerboard setup achieved 4.5° mean joint-angle MAE.
- EXIF focal length (35 mm equivalent) gives at best a nominal focal length. It ignores distortion and the crop from video mode or stabilisation, so treat it as a prior only.

### Gaps
- No source found quantifying EXIF-derived vs calibrated focal error for phone video modes.
- OpenCap's S1 Appendix (intra- and inter-phone intrinsic consistency) was not retrieved.

---

## 4. Synchronisation (phones and suit)

### Takeaway
OpenCap syncs cameras by cross-correlating keypoint velocities. Audio cross-correlation and clap events give roughly frame-level precision (worst case about 1/fps). Suit-to-video sync needs a shared kinematic event, because the suit has no audio. The aim is sub-frame residual sync (under about 17 ms at 60 fps). Earlier project research noted sync errors produce large calibration errors (CasCalib).

### Cited Findings
- OpenCap: videos time-synchronised by cross-correlating keypoint velocities across cameras; mocap-to-OpenCap alignment by minimising marker difference. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- Audio time-lagged cross-correlation between video audio tracks: worst-case skew is 1/FPS of the slowest video. — [arXiv 2210.09821](https://arxiv.org/pdf/2210.09821)
- Audio-IMU cross-correlation on a wearable: MAE 32 ms over a 20 s snippet; raw offsets typically a few hundred ms. — [arXiv 1805.05456](https://arxiv.org/pdf/1805.05456)
- Long recordings drift, so per-chunk offsets may be needed (community report: 30 s chunks fail at hour scale). — [caliscope discussion #496](https://github.com/mprib/caliscope/discussions/496)
- Vision-only cross-view sync: average error under 130 ms (a looser bound). — [Visual Sync, NeurIPS 2025](https://neurips.cc/virtual/2025/poster/118089)

### Inferences
- Protocol:
  - (1) At the start and end of the recording, do a **sharp clap with arms extended plus a fast elbow snap**. This gives an audio event for phone-to-phone sync and a kinematic event visible to both the suit and the video.
  - (2) Coarse-align on the clap, then **refine by cross-correlating elbow-angle (or wrist speed) time series** between suit and video at sub-frame resolution (upsample or interpolate).
  - (3) Check for drift by comparing start and end offsets. If they differ, fit a linear clock-rate correction (phone and suit clocks differ; phones may use variable frame rate, so use actual frame timestamps).
- Report the residual sync uncertainty and include it in the Monte Carlo as a time-shift distribution.
- Caution: optimising sync on the elbow angle itself slightly flatters agreement. Prefer sync on wrist speed or a separate calibration event, and pre-register the choice.

### Gaps
- No published residual-error figure was found for clap/flash plus kinematic cross-correlation between an IMU suit and phone video.
- The CasCalib 13° figure (from earlier research) was not re-verified here.

---

## 5. IMU suit error sources and mitigation

### Takeaway
IMU suits are typically within about 2–5° RMSE on elbow flexion in controlled studies, but error rises for long, complex and fast tasks and under magnetic disturbance. Some systems show biases above 10° at the elbow specifically. Mitigation: fresh calibration in a magnetically clean spot, a verified magnetic environment, short takes, and pre- and post-take static poses to detect drift.

### Cited Findings
- Rokoko Smartsuit Pro (one small study): elbow flexion RMSE 0.51° vs OptiTrack in vivo, 0.31° on a stepper-motor rig, Pearson r 0.77. The sample size and venue are unclear, so treat this as preliminary. — [Istanbul University record](https://avesis.istanbul.edu.tr/yayin/b6335d1a-ef27-46a3-9eff-efe6700f667f/investigation-of-wearable-motion-capture-system-towards-biomechanical-modelling)
- Perception Neuron vs Vicon: most joint angles RMSE under 4°. Another study found mean bias under 10° **except shoulder abd/add and elbow flexion/extension**. — [PMC8782534](https://pmc.ncbi.nlm.nih.gov/articles/PMC8782534)
- IMU accuracy decreases for fast and complicated limb movements (TEA Ergo IMU, RMSE ≤ 8.0°). — search summary pointing to [Cerfoglio et al. Sensors 2023](https://re.public.polimi.it/retrieve/bd9a6eda-0eb8-4720-84c6-e6943aabbd57/Cerfoglio_Sensors_2023b.pdf) (attribution of this specific quote is uncertain; verify)
- IMU vs optical elbow flexion RMSE 5.2 ± 2.1° (generic IMU study). — [search summary; sportsmedicine-open table](https://sportsmedicine-open.springeropen.com/articles/10.1186/s40798-018-0167-7/tables/3) (verify)
- Valor IMU vs Vicon: MAD 1.81–17.46° and RMSE 1.89–16.62° across joints and tasks. Magnetic fields, drift and inappropriate calibration are cited as error sources. — [Smith et al. 2024, Sensors](https://consensus.app/papers/details/8fef8a8c838c587299bfe3fe6d3ea130/?utm_source=claude_code)
- MIMU elbow error under magnetic disturbance (with an anti-disturbance fusion) reached up to 3.67° RMSE per axis. — [Gu et al. 2023, IEEE Sensors J](https://consensus.app/papers/details/002747ad0ffd5bbba74c7bce81029a2a/?utm_source=claude_code)
- Long complex tasks gave 2.8° vs 1.2° mean RMSE for short functional tasks (IMU vs optical). — [Robert-Lachaine et al. 2017](https://pharesst.irsst.qc.ca/etudes-primaires/139)
- Rokoko practice:
  - The magnetic field should fluctuate by no more than about **±0.15 Gauss**; yellow sensor indicators flag interference; walk the space to find hot spots. — [Rokoko support: degaussing](https://support.rokoko.com/hc/en-us/articles/44474445861521-Degaussing-your-space-A-guide-to-magnetic-interference); [Coil Pro troubleshooting](https://support.rokoko.com/hc/en-us/articles/23429480051217-The-Coil-Pro-Troubleshooting-Guide)
  - Sensor Fusion 2.0 (hub firmware 2.7.0.3) is said to reduce drift in magnetic environments but not eliminate it. — [Rokoko](https://rokoko.com/insights/sensor-fusion-2-0-more-accuracy-less-drift)
  - Calibrate away from metal. — [fxguide](https://www.fxguide.com/?p=190805); [HKU lab guide](https://bookstack.hku.nl/books/motion-capture-motion-tracking/page/how-to-rokoko/export/plaintext)

### Inferences
- Checklist:
  - Check the magnetic field (±0.15 G) at the performance spot.
  - Clear phones and tripods of metal near the forearms.
  - Calibrate the suit immediately before the take, in the performance spot, with a carefully held calibration pose (arms straight; the elbow reference depends on it).
  - Keep the take short (under a few minutes).
  - Record static poses before and after; the difference between them estimates drift and goes into the uncertainty budget.
  - Check that the forearm and upper-arm sensor straps are tight (sensor-to-segment slip).
- The elbow is specifically flagged as a higher-bias joint for some IMU suits (Perception Neuron), so the suit side may contribute several degrees by itself. It should get its own uncertainty term in the Monte Carlo, not be treated as truth.

### Gaps
- No independent, peer-reviewed, well-powered Rokoko elbow validation was found. The 0.51° figure is surprisingly low and comes from a weakly documented record.
- No numbers for elbow error vs angular velocity for Rokoko-class suits.

---

## 6. Directly measuring motion-time keypoint error (manual labelling)

### Takeaway
Still-frame jitter underestimates error during fast, blurred or occluded motion. Hand-label a stratified subset of motion frames in both views, compare against RTMW, and use the resulting error distribution (heavy-tailed, not Gaussian) in the Monte Carlo. Literature on human inter-annotator pixel error at elbows and wrists is thin; COCO's per-keypoint tolerances came from redundant annotation of 5,000 images.

### Cited Findings
- COCO OKS per-keypoint constants (ki = 2σi) were tuned from per-keypoint standard deviations relative to object scale, using 5,000 redundantly annotated validation images. Wrists have larger σ than eyes. — [LearnOpenCV OKS explainer](https://learnopencv.com/object-keypoint-similarity/)
- Human pose-annotation agreement collapses at strict thresholds, showing a floor on human precision. — [KαLOS, arXiv 2603.27197](https://arxiv.org/pdf/2603.27197)
- Markerless upper-body keypoint holdout RMS error was about 3.4–7.0 px (about 1 px ≈ 1 cm in that setup). — [search summary, PMC9023453 table](https://pmc.ncbi.nlm.nih.gov/articles/PMC9023453/table/Tab5) (verify context)
- Depth errors in stereo are heavy-tailed, so they should not be modelled as Gaussian. — [Abdelsalam et al. 2024](https://consensus.app/papers/details/6c8887e3cc72505c87d750db8608a5d8/?utm_source=claude_code)
- Annotators disagree on occluded joints. — [Supancic et al., arXiv 1504.06378](https://arxiv.org/pdf/1504.06378)

### Inferences
- Labelling protocol:
  - Use CVAT or Label Studio with skeleton templates.
  - Label shoulder, elbow and wrist in both views on about 100–200 frames, stratified by wrist speed tercile and occlusion state. This gives a stable estimate of the mean and 95th percentile per joint.
  - Have 2 annotators label about 30 overlapping frames, or one annotator twice a week apart, to estimate the annotator floor, and subtract that variance.
  - Feed the empirical (bootstrapped) residuals, conditioned on speed, into the Monte Carlo instead of Gaussian still-frame jitter.
  - Also triangulate the manual labels themselves: an elbow angle from manual 2D labels vs the suit gives a direct check that separates detector error from calibration, sync and definition error.
- The sample-size figure (100–200) is my estimate, not literature-derived.

### Gaps
- COCO's exact elbow and wrist σ values were not confirmed from a fetched primary source in this session (commonly cited as about 0.072 elbow and 0.062 wrist in cocoapi; **unverified here**).
- No published study of inter-annotator pixel error specifically for elbows and wrists in signing video.

---

## 7. Analysis choices that keep the test honest

### Takeaway
Report bias and dynamic agreement separately, propagate every error source (keypoints, calibration, sync, suit drift, definition offset), pre-register the offset and sync rules, and treat the suit as a second imperfect instrument rather than ground truth.

### Cited Findings
- Comparing two indirect systems gives an upper bound on error, not absolute accuracy. — [Francia et al. 2026, Sensors](https://consensus.app/papers/details/0cd0a4a588bd51eaa1a1ee7e867a5563/?utm_source=claude_code)
- Report RMSD with and without offset (RMSDoffset). — [Wren et al. 2023](https://consensus.app/papers/details/671c9d767b3c56548b02cb1958ea198f/?utm_source=claude_code)
- Use SPM and nested Bland-Altman to locate time-varying and proportional bias. — [Uchida et al. 2026](https://consensus.app/papers/details/7c4f17fad7ec5204b4c9bdb1147dc0aa/?utm_source=claude_code)
- Use post-triangulation reprojection error as the calibration-quality check. — [Pose2Sim issue #33](https://github.com/perfanalytics/pose2sim/issues/33)

### Inferences
- In a single take, frames are autocorrelated, so the TOST must use an effective sample size (block bootstrap, or the Monte Carlo over the whole pipeline) rather than per-frame n.
- Filter both signals identically: the same 6 Hz Butterworth on suit and video. Otherwise the filter difference becomes "disagreement".
- Pre-register:
  - the outlier/dropout rule (for example, frames where either view's confidence is below threshold are excluded and their count reported)
  - the offset rule
  - the sync method
  - which suit skeleton is used (raw, not retargeted)

### Gaps
- No literature found on applying TOST to a single-take, autocorrelated kinematic comparison specifically.
