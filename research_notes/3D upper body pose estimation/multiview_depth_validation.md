# Markerless 3D Upper-Body and Hand Keypoints Beyond a Single RGB Camera: Multi-View, Depth Sensors and Validation Accuracy (as of Oct 2026)

## Multi-view triangulation tools (Pose2Sim, OpenCap, Anipose, FreeMoCap, EasyMocap, Theia3D): cameras, calibration, 2D backends, hands

### Takeaway
Pose2Sim is the most flexible open-source option for this use case. It works from 2 or more calibrated cameras, uses RTMPose (via RTMLib) by default, and can track hands with the 133-keypoint whole-body model. It also runs OpenSim IK to produce joint angles. OpenCap uses 2 iPhones and is validated mainly for the lower limb; its upper-extremity accuracy is weak. EasyMocap fits SMPL-X/MANO hands but looks unmaintained since about 2022. Theia3D is commercial and has the most published upper-limb validation.

### Cited Findings
- **Pose2Sim, cameras:** at least 2 viewpoints are required. About 6 cameras are recommended in general, more for complex motion or occlusion — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)
- **Pose2Sim, calibration:** intrinsics come from a chessboard or ChArUco board. Extrinsics come from measured scene coordinates or a static board; moving-board and keypoint-based calibration are listed as "coming soon". It can convert calibrations from Caliscope, AniPose, FreeMoCap, Qualisys, OptiTrack, Vicon, OpenCap, EasyMocap and bioCV. Target errors are about 0.5 px or less intrinsic and under 1 cm extrinsic (2.5 cm still acceptable) — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)
- **Pose2Sim, 2D backends:** RTMPose through RTMLib (default), OpenPose (legacy; BODY_25B recommended), MediaPipe BlazePose (single person, via a conversion script), DeepLabCut, and AlphaPose (legacy). MMPose is "coming soon". DWPose is not mentioned by name — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)
- **Pose2Sim, hands:** the "Whole_body" model has 133 keypoints (body + face + hands). It is restricted to non-commercial use because of a training dataset. "Whole_body_wrist" keeps only 2 keypoints per hand. Hand and Face models can be loaded through RTMLib custom-model settings — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)
- **Pose2Sim, sync and IK:** cameras are synchronised by cross-correlating vertical keypoint speed. OpenSim scaling and IK run automatically using a model adapted from Beaucage-Gauvreau (2019). The README claims a "2-6° joint angle error" from peer-reviewed studies. For real-time single-camera use it points to Sports2D, which requires motion in the sagittal or frontal plane — [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)
- **Pose2Sim robustness (Pagnon 2021):** compared with the reference condition, joint angles changed by a mean absolute 0.35°–1.6° under degraded images, 4 vs 8 cameras, or 1 cm calibration error. For walking (sagittal) the errors were 1.5° (degraded image), 0.90° (4 cameras) and 0.19° (calibration) — [Pagnon et al. 2021, Sensors](https://consensus.app/papers/details/339cee43060c5ae6a19f3d4368fb9132/?utm_source=claude_code)
- **Pose2Sim accuracy vs markers (Pagnon 2022):** lower-limb only, 1 participant. Mean errors were 3.0° walking, 4.1° running and 4.0° cycling. A systematic 15° hip offset appeared in running. There was no upper-limb validation in this paper — [Pagnon et al. 2022, Sensors](https://consensus.app/papers/details/8ac7757bd5a556999b15ffdd599152fc/?utm_source=claude_code)
- **OpenCap:** 2 smartphones (iOS) plus cloud processing. Lower-extremity validation in return-to-sport tasks vs a 10-camera marker system gave a grand mean MAE of 3.85° and RMSE of 4.34° — [Turner et al. 2024, J Biomech](https://consensus.app/papers/details/9245df4285745451bb5953b029c5e7b1/?utm_source=claude_code)
- **OpenCap meta-analysis:** 11 studies, 184 participants. Pooled RMSE was 5.88°, falling to 5.20° after sensitivity analysis and 4.94° after trim-and-fill. Reliability was weaker for high-velocity and complex joint actions — [Çabuk et al. 2025, Biology of Sport](https://consensus.app/papers/details/f59b1304923c517d90baa460ab4de789/?utm_source=claude_code)
- **OpenCap scoping review (51 studies):** accuracy is higher for the lower than the upper extremity, higher in healthy than clinical populations, and best in the sagittal plane — [Zhang et al. 2026, Frontiers in Digital Health](https://consensus.app/papers/details/2213abd4e01f5014b3deaf0c8158090d/?utm_source=claude_code)
- **OpenCap upper body, overhead squat:** upper-body RMSE was about 36.7° (mean CMC 0.48), against 5.45° (CMC 0.93) for the lower body. This comes from a search snippet; the full text was not reviewed — [SKKU repository record](https://scholarx.skku.edu/item/fa60b317-005d-4e2b-89cd-fd2166b18730)
- **OpenCap user forum (anecdotal):** a user reported arm and elbow RMSE above 100°. Staff suggested reprocessing with the newer ISB-based shoulder model, which suggests the model version matters a great deal — [SimTK forum](https://simtk.org/plugins/phpBB/viewtopic.php?p=51537)
- **EasyMocap (ZJU):** fits SMPL, SMPL+H, SMPL-X and MANO, i.e. body + hand + face from multiple views. Demos use 23 cameras (ZJU-MoCap), 8 cameras (hands) and 8 consumer cameras (multi-person). 2D input comes from OpenPose or HRNet, with MediaPipe added in Dec 2021. The latest listed update is Nov 2022 — [EasyMocap GitHub](https://github.com/zju3dv/EasyMocap)
- **FreeMoCap:** calibrates with a ChArUco board (DICT_4X4_250) on top of Anipose's calibration code. Third-party summaries say it uses MediaPipe for 2D tracking. The current README names only the "skellytracker" dependency and makes no validation claims — [FreeMoCap blog summary](https://themenonlab.blog/blog/freemocap-open-source-motion-capture); [FreeMoCap GitHub](https://github.com/freemocap/freemocap)
- **Anipose:** handles 3D calibration (ChArUco), triangulation, filtering and visualisation. It was originally built for animal pose with DeepLabCut — [FreeMoCap blog summary](https://themenonlab.blog/blog/freemocap-open-source-motion-capture)
- **Caliscope:** automates multi-camera extrinsic calibration with bundle adjustment (6-DoF camera poses), and Pose2Sim can import its output — [Caliscope PyPI](https://pypi.org/project/caliscope/0.5.3); [Pose2Sim GitHub](https://github.com/perfanalytics/pose2sim)
- **Commercial multi-view, Captury:** 8 BTS cameras in markerless mode were compared with Xsens IMUs (not optical). Median elbow discrepancy was about 12° and shoulder under 8° (ICC ≥ 0.87) — [Francia et al. 2026, Sensors](https://consensus.app/papers/details/0cd0a4a588bd51eaa1a1ee7e867a5563/?utm_source=claude_code)

### Inferences
- If the existing pipeline already uses RTMPose or RTMLib, Pose2Sim is the lowest-friction way to add multi-view. Hand keypoints in 3D are available, but the whole-body model's licence is non-commercial, which matters for a product.
- OpenCap's pipeline is built around lower-limb biomechanics. Hand/finger keypoints are not part of its standard output (I did not verify this directly), and its upper-limb accuracy is poor or depends on the model version. It is a weak fit for elbow and hand work.
- EasyMocap is the only open tool reviewed here with a parametric hand model (MANO/SMPL-X). Its maintenance status is a risk.

### Gaps
- No peer-reviewed Pose2Sim validation of upper-limb or elbow joint angles against markers was found. The README's "2-6°" claim is a general figure.
- No independent validation of FreeMoCap or Anipose for human upper-limb angles was found.
- Whether OpenCap now offers hand keypoints, and the full results of the overhead-squat paper, were not verified.
- Theia3D's camera requirements (commercial docs) and hand support were not retrieved.

## Depth sensors (Azure Kinect / Orbbec Femto, RealSense, iPhone LiDAR + ARKit, ZED) and fusing 2D keypoints with depth

### Takeaway
Azure Kinect DK is discontinued (2023). Its successor is the Orbbec Femto Bolt (same depth module, with a K4A wrapper). Intel RealSense was spun out as an independent company in July 2025. The ZED SDK offers a 38-keypoint body model with simplified hands. Depth-sensor skeletons give about 5–15° angular error for upper joints, and ARKit body tracking errors are large and joint-dependent.

### Cited Findings
- **Azure Kinect status:** Microsoft ended Azure Kinect DK production in 2023 and moved the technology to partners. Orbbec's Femto Bolt uses the same depth module, and an API bridge (K4A wrapper) eases migration. The Femto Bolt has no 7-mic array — [MoguraVR](https://www.moguravr.com/azure-kinect-dk-discontinued/); [JetsonHacks](https://jetsonhacks.com/2024/07/07/orbbec-femto-bolt-a-microsoft-azure-kinect-replacement/); [Brand Hopper review](https://thebrandhopper.com/learning-resources/femto-bolt-review-definitive-azure-kinect-replacement/)
- **Body Tracking SDK on Femto Bolt:** a secondary source says the Microsoft Body Tracking SDK runs through the K4A wrapper. A Microsoft Q&A thread (2023) describes the Azure Kinect SDK as effectively unmaintained — [Brand Hopper](https://thebrandhopper.com/learning-resources/femto-bolt-review-definitive-azure-kinect-replacement/); [Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/1303648/azure-kinect-sdk-is-unmaintained)
- **Intel RealSense:** the spin-off was announced 8 Jan 2025 and became a standalone company around July 2025 with a $50M raise and about 130 staff. The product line continues outside Intel — [PCWorld](https://www.pcworld.com/article/2846867/realsenses-depth-camera-tech-spins-off-from-intel.html); [Vision Systems Design](https://vision-systems.com/embedded/article/55303384/intel-completes-realsense-spinoff); [Automate.org](https://www.automate.org/vision/industry-insights/after-completing-intel-spinoff-realsense-announces-50m-raise/aph)
- **ZED (Stereolabs):** BODY_38 includes feet, a simplified face and simplified hands. A forum thread reports jitter in the BODY_38/70 formats — [Stereolabs docs](https://stereolabs.com/docs/body-tracking); [ZED ROS 2 docs](https://docs.stereolabs.com/docs/integrations/ros-2/body-tracking); [Stereolabs community](https://community.stereolabs.com/t/unreal-engine-5-body-38-and-70-make-jittery-motion/2562)
- **Azure Kinect vs Vicon, upper joints:** angular MAE was about 5–15° for all upper joints. Accuracy was better for slow movements (n=26, reach and balance tasks) — [Antico et al. 2021, CMPB](https://consensus.app/papers/details/8263d82b4a085c54923e18d7d8711357/?utm_source=claude_code)
- **Azure Kinect, upper-body tasks vs Vicon (n=25):** the frontal camera position was most reliable and lighting had almost no effect. Lower-limb occlusion worsened upper-limb accuracy — [Brambilla et al. 2023, Heliyon](https://consensus.app/papers/details/525a8c5152c75e92b4bf6c5fc33c7f9d/?utm_source=claude_code)
- **Viewing angle matters for depth sensors:** Azure Kinect beat Kinect v2 and Orbbec Astra at non-frontal angles, while Kinect v2 was better at frontal (gait study) — [Yeung et al. 2021, Gait & Posture](https://consensus.app/papers/details/eb7d49505a6e511cbfe70102962ac0d4/?utm_source=claude_code)
- **RGB-D vs RGB:** MediaPipe (RGB) gave results close to Kinect v2 vs Qualisys, with lower dispersion and error "within the error range of short- and long-arm goniometers" — [de Sousa Melo et al. 2022, Sensors](https://consensus.app/papers/details/4708b27dc36b59519c4f1c7da89c8f7e/?utm_source=claude_code)
- **ARKit body tracking vs Vicon:** 10 subjects, 8 exercises. Weighted MAE was 18.80° ± 12.12° (range 3.75°–47.06° by joint and exercise), with mean Spearman ρ of 0.76. Full range of motion was poorly captured, but movement patterns were tracked — [Applied Sciences 2022 via DOAJ](https://doaj.org/article/6d61b23a9283450b845f1a3e77c1f072); [TUM portal](https://portal.fis.tum.de/en/publications/evaluating-3d-human-motion-capture-on-mobile-devices/)
- **iPhone 12 Pro LiDAR + ARKit in stroke (arm weakness):** benchmarked against Captury; this is a preliminary study only — [arXiv 2311.09716](https://arxiv.org/pdf/2311.09716)
- **ARKit developer reports:** issues with neck rotation and feet accuracy. Unity confirms the joint values come straight from ARKit — [Unity issue tracker](https://issuetracker-mig.prd.it.unity3d.com/issues/arkit-body-tracking-neck-joint-s-incorrectly-reports-rotations-when-the-scanned-person-rotates-their-head); [Apple forums](https://developer.apple.com/forums/thread/725730)

### Inferences
- Lifting 2D keypoints into 3D by sampling a depth map has some likely failure modes. These follow from the occlusion and viewing-angle findings above plus general depth-sensing physics; no paper here quantifies them for hands.
  - The depth sampled at a keypoint often lands on a different surface. At an occluded elbow it may hit the torso. At the wrist or fingers it may hit the background, because the depth edges get "flying pixels".
  - Thin structures like fingers fall below the effective depth resolution at typical 1–2 m range.
  - The depth stream and RGB stream have to be registered and time-aligned.
  - Depth is measured at the skin surface, not at the joint centre, which adds a systematic offset of about one limb radius.
- For fine hand articulation, hand-specific monocular 3D models or multi-view RGB with triangulation are likely better than sensor depth. Depth is more useful to fix global scale and arm depth.

### Gaps
- No peer-reviewed validation of Orbbec Femto Bolt body tracking, ZED BODY_38 or RealSense-based skeletons against marker-based upper-limb angles was found.
- No published shoulder- or elbow-specific error figures for ARKit body tracking were found.
- No study was found that quantifies hand-keypoint depth noise from fusing a 2D keypoint with a depth map.
- The current status of Orbbec's and the RealSense company's body-tracking SDKs (late 2026) was not checked against primary sources.

## Validation studies: RMSE/bias for elbow flexion and shoulder angles vs marker-based mocap or goniometer; TOST/SPM usage

### Takeaway
Multi-view markerless systems typically agree with marker-based mocap to within about 2–6° RMSE for elbow flexion/extension and shoulder elevation/abduction in controlled tasks. Shoulder internal/external rotation is much worse (about 15–22°). Systematic bias is common, especially underestimation of peak flexion. No published study was found that applies TOST equivalence testing or SPM-based equivalence to markerless vs marker-based elbow angles. SPM1d has been used to detect differences, not equivalence.

### Cited Findings
- **Theia3D, upper extremity in children (Box and Blocks):** RMSD of demeaned upper-extremity joint angles was under 6° for all joints. Between-system ICC was good (0.7–0.9), and Bland-Altman showed systematic bias — [Hansen et al. 2024, Biomedical Engineering Advances](https://consensus.app/papers/details/2c43500e8df45e6cabffd16853f2ac31/?utm_source=claude_code)
- **Theia3D, rotation sequence:** a related Virginia Tech thesis (Theia3D, Box and Blocks) found that agreement depends on the Euler rotation sequence chosen — [VTechWorks](https://vtechworks.lib.vt.edu/items/1979a50c-dc82-4375-8841-1608782859f5)
- **Theia3D, shoulder (20 healthy adults, v2024.1.24):**
  - RMS differences were under 6° for abduction and 15.3°–22.3° for external rotation.
  - CMC was mostly above 0.75, but weak for flexion during external rotation.
  - Range of motion differed significantly in all planes, though coronal- and sagittal-plane mean differences were within the minimal clinically important difference.
  - The URL is the likely full text, from snippets; the year was not confirmed — [Univ. Potsdam publication](https://publishup.uni-potsdam.de/files/57827/phr809.pdf)
- **Theia3D, boxing (3 elite boxers):** the elbow joint centre differed by more than 3 cm, against under 2.5 cm for shoulder and wrist. Internal/external rotation agreed worst; the shoulder performed best — [Frontiers Sports Act Living 2022, PMC9357930](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9357930/)
- **Captury (8 cameras) vs Xsens IMUs:** median discrepancy was about 12° for elbow flexion/extension and under 8° for shoulder flexion/extension, with ICC ≥ 0.87 and ρ ≥ 0.89. The authors judge it suited to movement patterns rather than absolute angles — [Francia et al. 2026, Sensors](https://consensus.app/papers/details/0cd0a4a588bd51eaa1a1ee7e867a5563/?utm_source=claude_code)
- **Markerless upper limb, full vs partial ROM, vs optoelectronic (n=10):**
  - ICC was above 0.91 for the elbow and above 0.94 for the shoulder.
  - Maximum flexion was systematically underestimated, especially at the shoulder, attributed to occlusion and joint geometry.
  - The wrist had the lowest RMSE.
  - The abstract does not give exact RMSE values or name the system.
  - [Francia et al. 2026, Applied Sciences](https://consensus.app/papers/details/9fabcdafd4645eb7ac96cfb586d2f6b9/?utm_source=claude_code)
- **Stroke patients (15), webcams with differentiable biomechanics vs optical mocap (drinking task):** median RMSE was 2–5° for joint angles, with an IQR of trial-to-trial bias around 1–3° and median r above 0.95 — [Cotton et al., arXiv 2411.14992](https://arxiv.org/abs/2411.14992)
- **2 high-speed cameras, DeepBehavior vs Qualisys during reaching (n=4):** elbow MAE was about 2°. Error rose when the elbow was occluded in one camera. This is a preprint — [Avni et al. 2023, bioRxiv](https://www.biorxiv.org/content/10.1101/2023.03.16.532711v1)
- **IMU + monocular MediaPipe calibration vs optical mocap:** shoulder and elbow RMSE 5.13–7.86°, r above 0.96 — [Li et al. 2023, Sensors & Actuators A](https://consensus.app/papers/details/8aba065f01fc5f6789b1f55bfc5c04e1/?utm_source=claude_code)
- **SPM usage:**
  - An equestrian study used SPM paired t-tests and found significant elbow flexion differences for markerless vs marker-based during walking — [UCLan repository](https://clok.uclan.ac.uk/55378)
  - In cricket, SPM1d was used on elbow flexion/extension waveforms, but between marker-registration methods (RMSE 8.9° vs 25.1°), not markerless — [ISBS proceedings](https://ojs.ub.uni-konstanz.de/cpa/article/view/6337)
- **TOST:** no study was found that applies TOST, or SPM with equivalence bounds, to markerless vs marker-based upper-limb angles. This is based on targeted searches — [search of Consensus/web, this note]

### Inferences
- A plausible equivalence margin for elbow flexion is about ±5°. That is in line with the error range of goniometers and marker-based systems that these papers use as benchmarks. Multi-view systems in controlled tasks would plausibly pass it; monocular and depth-sensor systems often would not.
- Combining TOST on summary metrics with SPM1d on waveforms for markerless upper-limb validation looks novel relative to the published literature found.
- Report bias (Bland-Altman) and ROM differences separately from RMSE. Several studies show good waveform correlation alongside a systematic peak underestimation.

### Gaps
- Studies reporting elbow-flexion RMSE specifically from Pose2Sim, OpenCap (new shoulder model) or FreeMoCap against Vicon/OptiTrack were not found.
- No direct goniometer-vs-multi-view study for the elbow was found.
- Full-text numbers for Hansen 2024 (per-joint RMSD) and the boxing study were not extracted; PMC blocked fetching.

## Monocular vs multi-view accuracy gap for upper-limb angles

### Takeaway
Monocular 3D errors are much larger and depend heavily on viewpoint. 3D joint position errors reach 146–249 mm, and ARKit MAE about 19° on average. Multi-view triangulation typically gets 2–6° RMSE for elbow and shoulder flexion and abduction. The gap is largest for out-of-plane motion and for shoulder rotation.

### Cited Findings
- **11 open-source monocular estimators vs optical mocap (Physio2.2M, 25 participants):** MPJPE was 72–122 mm in 2D and 146–249 mm in 3D. Elbow flexion MAE was reported for 2D and 3D, but the values were not rendered in the abstract, so they are missing here. Inference ran at 25–200 FPS (direct) and 117–9341 FPS (lifting) — [Rode et al. 2025, Scientific Reports](https://consensus.app/papers/details/a823db339dd65b2ba2abd8a8159e1b2f/?utm_source=claude_code)
- **Monocular MediaPipe 3D vs marker-based, upper-limb ROM tasks (n=10):** accuracy depends strongly on camera azimuth.
  - Elbow is best at 90° and 135° camera positions; shoulder at 135°, 180° and 315°.
  - The wrist was least accurate.
  - MediaPipe "tilt" with distance is a noted issue.
  - [Kim et al. 2025, IEEE Access](https://consensus.app/papers/details/fcc7f9ebfa815bc788c0b277ec185521/?utm_source=claude_code)
- **Monocular ARKit (RGB + LiDAR):** MAE 18.8° ± 12.1° (3.75°–47.06°) — [Applied Sciences 2022](https://doaj.org/article/6d61b23a9283450b845f1a3e77c1f072)
- **Multi-view references:**
  - Webcam multi-view in stroke: 2–5° median RMSE — [arXiv 2411.14992](https://arxiv.org/abs/2411.14992)
  - 2-camera reaching: elbow about 2° MAE — [Avni et al. 2023](https://www.biorxiv.org/content/10.1101/2023.03.16.532711v1)
  - Theia3D: under 6° — [Hansen et al. 2024](https://consensus.app/papers/details/2c43500e8df45e6cabffd16853f2ac31/?utm_source=claude_code)
  - Pose2Sim lower limb: 3–4° — [Pagnon 2022](https://consensus.app/papers/details/8ac7757bd5a556999b15ffdd599152fc/?utm_source=claude_code)
- **Multi-view still fails under occlusion:** with 2 cameras, elbow error rose when the elbow was occluded in one view — [Avni et al. 2023](https://www.biorxiv.org/content/10.1101/2023.03.16.532711v1)
- **Fewer cameras is acceptable within reason:** dropping from 8 to 4 cameras changed Pose2Sim angles by under 1° in walking — [Pagnon 2021](https://consensus.app/papers/details/339cee43060c5ae6a19f3d4368fb9132/?utm_source=claude_code)

### Inferences
- A rough rule from these sources: elbow flexion/extension is about 2–6° RMSE with 2+ calibrated views, about 5–15° with an RGB-D skeleton, and about 5–20° or more with monocular 3D lifting, depending heavily on viewpoint. Shoulder axial rotation is unreliable in all markerless modes.
- For a single-camera product, the main lever is placing the camera so the elbow flexion plane faces it roughly perpendicular. Adding a second calibrated camera is probably the largest single accuracy gain for elbow and shoulder angles.

### Gaps
- No single study was found that directly compares monocular and multi-view upper-limb angles against the same marker-based reference with the same participants.
- Rode et al.'s exact elbow MAE values were not recoverable from the abstract.
- Accuracy for hand and finger joint angles (MCP/PIP flexion) from multi-view markerless vs markers was not covered by any source found.
