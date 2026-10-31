# Synchronising two consumer-phone videos and a Rokoko Smartsuit FBX (target: well below one video frame)

Scope: synchronisation only (video↔video and video↔IMU suit). Frame periods for reference: 30 fps = 33.3 ms, 60 fps = 16.7 ms, so "well below one frame" means roughly ≤ 5 ms for the 60 fps pair and ≤ 10 ms overall. Current SignSure state (from the brief, not re-researched): wrist-speed cross-correlation + quarter-frame geometric refinement for video↔video; 3D wrist-speed cross-correlation for video↔FBX, agreeing within ~8 ms with an elbow-angle-rate alternative.

Research budget note: about 20 tool calls; several primary papers (PMC, MDPI, Rokoko support pages) returned 403 or bot-check pages, so a few numbers come from search snippets and are flagged as such.

## Event-based protocol cues (clap, flash/LED, sharp sync gesture): precision and lab practice

### Takeaway
A *visual* impulsive event (flash, LED, slap/punch with a sharp velocity peak) is the most reliable cheap cue; light-based sync matched a dedicated LED clock at 60 fps in one benchmark, while audio-based sync was worse than a frame. Clapping is weak for IMU alignment (~17 ms in one thesis) because it excites only a local upper-body motion; whole-body impulsive movements align better (~5 ms). Event cues are resolved only to the frame unless refined by sub-frame interpolation or rolling-shutter-aware decoding.

### Cited Findings
- Pose2Sim's documentation recommends, for its keypoint-based sync, a "sharp vertical movement" by the participant, not moving towards/away from the cameras, a capture of at least 5 s and at most a few minutes (cameras may drift); as alternatives it lists a flashlight, a clap or another clear visual/audio event, and says visual events are preferred because sound travels more slowly than light — [Pose2Sim README](https://github.com/perfanalytics/pose2sim)
- OpenCap developers describe a hand raise-and-lower as a "fail-safe" way to sync cameras; a "punch" must be upward enough for the code to track wrist and shoulder positions and must contain a velocity signal; cyclic movements are problematic because the algorithm may not know which cycle to align — [SimTK OpenCap forum](https://simtk.org/plugins/phpBB/viewtopic.php?p=50447) (search-snippet summary of forum threads; developer statements, not a validation study)
- OpenCap also expects a *static* neutral pose; raising the hand during the neutral pose broke sync for one user — [SimTK OpenCap forum, "Video synchronization during a neutral pose"](https://simtk.org/plugins/phpBB/viewtopic.php?p=45549)
- An event-based algorithm (heel contact) synchronised OpenCap with force plates in 92.5% of 330 records — [Sensors 2026, PMC12846238](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12846238/) (accuracy in ms not retrieved)
- Kügler (TU Wien diploma thesis, 2026) on aligning wearable/IMU streams via "marker actions": ~4.8 ms accuracy for full-body alignment using walking but only ~17 ms for clapping, attributed to clapping's mostly local upper-body effect; short, impulsive movements with high signal dynamics aligned more consistently than slow ones — [Kügler 2026, TU Wien repositum](https://repositum.tuwien.at/handle/20.500.12708/226907) (search-snippet figures; IMU-to-IMU, not IMU-to-camera)
- StrengthSense dataset: participants jumped after every device reconnection to synchronise IMUs; the paper has a sync-validation section (figures not retrieved) — [arXiv 2511.02027](https://arxiv.org/pdf/2511.02027)
- "Mocap Everyone Everywhere": IMU↔head-camera sync initialised from device timecodes, then corrected by an arm swing so an IMU peak aligns with the frame where the hands are closest to the camera; the authors note the timecodes had minor errors — [arXiv 2401.00847](https://arxiv.org/pdf/2401.00847)
- RocSync benchmark with two GoPros (mean reprojection error, px, at 30/60 fps): RocSync LED clock with sub-frame interpolation 1.02/0.95; without interpolation 3.07/1.11; single-lamp light-based sync 3.09/1.11 (an "ideal case"); audio 12.90/14.64 (with interpolation) and 11.34/13.91 (without); timecode 54.60/55.14 — i.e. a flash is frame-accurate but not sub-frame, audio and consumer timecode were worse than a frame — [RocSync, arXiv 2511.14948](https://arxiv.org/html/2511.14948v1)
- RocSync device: 25×25 cm PCB, 100-LED ring lighting one LED per ms (one revolution per 100 ms) plus a 16-bit binary counter, ArUco marker, TCXO; estimated ~US$20 per unit; mean RMSE 1.34 ms (runs 0.38–1.94 ms) vs Kinect hardware sync at 30 fps; residual error mostly from rolling shutter (the decoded time shifts with the device's vertical image position); offset *and drift* fitted per camera by least squares with RANSAC from showing the clock at start and end — [RocSync, arXiv 2511.14948](https://arxiv.org/html/2511.14948v1)

### Inferences
- For SignSure, the sync gesture should be an impulsive *arm* event that is strong in all three streams: e.g. a fast downward hand slap onto the thigh or table (sharp deceleration spike in the suit's hand/forearm sensors and a velocity discontinuity visible in both videos), performed in the still-hold before and after the sign. A clap is weaker for the suit (local motion, and the two hands' contact is ambiguous in 2D), and a jump excites the trunk/legs, which the nine-angle analysis does not use.
- Doing the event twice (before and after the sign) gives two independent lag estimates; their difference measures drift/VFR error, mirroring RocSync's start/end strategy.
- A single-frame event (flash) only pins the lag to ±half a frame unless the rising edge is interpolated (partial-exposure brightness) or rolling-shutter row timing is used; its main value is as an *independent check* of the algorithmic lag, not as the final estimate.
- A phone-screen "LED clock" (a second phone displaying a millisecond counter/rotating marker, visible to both cameras) is a zero-cost approximation of RocSync; screen refresh (typically 60–120 Hz) would limit it to ~8–17 ms per reading unless a dedicated LED device is used (inference; screen-refresh limits not sourced).

### Gaps
- No source found that directly measures clap/slap/flash precision (ms) for IMU-suit↔video alignment; the 4.8/17 ms numbers are IMU-to-IMU.
- OpenCap's exact sync algorithm and its accuracy in ms were not retrieved (supplementary material of the OpenCap paper suggested by developers).

## Audio-based sync of two phones (audio cross-correlation, PluralEyes-style, ffmpeg) and audio-video offset inside phone files

### Takeaway
Audio cross-correlation can align the *audio tracks* of two phones well, but the result is only as good as each phone's internal audio↔video offset, which is unknown, device-specific and sometimes hundreds of ms; in a controlled benchmark audio sync gave errors above one frame. Sound propagation adds ~3 ms per metre of path difference. Audio is therefore a coarse initialiser, not a sub-frame method.

### Cited Findings
- In RocSync's GoPro benchmark audio sync gave 11–15 px reprojection error vs ~1 px for the LED clock, i.e. errors above one frame interval; the authors suspect audio/video pipeline latency; they note a 5 m difference in source distance adds ~15 ms and crossing a 10 m room ~30 ms — [RocSync, arXiv 2511.14948](https://arxiv.org/html/2511.14948v1)
- Idiap (2009) perceptual audio alignment of camera/phone recordings: 10 ms precision target, correct alignment in 99% of cases on a real-life dataset, outperforming plain cross-correlation (older than the preferred range) — [Idiap publication record](https://publications.idiap.ch/export/publication/1727/marc21)
- A patent on smartphone audio sync refines a waveform cross-correlation delay by cross-correlating onset ("attack") envelopes, because waveform cross-correlation can show wide or multiple similar peaks that make the delay uncertain — [US patent 11609737](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11609737)
- Clock-rate differences over 100 ppm between cameras are described as common, so drift matters on long recordings — [US 2014/0355947](https://patents.justia.com/patent/20140355947)
- Many smartphones record variable frame rate (VFR), causing audio-video sync difficulties in editing — [Wikipedia, Variable frame rate](https://en.wikipedia.org/wiki/Variable_frame_rate); iOS recording uses frame-rate *targets*, not exact rates — [ProVideo Coalition](https://www.provideocoalition.com/understanding-iphone-framerates-for-shooting-editing-distribution/)
- One open-source project reports an Android file whose audio track starts 0.18–0.27 s after the picture via an MP4 empty edit, which editors and ffmpeg handle differently — [GitHub PR, chronon #37](https://github.com/MerlanBromisch/chronon/pull/37) (anecdotal, single small project); a Meta wearables SDK issue reports ~200 ms audio-vs-video timestamp differences on iOS/Android (streaming SDK, not native camera files) — [meta-wearables-dat-ios #347](https://github.com/facebook/meta-wearables-dat-ios/issues/347)
- RecSync's related-work section lists sound, flashlights and phone "shake" as data-based clock-sync approaches — [Akhmetyanov et al. 2021, arXiv 2107.00987](https://arxiv.org/pdf/2107.00987)

### Inferences
- If audio is used, read audio and video start times from container timestamps (`ffprobe -show_streams -show_entries stream=start_time` and the edit list) rather than assuming both start at 0; an ignored edit list alone can produce a 200 ms error.
- Audio is useful to disambiguate the coarse lag when wrist-speed cross-correlation is ambiguous (repetitive signs), with ±1–2 frames tolerance, followed by the existing geometric refinement.
- Per-device audio↔video offset could be calibrated once per phone model with a clap that is also visible (hands meeting), but it may vary between recordings, so it should not be trusted for sub-frame use without a per-take check.

### Gaps
- No 2018–2026 study found that reports audio cross-correlation sync accuracy (ms) for *consumer-phone video frames* (as opposed to audio tracks).
- Typical internal audio↔video offset and its repeatability for current iPhone/Android camera apps were not found from a primary source.

## Timecode / genlock-like solutions for phones; Rokoko Studio sync capabilities

### Takeaway
The only sub-millisecond option for consumer phones found is software sync on Android (RecSync / libsoftwaresync / OpenCamera Sensors): NTP-like clock sync over Wi-Fi plus camera *phase* alignment, ≤ 250–300 µs measured. Consumer timecode (LTC, e.g. Tentacle) gives a shared clock label but no genlock, so frames still have an arbitrary phase (up to half a frame error) and RocSync measured it as the worst method. Rokoko Studio accepts SMPTE timecode in start/stop recording commands (Command API / UDP triggers), which can start the suit recording on a known clock, but no evidence of genlock/LTC input or sub-frame alignment was found.

### Cited Findings
- RecSync (Skoltech, IEEE Sensors 2021): Android app for synchronised video on multiple phones; step 1 clock sync between phones by a min-filtering NTP modification, step 2 align camera phases by requesting frames with different exposure in preview mode; phase is preserved when switching from preview to video — [Akhmetyanov et al. 2021, arXiv 2107.00987](https://arxiv.org/pdf/2107.00987)
- RecSync accuracy: with two Samsung Galaxy S20s and a periodic-flash + rolling-shutter test rig, the time difference between corresponding frames did not exceed 250 µs over five 1-minute pairs (abstract: < 300 µs) — [arXiv 2107.00987](https://arxiv.org/pdf/2107.00987)
- RecSync drift: < 1.2 ms per minute for most of 47 phone models (early Google Pixels worse); phase estimation needs ~50 timestamps (~2 s); assumes phones of the *same model* with Camera2 API and precise ("real-time") frame timestamping; frame-timestamp differences are Gaussian on some phones, others drop frames (clustered intervals) — [arXiv 2107.00987](https://arxiv.org/pdf/2107.00987)
- RecSync is based on Ansari et al., "Wireless Software Synchronization of Multiple Distributed Cameras" (ICCP 2019, Google libsoftwaresync); forks: DFKI-SignLanguage/RecSync-android (RecSyncNG, remote GUI, central download; notes require Android 10+ and an Ethernet adapter on the leader) and MobileRoboticsSkoltech version (Wi-Fi hotspot on leader) — [DFKI RecSync-android](https://github.com/DFKI-SignLanguage/RecSync-android); [Skoltech RecSync-android](https://github.com/mobileroboticsskoltech/recsync-android)
- OpenCamera Sensors (F-Droid) includes the same sync; phones must support real-time timestamping; phase alignment is optional and needed only when precision better than half a frame is required — [OpenCamera Sensors on F-Droid](https://www.f-droid.org/packages/com.opencamera_sensors.app)
- Tentacle-type devices output SMPTE-12M LTC timecode and offer no genlock; timecode lock suffices for multicam ISO editing but not frame-phase lock — [vmi.tv review](https://vmi.tv/?p=7553) (reseller review, secondary)
- RocSync measured a timecode baseline at ~55 px reprojection error vs ~1 px for its LED clock (GoPro, 30/60 fps) — [RocSync, arXiv 2511.14948](https://arxiv.org/html/2511.14948v1)
- Pose2Sim notes GoPros can be synchronised by timecode or GPS (outdoors) — [Pose2Sim README](https://github.com/perfanalytics/pose2sim)
- **Rokoko-specific:** Studio's Command API `recording/start` and `recording/stop` take an optional SMPTE `hh:mm:ss:ff` timecode (plus optional `frame_rate`); the start timecode sets the clip's start time, a non-zero stop timecode sets duration and trims data; `00:00:00:00` means timecode not used — [Rokoko studio-command-api-examples](https://github.com/Rokoko/studio-command-api-examples); [Rokoko Command API support article](https://support.rokoko.com/hc/en-us/articles/9738087323025-Rokoko-Studio-Command-API)
- **Rokoko-specific:** Studio also accepts two-way UDP trigger messages with the same SMPTE timecode to align clip start time, offset and duration — [Rokoko UDP Trigger Messages](https://support.rokoko.com/hc/en-us/articles/14905272191505-Rokoko-Studio-UDP-Trigger-Messages) (page 403 on fetch; content from search snippet)
- **Rokoko-specific:** Studio 2.3.2 release notes reference a sample "SyncRecordingApp" for timecode with start/stop; a bug where a stop timecode did not trim clips was fixed in 2.4.2 — [Studio 2.3.2 notes](https://support.rokoko.com/hc/en-us/articles/13143030107537-Rokoko-Studio-2-3-2); [Studio 2.4.2 notes](https://support.rokoko.com/hc/en-us/articles/18467538187409-Rokoko-Studio-2-4-2) (search-snippet content)
- A third-party blog says the Smartsuit Pro II outputs timecode that can be aligned with a Live Link Face recording in post — [mocaponline.com](https://mocaponline.com/blogs/mocap-news/face-capture-game-dev-iphone-arkit-live-link-metahuman) (secondary)

### Inferences
- The SignSure phone pair (480p 30 fps + 1080p 60 fps) is mixed-model/mixed-rate; RecSync assumes the same model and equal rates, so using it would mean two Android phones of the same model at 60 fps. If phases are aligned at 60 fps, a 30 fps stream could be derived by decimation without losing alignment (inference).
- A practical low-budget "trigger" for the suit: a small script on the laptop running Rokoko Studio that sends the Command API start-recording call while also emitting a visible/audible cue (or while a phone app starts recording) gives a coarse common start (~tens of ms, network/UI latency unknown) — useful for initialisation and for ruling out gross lag ambiguity, not for sub-frame sync.
- Timecode written by a phone app (e.g. LTC on the audio track) inherits the phone's audio↔video offset problem and frame-phase ambiguity; it is a labelling aid, not a sub-frame method.

### Gaps
- Whether Rokoko Studio can *receive* external LTC/genlock from hardware (e.g. Tentacle) or *emit* timecode, and how the Command API timecode maps to FBX export time ("use clip start time as time zero"), was not confirmed from Rokoko documentation (support pages returned 403).
- Rokoko suit internal latency/timestamp jitter: no source found.
- No iOS equivalent of RecSync (phase-aligned multi-phone recording) was found in this search; commercial multicam apps were not evaluated.

## Sub-frame algorithmic sync (spline/continuous-time alignment, reprojection-based offsets, rolling shutter, DTW vs offset, drift/VFR)

### Takeaway
Pose-based sync with continuous-time interpolation is a mature approach and reaches ~0.25 frame average error in the literature; interpolating to the estimated sub-frame time roughly halves triangulation error versus nearest-frame matching. The right model is a pure offset plus (optionally) a linear clock-rate term, applied to *container timestamps*, not DTW (which absorbs real kinematic differences). Rolling shutter is the dominant residual for LED-based methods and also biases keypoint times by image row.

### Cited Findings
- Albl & Kukelova et al. jointly estimate two-view geometry and the temporal offset from minimal correspondences, modelling image motion as linear (later spline) in time; methods need a good initialisation and small offsets (< ~0.5 s) — [Albl et al., arXiv 1704.06843](https://arxiv.org/pdf/1704.06843) (offset-range limit from search snippet)
- A 2021 Sensors paper synchronises multi-camera systems from off-the-shelf 2D human-pose estimates and reports sub-frame accuracy on four benchmarks, with lower accuracy on some datasets — [Sensors 21(7):2464, doi 10.3390/s21072464](https://doi.org/10.3390/s21072464) (full text not retrieved; snippet)
- Self-supervised human-pose-based multi-camera synchronisation with a motion-spline representation reports average temporal error below 0.26 frames — [ResearchGate record](https://www.researchgate.net/publication/364478069_Self-Supervised_Human_Pose_based_Multi-Camera_Video_Synchronization) (snippet)
- Spatio-temporal calibration of multiple Kinects from 3D human pose resamples pose streams by interpolation for sub-frame alignment before triangulation — [ResearchGate record](https://www.researchgate.net/publication/365589151_Spatio-Temporal_Calibration_of_Multiple_Kinect_Cameras_Using_3D_Human_Pose) (snippet)
- RocSync: interpolating keypoints to sub-frame timestamps roughly halved 3D hand-pose triangulation error vs nearest-frame matching (~4.4 px vs 8.8 px, from snippet), and cut GoPro 30 fps reprojection error from 3.07 to 1.02 px; each camera's time modelled as linear in global time (offset + drift) — [RocSync, arXiv 2511.14948](https://arxiv.org/html/2511.14948v1)
- RocSync attributes most residual error to rolling shutter: rows are exposed at different times so the decoded timestamp depends on the device's vertical image position; rolling-shutter compensation left as future work — [RocSync](https://arxiv.org/html/2511.14948v1)
- Pose2Sim's sync: mean *vertical* speed of selected keypoints per camera, 6 Hz 4th-order low-pass before cross-correlation, keypoints with likelihood < 0.4 ignored, search ±2 s around an approximate max-speed time; plots saved; no sub-frame refinement or accuracy figure documented — [Pose2Sim README](https://github.com/perfanalytics/pose2sim)
- Plain cross-correlation resolves offsets only to the sampling interval; sub-sample accuracy needs refinement — [Scitepress 2019, low-cost camera/IMU sync](https://www.scitepress.org/Papers/2019/78376/78376.pdf) (snippet); Boxi (robotics) refines by iteratively interpolating one signal at the current offset and minimising MSE, reaching ~0.5 ms average offset uncertainty between two IMUs — [Boxi, arXiv 2504.18500](https://arxiv.org/pdf/2504.18500)
- Android frame timestamps follow t_i = τ0 + N_i·τ + η_i (phase, period, integer frame index allowing drops); some phones drop frames, giving clustered inter-frame intervals; period/phase can be fitted by least squares per cluster — [RecSync, arXiv 2107.00987](https://arxiv.org/pdf/2107.00987)
- iOS records VFR with frame-rate targets; even ProRes iPhone footage can be variable — [ProVideo Coalition](https://www.provideocoalition.com/understanding-iphone-framerates-for-shooting-editing-distribution/); [Blackmagic forum](https://forum.blackmagicdesign.com/viewtopic.php?t=151404&p=807888) (anecdotal)

### Inferences
- **Use per-frame presentation timestamps** (ffprobe `pts_time`) for both videos instead of `index / nominal_fps`. A 29.97 vs 30 fps mismatch is 1000 ppm = 10 ms over 10 s and 30 ms over 30 s (arithmetic) — larger than the target; VFR jitter/drops are similar order. Then fit lag (and optionally a rate term) in continuous time.
- **Continuous-time refinement:** replace the quarter-frame grid with a continuous 1-D optimisation (e.g. Brent) of the reprojection-error-vs-lag cost, evaluating the slower camera's keypoints by cubic-spline interpolation at t + lag (already partly the case). Report the curvature of the cost at the minimum as a local precision estimate.
- **Rolling shutter:** each keypoint's capture time ≈ frame start + (row / height) · readout time. With a 1080p phone readout of the order of 10–30 ms (unverified, see Gaps), a wrist moving vertically across the image gets a row-dependent time bias of several ms — comparable to the target. A rolling-shutter-aware model adds row·readout/height to each keypoint time before interpolation; readout time can be fitted as an extra parameter in the geometric refinement (it is identifiable from fast vertical motion) or measured once per phone (flash/LED test).
- **DTW vs offset:** for one performance seen by two cameras and the suit, the true relation is offset + linear drift. DTW would warp away genuine disagreement (exactly what the equivalence test is meant to detect), inflating apparent agreement. Use DTW only as a diagnostic.
- **Drift:** with RecSync's < 1.2 ms/min (phones) and ~100 ppm (6 ms/min) clock differences as plausible bounds, a 10–20 s sign take accumulates ~0.2–2 ms drift — negligible relative to a frame if timestamps (not nominal fps) are used, but a two-event (start/end) estimate costs nothing.

### Gaps
- Rolling-shutter readout times for the specific phones were not researched (calibration teammate's area); numbers above are an unverified order of magnitude.
- No paper found that reports sub-frame sync accuracy specifically for mixed 30/60 fps phone pairs.

## Video↔IMU-suit alignment (accelerations/angular velocities vs video, latency, filtering delays, FBX timing)

### Takeaway
Validation studies align IMU and optical/video data by cross-correlating rotation-invariant signals (norm of angular velocity, speed), typically followed by sub-sample interpolation refinement; a zero-lag cross-correlation peak after alignment is used as the check. Hardware sync is preferred where available; software-only alignment is often coarse enough that some studies analysed only peak values. Constant suit latency is absorbed by the fitted offset; *phase* delays from filtering are not, unless both streams are filtered identically with zero-phase filters.

### Cited Findings
- Optical↔IMU temporal alignment by cross-correlating the norms of optical and gyroscope angular velocities and taking the largest peak; using norms makes the alignment independent of the rotational offset between systems — [Sensors 2025, 25(15):4680](https://www.mdpi.com/1424-8220/25/15/4680) (page 403; from search snippet)
- IMU vs optoelectronic validation (J NeuroEng Rehabil 2024): hardware synchronisation further refined in software by cross-correlation and visual inspection — [Springer, s12984-024-01426-6](https://link.springer.com/article/10.1186/s12984-024-01426-6) (snippet)
- FlEye camera: cross-correlation peak at zero lag used as evidence that optical and inertial signals are correctly collated (mean absolute angular-velocity difference ~0.54 deg/s) — [arXiv 2412.21081](https://arxiv.org/pdf/2412.21081)
- MetaMotion IMU vs Vicon thesis: time sync by `xcorr`; sync limitations meant only peak orientations and angular-velocity extrema were analysed — [ODU thesis](https://digitalcommons.odu.edu/cgi/viewcontent.cgi?article=1026&context=biomedengineering_etds)
- Spatio-temporal initialisation for IMU-to-camera registration (TUM) — [mediaTUM 1287172](https://mediatum.ub.tum.de/doc/1287172/141816.pdf) (not opened)
- Sub-sample refinement by iterative interpolation + MSE minimisation: ~0.5 ms offset uncertainty (IMU↔IMU) — [Boxi, arXiv 2504.18500](https://arxiv.org/pdf/2504.18500)
- Impulsive full-body movements gave ~4.8 ms IMU alignment vs ~17 ms for clapping — [Kügler 2026](https://repositum.tuwien.at/handle/20.500.12708/226907) (snippet)
- "Mocap Everyone Everywhere" used an arm-swing IMU peak vs camera frame to correct timecode-based IMU↔camera sync — [arXiv 2401.00847](https://arxiv.org/pdf/2401.00847)

### Inferences
- **Signal choice for FBX↔video:** the FBX gives orientations (and positions) at 60 fps, not raw IMU accelerations; the analogue of the gyro-norm method is to cross-correlate the norm of *segment angular velocity* (forearm, upper arm) computed from FBX orientations against the same quantity from triangulated video segments, alongside wrist speed and elbow-angle rate. Using several independent, rotation-invariant signals and checking that their lags agree (current: ~8 ms) is the established verification pattern.
- **Filtering:** the 6 Hz zero-lag Butterworth used in SignSure introduces no phase delay if applied identically to both streams before cross-correlation; any causal filtering inside Rokoko Studio (filters/smoothing at export) would introduce a frequency-dependent delay that a single offset can only partly absorb (no Rokoko documentation found). Exporting with filters/key reduction off (already the protocol for validation exports) minimises this.
- **Sub-sample:** FBX (60 fps) vs video-derived 3D (resampled): refine the cross-correlation peak by parabolic interpolation or by direct continuous lag optimisation on spline-interpolated signals (Boxi-style), then confirm by minimising the *angle* RMS between FBX and video as a function of lag — but beware that the latter optimises the very quantity being tested (see next section).
- **Latency:** a constant suit latency (wireless transmission, Studio buffering) is irrelevant once a per-take offset is fitted; only latency *variation* within a take matters, which would show up as lag disagreement between the pre-sign and post-sign events.
- **"Use clip start time as time zero":** this only shifts the FBX time origin, so it does not affect a per-take fitted offset; it matters only if Rokoko timecode is used to pre-align.

### Gaps
- No study found reporting residual IMU-*suit* (Rokoko/Xsens) vs markerless-video sync error in ms.
- Rokoko Studio's internal filtering delay and timestamp source for exported FBX keys were not documented in accessible sources.

## How to verify sync quality and propagate residual sync uncertainty

### Takeaway
Verify with an independent ground truth (LED/flash/LED-clock visible to both cameras, or two separated sync events), with agreement between independent signals, and with the sharpness of the cost minimum. Propagate the lag uncertainty by drawing the lag from its estimated distribution in each Monte Carlo draw, and report the sensitivity of the RMS to ±1 frame. Avoid choosing the lag by minimising the tested angle discrepancy.

### Cited Findings
- RocSync verifies against hardware-synchronised Kinects (RMSE 1.34 ms) and uses reprojection error as a sync-quality metric for unsynchronised cameras, comparing methods by it — [RocSync](https://arxiv.org/html/2511.14948v1)
- RecSync verifies with a periodic flash + rolling-shutter rig: time difference between corresponding frames ≤ 250 µs — [arXiv 2107.00987](https://arxiv.org/pdf/2107.00987)
- Zero-lag cross-correlation peak after alignment as an IMU↔optical validation check — [FlEye, arXiv 2412.21081](https://arxiv.org/pdf/2412.21081)
- OpenCap developers chose between a velocity cross-correlation lag and a distance-minimising lag by whichever gave lower error in some alignments — [SimTK OpenCap forum](https://simtk.org/plugins/phpBB/viewtopic.php?p=49350) (snippet)
- Pose2Sim saves cross-correlation plots per camera pair for inspection — [Pose2Sim README](https://github.com/perfanalytics/pose2sim)
- Two sync observations (start and end) allow estimating offset *and* drift — [RocSync](https://arxiv.org/html/2511.14948v1)

### Inferences
- **Verification checklist per take:** (1) lag from wrist speed, elbow-angle rate, segment-angular-velocity norm and geometric refinement agree within a few ms; (2) the reprojection-error-vs-lag curve has a single sharp minimum (curvature → standard error); (3) lag estimated separately from a pre-sign and a post-sign sync event agrees (drift/VFR check); (4) optionally, an independent flash/LED event lands within ±½ frame of the algorithmic lag; (5) residual correlation peak at zero lag after alignment.
- **Uncertainty propagation:** treat each lag (video↔video, video↔FBX) as a random variable, e.g. Normal(estimate, σ) with σ from the spread of the independent estimates or from a block bootstrap over time segments (frames are autocorrelated, so segment/block resampling, not frame resampling). Draw it in every Monte Carlo iteration alongside the calibration refits, so sync error inflates the RMS bound honestly. Also report a deterministic sensitivity curve RMS(lag) over ±1 frame.
- **Independence from the tested quantity:** estimate lags from signals other than the nine test angles (or at least from speed/velocity, not angle values), otherwise the sync step partly "fits" the agreement under test and biases the TOST towards equivalence; this matches the project's pre-registration philosophy (lag rule fixed before seeing results).

### Gaps
- No published protocol found that propagates sync uncertainty into a TOST/equivalence decision for IMU-vs-video validation; the above is a design inference.

## Ranked catalogue of methods for SignSure (synthesis)

### Takeaway
Best value: (1) keep and strengthen the software chain (timestamp-correct, continuous-time, rolling-shutter-aware refinement with multi-signal agreement and Monte Carlo lag propagation), (2) add an impulsive arm sync event before and after each sign, (3) add a cheap LED/flash or LED-clock check; hardware/app sync (RecSync) gives sub-ms video↔video only for matched Android phones; timecode and audio are coarse aids only.

### Cited Findings
- Accuracy anchors: RecSync ≤ 0.25–0.3 ms (matched Android phones) — [arXiv 2107.00987](https://arxiv.org/pdf/2107.00987); RocSync LED clock 1.34 ms RMSE, ~US$20 — [arXiv 2511.14948](https://arxiv.org/html/2511.14948v1); pose-based spline sync < 0.26 frame — [ResearchGate](https://www.researchgate.net/publication/364478069_Self-Supervised_Human_Pose_based_Multi-Camera_Video_Synchronization); single flash ≈ frame-level — [RocSync](https://arxiv.org/html/2511.14948v1); audio and timecode worse than one frame in GoPro benchmark — [RocSync](https://arxiv.org/html/2511.14948v1); IMU impulsive full-body event ~4.8 ms, clap ~17 ms — [Kügler 2026](https://repositum.tuwien.at/handle/20.500.12708/226907); Rokoko Studio timecode via Command API/UDP (start-time labelling only) — [Rokoko examples](https://github.com/Rokoko/studio-command-api-examples)

### Inferences
Ranked (accuracy ÷ effort for this project; accuracies are literature figures or estimates as marked):

| # | Method | Applies to | Expected accuracy | Cost/effort | How to verify |
|---|---|---|---|---|---|
| 1 | Use per-frame container timestamps (VFR/29.97 aware) + continuous-time lag optimisation (spline interpolation, no quarter-frame grid) | video↔video, video↔FBX | removes up to tens of ms of rate error; sub-frame refinement ~0.25 frame (lit.) | software only, low | timestamps histogram; start/end lag agreement |
| 2 | Rolling-shutter-aware keypoint times (fit or measure readout) | video↔video | removes a row-dependent bias of several ms (est.) | software, medium | reprojection error drop; LED test |
| 3 | Impulsive arm sync event (hand slap) before and after each sign, in the still holds | all three streams | ~5 ms class for impulsive events (IMU lit.); frame-level visually, sub-frame with interpolation | protocol, ~2 s per take | lag agreement pre vs post; agreement with continuous-signal lag |
| 4 | Multi-signal agreement (wrist speed, elbow-angle rate, segment angular-velocity norm, geometric) + Monte Carlo lag propagation | both | quantifies rather than reduces error | software, low–medium | spread of estimates → σ |
| 5 | LED-clock / flash visible to both phones (RocSync-like ~US$20 build, or phone flashlight) | video↔video (check) | 1.3 ms (RocSync), flash ≈ frame-level | low–medium hardware | independent ground truth per take |
| 6 | RecSync/OpenCamera Sensors on two identical Android phones at 60 fps | video↔video | ≤ 0.3 ms, drift < 1.2 ms/min | buy matched Androids; setup effort | built-in; flash test |
| 7 | Rokoko Command API/UDP start with SMPTE timecode, triggered with phone recording start | video↔FBX (coarse) | tens of ms (est.; latency undocumented) | scripting, low | compare to fitted offset |
| 8 | Audio cross-correlation (incl. onset refinement) | video↔video (coarse) | > 1 frame in benchmark; depends on per-phone A/V offset | software, low | only as initialiser |
| 9 | LTC/Tentacle timecode on phones | video↔video labelling | worse than a frame (no genlock) | ~US$200+ hardware (price not verified) | — |

- Avoid DTW for the final alignment; use offset (+ linear drift) only.
- Estimate lags without using the nine test angles' agreement, and fix the sync rule in the pre-registration before analysing a new take.

### Gaps
- Prices for Tentacle units and multicam phone apps were not verified.
- No direct measurement of the current SignSure pipeline's lag error against an independent ground truth exists in the sources; a flash/LED-clock take would provide it.
