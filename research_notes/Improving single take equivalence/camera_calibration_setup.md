# Camera setup, calibration and synchronisation for low-cost two-phone (few-phone) 3D upper-body joint angles

Scope note: published evidence is almost entirely about lower-limb gait/sport kinematics; no study found
quantifies these factors for upper-body signing. Numbers marked "(computed)" in the Inferences come from
small geometric calculations run for these notes (orthographic two-view model, project `.venv` numpy); they
are illustrations of mechanism, not literature results.

## Q1. Board-based calibration that costs almost nothing (ChArUco on a screen, printed A4 board, anipose/Pose2Sim/OpenCap workflows) vs body-keypoint self-calibration

### Takeaway
Every validated low-cost system (OpenCap, Pose2Sim, anipose) uses a planar target for calibration, not body
keypoints; OpenCap gets 4.5° mean joint-angle error with two iPhones using pre-stored intrinsics plus a single
image of an A4-printed checkerboard for extrinsics. Keypoint-only calibration methods in the literature still
show ~10–15% focal errors and degree-level rotation errors, which is exactly the failure mode SignSure sees.

### Cited Findings
- OpenCap (Uhlrich et al. 2023): intrinsics are preloaded per phone model from a database (computed with a precision 720×540 mm checkerboard); extrinsics are computed per session from a single image of a checkerboard; a 210×175 mm board printed on A4 is sufficient, and printed vs precision boards gave minimal kinematic differences. Extrinsic error grows with distance from the board (use a larger board or work near where it stood). — [Uhlrich et al. 2023, PLoS Comput Biol](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- OpenCap result with that calibration, two cameras at ±45°, 60 Hz, 720×1280: mean joint-angle MAE 4.5° (range 1.7–10.3°) over 18 rotational + 3 translational DOFs; marker error 32 mm; arm markers 39 mm mean error. No separate shoulder/elbow angle MAE reported in the main text. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- OpenCap forum advice from Uhlrich: board should be perpendicular to the ground, very flat, square size verified, shaded from direct sun; a larger board for large volumes; board can be oriented ~45° to the frontal plane so both cameras see it; translation errors (e.g. >20 cm step-length errors in a 15 m sprint) were attributed to inaccurate calibration. — [SimTK OpenCap forum](https://simtk.org/plugins/phpBB/viewtopic.php?p=48474); [forum thread](https://simtk.org/plugins/phpBB/viewtopic.php?p=48088)
- Pose2Sim docs: intrinsics once per camera from a chessboard/ChArUco filmed from many angles covering most of the frame (frames extracted from video, not photos, since formats can skew calibration); a 5×8-corner board on A4 suggested, ≥20 corners; target intrinsic error ≤0.5 px; ChArUco is more occlusion-robust but slightly less accurate (~0.5 px vs ~0.2 px for a chessboard); recalibrate after any zoom change. Extrinsic error should be <1 cm (acceptable up to 2.5 cm). Scene-landmark extrinsics (≥10 measured, well-spread 3D points) is "very accurate" and works with unsynchronised cameras; a single static board is the least accurate method; keypoint-based extrinsic calibration is listed as "coming soon". — [Pose2Sim documentation](https://perfanalytics.github.io/pose2sim/)
- Pose2Sim robustness study: a deliberate ~1 cm calibration error changed walking sagittal angles by only 0.19°, versus 0.90° for 4 vs 8 cameras and 1.5° for degraded images; all perturbations gave 0.35–1.6° MAE vs the reference condition. — [Pagnon et al. 2021, Sensors (Part 1)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8512754/)
- Anipose/aniposelib calibrates multiple cameras from a ChArUco board with iterative bundle adjustment minimising reprojection error. — [Aniposelib tutorial](https://anipose.readthedocs.io/en/latest/aniposelib-tutorial.html)
- ChArUco boards give lower projection error than marker-only or plain chessboard patterns in a vehicle-rig study (note: contradicts Pose2Sim's statement that chessboards are slightly more accurate; both agree on sub-pixel errors). — [arXiv 2601.14208](https://arxiv.org/pdf/2601.14208); [Pose2Sim docs](https://perfanalytics.github.io/pose2sim/)
- General ChArUco guidance: mean reprojection error <0.5 px is good; <0.3 px for stereo/depth work. — [Robotics Center tutorial](https://www.roboticscenter.ai/es/tutorials/calibrate-unitree-g1-cameras)
- Keypoint-based calibration (CasCalib 2024, sparse unsynchronised cameras): single-view focal errors 0.66–18.4% (≈11% average) across 4 cameras; pairwise rotation errors 0.8–10.7° even when synchronised; the authors skipped bundle adjustment in two-view experiments because "two views give insufficient constraints under noisy keypoints". — [CasCalib, arXiv 2405.06845](https://arxiv.org/html/2405.06845v1)
- Takahashi et al. use human joints as calibration correspondences for sync + extrinsics, later adding bone-length and smooth-motion priors; Choi et al. (ICCV 2025) extend "humans as a calibration pattern" to time offsets and poses. — [Takahashi et al. CVPRW 2018](https://openaccess.thecvf.com/content_cvpr_2018_workshops/html/Takahashi_Human_Pose_As_CVPR_2018_paper.html); [Choi et al. ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/papers/Choi_Humans_as_a_Calibration_Pattern_Dynamic_3D_Scene_Reconstruction_from_ICCV_2025_paper.pdf)
- A keypoint-based extrinsic method reported lower reprojection error than a target-based reference, but only reprojection error (not ground truth); keypoints are visible over wider view angles than a checkerboard. — [Online marker-free extrinsic calibration, arXiv 2209.07393](https://astro.paperswithcode.com/paper/online-marker-free-extrinsic-camera)
- Self-calibration from non-rigid objects such as human bodies makes parameter accuracy hard to guarantee; high-accuracy applications use dedicated targets. — [Berkeley multi-camera calibration paper](https://people.eecs.berkeley.edu/%7Eyima/psfile/TCAD_IROS_final_1_0.pdf)

### Inferences
- The SignSure symptoms (focal driven to 2.1×, baseline jumping 56°→65° when one bone definition changed, 4.6–7.3 px reprojection error) are what the literature predicts for two-view body-only calibration: the essential matrix has only 5 DOF and keypoint noise of several px plus bone-definition bias (keypoints ≠ joint centres) leaks into rotation and focal. A board removes the human model from calibration entirely, so changing a bone definition can no longer move the cameras.
- Cheapest high-value option: (a) per-phone intrinsics once from a printed A4 chessboard video (≥20 corners, cover the frame, ≤0.5 px); (b) per-take extrinsics from one A4/A3 board (or ChArUco on a laptop/tablet screen — rigid and perfectly flat, known square size, but check screen glare and that both phones see it) held at the signer's chest position, ideally several poses filmed by both phones (moving board in synchronised video = many correspondences). OpenCap shows even one static image is enough for ~4.5° joint-angle MAE.
- Scene-landmark extrinsics (tape-measured points on a wall/table, Pose2Sim style) is an alternative with zero printing and works unsynchronised.
- Keep keypoint self-calibration only as a refinement (bundle adjust extrinsics starting from the board solution, intrinsics fixed), and report the board-vs-keypoint difference as a calibration-uncertainty check.

### Gaps
- No head-to-head study found that measures 3D joint-angle error for board vs body-keypoint calibration on the same human data with ground truth.
- No quantitative study found on ChArUco shown on a phone/laptop screen vs printed board (only general guidance on flatness and known square size).
- OpenCap's S1 appendix (intra-/inter-phone intrinsic variability, sync accuracy) was not accessible in the fetched text.

## Q2. Measuring phone intrinsics once; locking focus/zoom; disabling stabilisation — how much does focal error matter?

### Takeaway
Validated systems treat intrinsics as known (OpenCap per-model database, Pose2Sim once per camera, ≤0.5 px).
A focal error itself is largely absorbed by camera distance under near-weak-perspective, but in two-view
self-calibration it couples to the estimated convergence angle, and a few-degree convergence-angle error
distorts joint angles by several degrees.

### Cited Findings
- OpenCap preloads per-device-model intrinsics and uses fixed focus distance during recording. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- Pose2Sim: intrinsics need computing once per camera lifetime but must be recomputed if you zoom. — [Pose2Sim docs](https://perfanalytics.github.io/pose2sim/)
- Smartphone autofocus changes intrinsics frame to frame: a spatiotemporal bundle-adjustment method solves per-frame intrinsics for smartphone footage because of autofocus. — [Spatiotemporal BA, arXiv 2007.12806](https://arxiv.org/pdf/2007.12806)
- Triangulation error is inversely proportional to baseline × focal length and scales with viewing distance. — [BMVC 1990](https://bmva-archive.org.uk/bmvc/1990/bmvc-90-048.pdf)
- Sensitivity study varying intrinsics up to ±15%: triangulation was more sensitive to underestimating focal length and to principal-point errors; for small combined errors, principal-point sensitivity exceeded focal sensitivity. — [Crowdsourced 3D mapping, arXiv 2007.12918](https://arxiv.org/pdf/2007.12918)
- In CasCalib's noise simulations, focal estimates from human keypoints only degraded strongly above ~80 px keypoint noise (mean focal ~437 px), yet real-data focal errors were still ~11% on average. — [CasCalib](https://arxiv.org/html/2405.06845v1)

### Inferences
- (computed) Two orthographic views at true convergence θ, reconstructed with a wrong θ′, give the linear map Z′ = Z·sinθ/sinθ′ + X·(cosθ − cosθ′)/sinθ′ (scale + shear in the depth plane). For SignSure's observed 56° → 65° shift: depth scale 0.915 and shear 0.151; the worst-case change of a 60–120° in-plane joint angle is ≈10°. A 5° error (60°→65°) gives ≤5.6°; a 2° error (60°→62°) gives ≤2.3°. This matches the "several degrees" elbow movement seen on real takes.
- (computed) Any residual anisotropic scale between depth and lateral axes changes in-plane angles by up to ≈2.8° (5%), 5.5° (10%) and 10.4° (20%). With a ±15° margin and a ~9° true RMS needed to pass, a 10% depth-scale error alone consumes a large part of the budget.
- Focal and camera distance are nearly confounded when the subject's depth extent (~0.5 m for arms) is small relative to distance (2–3 m); this explains why focal is unidentifiable from two views and why fixing it from a lens calibration removes a whole degree of freedom from the Monte Carlo calibration uncertainty.
- Practical: calibrate each phone once per resolution/lens (main 1× lens only; 0.5×/2× are different cameras), lock AE/AF (iOS: long-press AE/AF lock; Android: pro/manual mode), disable digital stabilisation (EIS crops and warps per frame, invalidating a fixed intrinsic model), and record in the same resolution/aspect used for calibration.

### Gaps
- No published measurement found of how much iPhone/Android EIS or "cinematic" stabilisation changes effective focal/principal point; the advice to disable it is engineering practice, not quantified here.
- No study found that directly maps a percentage focal error to joint-angle error in a human two-view setup.

## Q3. Camera count (2 vs 3 vs 4) and inter-camera angle (30°, 60°, 90°)

### Takeaway
Going from 2 to 3–5 cameras gave negligible kinematic gain in OpenCap (<0.3°) when occlusion is low, but
extra views help where occlusion occurs (arms crossing the body in signing). Convergence angle matters more:
guidance converges on ≥30° minimum, 45–90° preferred, and simple triangulation-noise geometry favours 70–90°.

### Cited Findings
- OpenCap: 3 cameras did not improve accuracy over 2; 5 cameras reduced marker error mildly (32→29 mm) with kinematic gains <0.3°. Validation cameras at ±70°, ±45°, 0°, 1.5 m high, 3 m from centre; main results used ±45° (≈90° between cameras). Recommended ±45° for squat/sit-to-stand/jumps, ±30° for walking. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- Uhlrich (forum): a third camera does not necessarily add accuracy for activities with little occlusion. — [SimTK forum](https://simtk.org/plugins/phpBB/viewtopic.php?p=48088)
- Pose2Sim: 4 vs 8 cameras changed walking sagittal angles by 0.90°. — [Pagnon et al. 2021](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8512754/)
- Pose2Sim docs: minimum 2 views; for two cameras and one person, best results with one camera in front and one 45° to the side at hip level (citing Samani et al. 2026); front + 90° side acceptable; for frontal/transverse-plane angles, front/back configurations recommended (citing Zhao et al. 2026); ~6 cameras generally good; top views poor. — [Pose2Sim docs](https://perfanalytics.github.io/pose2sim/)
- Finger-angle study: removing cameras from a 4-webcam rig changed joint angles by up to 20°, but well-placed 2-camera pairs stayed within ~4° of the 4-camera result. — [search summary of hand webcam study, PLoS ONE 2023](https://doaj.org/article/46e7e953a98e4187a0bd28b5f4635451)
- Two-webcam OpenPose gait system with linear triangulation: sagittal angle errors up to 14.0° ± 1.8°; authors attribute to keypoint error and camera configuration. — [Heidelberg record](https://heibib.ub.uni-heidelberg.de/search/Record/1772141089)
- Multiview confidence-interval study: CIs on joint angles narrowed with more cameras; median effect small, but with fewer cameras occlusions made uncertainty at particular joints/times much larger than median. — [arXiv 2502.06486](https://arxiv.org/pdf/2502.06486)
- Qualisys: angle between two cameras ideally >60°, at least 30°; below 30°, two-camera 3D can degrade below usable levels. — [Qualisys camera positioning](https://docs.qualisys.com/qtm/content/system_setup/camera_positioning.htm)
- Classic photogrammetry: recommendations of ≥60°, preferably ≥90° convergence. — [Abdel-Aziz 1974, PE&RS](https://asprs.org/wp-content/uploads/pers/1974journal/nov/1974_nov_1341-1346.pdf)

### Inferences
- (computed) For two views, depth-noise amplification relative to image noise is √(1+cos²θ)/sinθ: 4.0× at 20°, 2.65× at 30°, 1.73× at 45°, 1.29× at 60°, 1.12× at 70°, 1.0× at 90°. Moving from ~56° to ~80–90° cuts depth noise by ~25% and also makes the rotation better conditioned for calibration.
- For signing (hands in front of the torso, arms crossing), occlusion is the main argument for a third phone (e.g. front + left 60–90° + right 60–90°): it rescues frames where one side view loses the far hand, and gives three-view redundancy for outlier rejection. Expected gain in median error is small (OpenCap/Pose2Sim <1°), but tail errors and Monte Carlo spread should shrink. A third phone also makes self-calibration far better constrained than two views (CasCalib note).
- Avoid placing the second phone >~110° (near-opposite views make left/right keypoint swaps and mirror ambiguities more likely).

### Gaps
- No upper-body/signing study found that varies camera angle systematically; Samani et al. 2026 and Zhao et al. 2026 (cited by Pose2Sim) could not be retrieved.
- No Theia3D camera-subset results were found (a KIT thesis on omitting cameras exists but results unavailable: [KIT](https://hcr.iar.kit.edu/236.php)).

## Q4. Synchronisation: clap/flash/timecode apps vs motion cross-correlation; effect of a 1-frame offset

### Takeaway
Software sync apps achieve sub-millisecond phone-to-phone alignment; a visual flash event gives ≤1 frame;
motion cross-correlation (OpenCap, Pose2Sim, SignSure) is standard but residual offsets of a frame are
common. A 1-frame offset at fast arm speeds gives several degrees of angle error, so sub-frame sync is a
large, cheap win.

### Cited Findings
- Ansari et al. (Google, ICCP 2019): software-only WiFi sync of smartphone cameras with <250 µs accuracy (clock alignment then phase alignment of frame streams); open-source Android `libsoftwaresync`. — [arXiv 1812.09366](https://arxiv.org/pdf/1812.09366)
- Akhmetyanov et al. 2021: sub-millisecond (<300 µs) synchronised video recording across multiple Android smartphones (RecSync-style app); phase sync of professional cameras normally needs hardware triggers unavailable from smartphone APIs; frame times modelled as phase + index×period + random error, with frame drops. — [arXiv 2107.00987](https://arxiv.org/pdf/2107.00987)
- Twist-n-Sync: gyroscope-based microsecond-level sync, requires phones to be shaken together physically. — [GitHub](https://github.com/MobileRoboticsSkoltech/twist-n-sync)
- OpenCap synchronises by cross-correlating keypoint velocities across cameras (no accuracy figure in main text). — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- Pose2Sim sync: correlates mean vertical keypoint speed; works best with clear vertical motion, ≥5 s, no movement toward/away from cameras; keep recordings to a few minutes because clocks drift; prefers visual events (flashlight) over audio (clap) because sound is slower than light; no accuracy figure given. — [Pose2Sim docs](https://perfanalytics.github.io/pose2sim/)
- CasCalib: keypoint-based offset estimation was within ~5 frames on multi-person datasets and ±10 frames std on Human3.6M; unsynchronised pairs gave camera rotation errors up to 13–73° versus 0.8–17° after sync. — [CasCalib](https://arxiv.org/html/2405.06845v1)
- Spatiotemporal bundle adjustment: standard triangulation is invalid for moving points in unsynchronised video; modelling sub-frame offsets significantly improved body fitting over assuming synchronised capture. — [arXiv 2007.12806](https://arxiv.org/pdf/2007.12806)

### Inferences
- (computed) A timing offset Δt produces an inter-view inconsistency of v·Δt. For a 0.25 m forearm, the induced angle perturbation scale ≈ v·Δt/L: at 1 m/s wrist speed, 8 ms → 1.9°, 17 ms → 3.8°, 33 ms → 7.6°; at 2 m/s these double (up to ~15° for a 33 ms offset). Errors concentrate at peak-velocity frames, i.e. exactly where RMS is dominated in signing.
- Sound travels ~0.34 m/ms, so a clap 3 m from one phone and 1 m from the other adds ~6 ms skew; a phone-screen flash or LED visible to both cameras is better; but any single event is quantised to the frame (±½ frame) unless sub-frame interpolated. Recording both phones at 60 fps halves the quantisation versus the current 480p/30 fps phone.
- Best cheap combination: event marker (flash/ sharp hand clap seen in video) for coarse sync, keep the existing geometric refinement for sub-frame estimate, and resample both streams to a common time base using actual frame timestamps (see Q5).

### Gaps
- No study found that measures joint-angle error as a function of frame offset for human markerless capture; the numbers above are a first-order geometric estimate.
- No published peak wrist/forearm speeds for ISL signing were retrieved (the 0.5–2 m/s range is an assumption to check against the FBX).

## Q5. Rolling shutter and variable frame rate on phones

### Takeaway
Phone sensors read out over ~5–25 ms per frame, which acts like a row-dependent sync offset; VFR recording
breaks the "index × period" timing assumption. Neither is quantified for human joint angles in the
literature, but both are of the same order as a 1-frame sync error and are cheap to mitigate.

### Cited Findings
- Readout time examples: iPhone 4s 30 fps measured at 22.08 ms (LED-flicker method); iPhone 15 Pro ~5 ms (unverified blog figure); conventional CMOS often 15–25 ms. — [Linköping rolling-shutter tutorial](https://www.cvl.isy.liu.se/education/tutorials/rolling-shutter-tutorial/pdf/Intro30m.pdf); [Wolfcrow guide](https://wolfcrow.com/the-essential-guide-to-rolling-shutter-what-you-need-to-know/)
- A 2026 smartphone sub-frame timing study measured ~6.58 µs per row (≈7 ms for 1080 rows; ≈3 ms for 480 rows if the same sensor timing applied — phone unspecified). — [arXiv 2605.29118](https://arxiv.org/pdf/2605.29118)
- Naive global-shutter reconstruction from rolling-shutter stereo gives biased geometry even under mild motion; error depends on depth. — [Saurer et al. ICCV 2013](https://openaccess.thecvf.com/content_iccv_2013/papers/Saurer_Rolling_Shutter_Stereo_2013_ICCV_paper.pdf)
- Global-shutter methods perform severely worse when rolling shutter is not modelled (visual-inertial smartphone tracking). — [Li & Mourikis 2013](https://intra.ece.ucr.edu/~mourikis/papers/Li2013ICRA_b.pdf)
- Phone frame timing includes random error and frame drops. — [arXiv 2107.00987](https://arxiv.org/pdf/2107.00987)
- VFR footage displays frames at uneven intervals and is usually converted to CFR before analysis to prevent sync problems. — [Cloudinary glossary](https://cloudinary.com/glossary/variable-frame-rate)
- Pose2Sim: below 60 Hz accuracy drops, especially for fast motion. — [Pose2Sim docs](https://perfanalytics.github.io/pose2sim/)

### Inferences
- Rolling shutter: when the two phones are in the same orientation, the hand and elbow are at similar image heights in both, so much of the readout delay is common and partly absorbed by the sync offset; residual skew between wrist and shoulder rows (a few ms) is ≲1° at 1 m/s by the Q4 formula. Portrait vs landscape mismatch between phones (rows run along different body axes) would make this worse — keep both phones in the same orientation.
- VFR: phones often drop to lower frame rates in low light (auto exposure lengthens exposure). Use bright light, lock 60 fps, and read real presentation timestamps (ffprobe `pts_time`) rather than assuming constant 1/fps; resample to a common grid before triangulation.
- Fast shutter (≤1/500 s) reduces motion blur, which otherwise biases keypoints along the motion direction at peak speed.

### Gaps
- No study found quantifying rolling-shutter or VFR effects on triangulated human joint angles.
- No reliable current-model iPhone/Android readout-time measurements from peer-reviewed sources.

## Q6. Recommended recording protocol from validated low-cost systems

### Takeaway
Consensus: 60 fps, ≥720p, fixed focus/exposure, known intrinsics, board extrinsics, 2–3 phones at ~45° each
side of frontal (≈90° between them), 2–10 m distance, tripods at chest/hip height, uncluttered bright scene.

### Cited Findings
- OpenCap: 720×1280 at 60 Hz, fixed focus, cameras ≥2 m (2–10 m working range; 10 m may need high-accuracy pose settings), validation cameras 1.5 m high, 3 m from subject. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- OpenCap pose-model sensitivity at two cameras: OpenPose high-accuracy 4.3°, HRNet 4.5°, OpenPose default 4.7° MAE. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- Pose2Sim: keep frame rate high (<60 Hz hurts fast motion); 1080×1920 → 720×1280 has little effect on accuracy; CRF 20→30 compression virtually no effect; uncluttered background, good lighting; tripods can be mistaken for people. — [Pose2Sim docs](https://perfanalytics.github.io/pose2sim/)
- Pose2Sim accuracy (8 cameras, lower body): mean errors 3.0° walking, 4.1° running, 4.0° cycling. — [Pagnon et al. 2022, Sensors (Part 2)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9002957/)
- Upper-limb single-camera / smartphone references for context: Azure Kinect + OpenSim shoulder elevation RMSE ~8°; BlazePose smartphone shoulder abduction MAE 8.3°. — [PMC12416023](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12416023/); [Jornadas de Automática](https://revistas.udc.gal/index.php/JA_CEA/article/download/13777/9845/57840)

### Inferences
- For SignSure (upper body only): frame from hips to above head so the arms fill most of the image height (more px per segment than full-body framing at 3 m); 1.5–2.5 m distance is acceptable when the field of interest is the upper body, but stay ≥ the distance used for lens calibration focus lock.
- Replace the 480p/30 fps phone or set it to 1080p/60 fps: 480p roughly halves pixels per segment versus 1080p framing of the same volume, so the same 3 px keypoint noise is ~2× larger in metres (Pose2Sim's "720p is enough" applies to whole-body framing; below 720p it is untested).
- Include in each take: 2–3 s board sweep visible to both phones at the signer's position, a flash/visible clap, 1–2 s still hold before and after the sign (already in protocol), then the sign.

### Gaps
- No validated protocol specifically for signing/hand-dominant upper-body motion found.

## Q7 (objective). Ranking of cheap improvements by expected effect on joint-angle error and calibration uncertainty

### Takeaway
Ranked by expected effect for SignSure's current failure modes: (1) known intrinsics + board extrinsics,
(2) better convergence angle (~80–90°) and/or a third phone, (3) sub-frame sync (sync app or visual event,
both phones 60 fps CFR), (4) camera hygiene (lock focus/exposure, no stabilisation, fast shutter,
≥720p on both phones), (5) rolling-shutter/orientation matching.

### Cited Findings
- Calibration from targets: OpenCap reaches 4.5° MAE with 2 phones using per-model intrinsics and one A4 board image. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462)
- Once calibration is target-based and ~1 cm accurate, residual calibration error contributes only ~0.2° (walking sagittal). — [Pagnon et al. 2021](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8512754/)
- Keypoint-only calibration: ~11% focal error and up to ~10° pairwise rotation errors in real data even with sync. — [CasCalib](https://arxiv.org/html/2405.06845v1)
- More cameras: <0.3° gain beyond 2 when occlusion is low (OpenCap); 0.9° for 4 vs 8 (Pose2Sim); larger gains in occluded frames. — [Uhlrich et al. 2023](https://journals.plos.org/ploscompbiol/article?id=10.1371/journal.pcbi.1011462); [Pagnon et al. 2021](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8512754/); [arXiv 2502.06486](https://arxiv.org/pdf/2502.06486)
- Sync apps: <250–300 µs. — [arXiv 1812.09366](https://arxiv.org/pdf/1812.09366); [arXiv 2107.00987](https://arxiv.org/pdf/2107.00987)

### Inferences
- Rank 1 — intrinsics measured once per phone (A4 chessboard video, ≤0.5 px) + board extrinsics per take: removes focal from the unknowns (fixing the 2.1× focal drift), decouples cameras from bone definitions (fixing the 56°→65° baseline shift, worth up to ~10° worst-case in-plane angle change by the computed shear model), and should cut reprojection error from 4.6–7.3 px towards the 1–3 px keypoint-noise floor. Expected effect: several degrees of systematic angle error removed and a much narrower calibration component in the Monte Carlo. Cost: one printed sheet, ~10 min per phone once.
- Rank 2 — geometry: second phone at 70–90° from the frontal phone (depth-noise factor 1.12–1.0 vs 1.32 at 56°, computed) and optionally a third phone on the other side for occlusion/redundancy. Expected effect: ~10–25% less triangulation noise; fewer occlusion outliers for the far hand.
- Rank 3 — sync: a sync app (Android libsoftwaresync/RecSync) or a visible flash plus both phones at 60 fps CFR. Expected effect: at 1–2 m/s hand speed, going from ~1 frame at 30 fps (33 ms) to sub-frame (<8 ms) removes roughly 5–10° peak-frame perturbation (computed, first-order), most relevant to RMS at peak velocity frames.
- Rank 4 — capture hygiene: AE/AF lock, stabilisation off, shutter ≤1/500 s, bright light (prevents VFR drops), same orientation and ≥720p (ideally 1080p) on both phones. Individually small, but they keep the fixed-intrinsics model valid and keypoint noise near ~1–3 px.
- Rank 5 — rolling-shutter modelling: likely ≲1° when both phones share orientation; only worth modelling after ranks 1–4.
- The ranking is an inference combining literature (lower-limb) with first-order geometry; it should be checked on SignSure's own simulation (`single_take_simulation.py`) by perturbing focal, convergence angle and sync offset separately.

### Gaps
- No upper-body or sign-language study directly validates this ordering; magnitudes for Ranks 2–5 are computed approximations.
