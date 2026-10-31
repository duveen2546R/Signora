# Software-only synchronisation of two existing phone videos and a Rokoko suit FBX

Scope: algorithmic sync of the existing inputs (iPhone 1080p 60 fps constant-frame-rate video; 480p ~30 fps variable-frame-rate (VFR) re-encoded video, frame intervals 11–52 ms; Rokoko FBX 60 fps, no audio). No new recordings. Statements marked **[in-house]** are reasoning or arithmetic done for this note, not taken from a source. Facts about the current SignSure code come from the assignment and were not re-checked.

Overall picture (summary for the report writer):
- **Best pipeline [in-house synthesis].**
  1. Read true per-frame presentation timestamps (PTS) with PyAV/ffprobe and the MP4 edit lists. Do not use OpenCV `CAP_PROP_POS_MSEC`.
  2. Get a coarse video↔video lag from audio (GCC-PHAT or onset envelopes), or from the existing wrist-speed cross-correlation. Use the two only as an independent cross-check of each other.
  3. Refine the video↔video lag, and optionally a clock-rate factor, by minimising reprojection error with continuous-time (cubic or smoothing-spline) keypoint trajectories. Use the 60 fps iPhone view as the time reference.
  4. Get the video↔FBX lag from cross-correlation with sub-sample peak interpolation, combining several rotation-invariant signals.
  5. Estimate a standard error for each lag (cost curvature, block bootstrap, spread across independent signals) and draw both lags in every Monte Carlo replicate.
- **Expected accuracy [in-house, not sourced; no published study matches this exact setup].**
  - Video↔video after geometric refinement: about 2–8 ms (roughly 0.1–0.25 of a 33 ms frame, consistent with the earlier <0.26-frame result).
  - Audio alone: sub-ms between the audio tracks, but only to within the unknown audio/video offset inside each file, which may be tens of ms in the re-encoded file.
  - Video↔FBX: about 5–15 ms (the existing two-signal agreement of ~8 ms is the best local evidence).

## 1. Audio-based video↔video sync (GCC-PHAT, onset/envelope, fingerprinting); pitfalls; reading exact PTS and edit lists

### Takeaway
Audio cross-correlation can align the two audio tracks to well under a millisecond. But video↔video sync from audio is only as good as each file's internal audio-to-video offset. Edit lists, encoder priming and messaging-app re-encoding can shift that offset by tens of ms, sometimes far more. Use audio for coarse sync and as an independent cross-check, not as the final sub-frame lag. Read video and audio timing from PTS plus edit lists (PyAV/ffprobe), never from OpenCV's position property.

### Cited Findings
- **Coarse-then-fine is the standard audio design.**
  - Fingerprint-based positions have only frame-level accuracy. A patented design therefore runs GCC-PHAT cross-correlation around the coarse fingerprint candidates to refine them — [US8682144B1](https://patents.google.com/patent/US8682144).
  - A 2026 arXiv paper (360° camera capture) uses the same pattern: spectral fingerprints vote for a coarse lag, then GCC-PHAT on the waveforms refines it — [arXiv 2609.22809](https://arxiv.org/pdf/2609.22809).
- **GCC suits refinement, fingerprinting suits coarse search.** A EUSIPCO 2015 paper:
  - calls generalised cross-correlation well known for accurate delay estimation but computationally expensive, so best for channels that are already roughly aligned;
  - says fingerprinting accuracy is bounded by the time-frequency hop size, typically a few to tens of ms: enough for video, but not sample-level sync — [EUSIPCO 2015](https://new.eurasip.org/Proceedings/Eusipco/Eusipco2015/papers/1570096423.pdf).
- **The research lineage of audio-based multi-camera sync:**
  - Shrestha, Barbieri & Weda (ACM MM 2007), audio fingerprints;
  - Shrestha et al. (IEEE Trans. Multimedia 12:79–92, 2010), audio-visual features;
  - Bryan, Smaragdis & Mysore (ICASSP 2012), landmark-based fingerprint cross-correlation to cluster and time-align user-generated recordings — [SyncSink JMUI author version (Six & Leman 2015)](https://0110.be/files/attachments/415/2015.08.syncsink_jmui_author_version.pdf); [Adobe Research page](https://research.adobe.com/publication/clustering-and-synchronizing-multi-camera-video-via-landmark-cross-correlation).
  - I could not retrieve the accuracy tables of these papers (see Gaps).
- **Pairwise offsets can be chained.** Pairwise offsets between recordings can be combined so that a poorly correlated pair is aligned through intermediate recordings — [US9756281B2 / related Google patents](https://patents.google.com/patent/US9756281).
- **Audio vs visual events.** Pose2Sim's documentation says visual events should be preferred to audio ones because sound travels much more slowly than light — [Pose2Sim README](https://github.com/perfanalytics/pose2sim/blob/main/README.md).
- **iPhone audio/video offsets are model-specific and can be large.**
  - The SynQR vendor says every iDevice model has a model-specific AV offset, which it calibrates. This is a vendor claim, not an independent measurement — [SynQR / CreativeCOW](https://creativecow.net/synqr-measure-your-daws-video-offset-with-your-iphone-reliably-in-real-time/).
  - An Apple developer forum thread reports that video stabilisation on an iPhone 15 Pro adds up to about 1 s of video delay because it buffers frames. The same poster saw video frames starting well before the first audio sample — [Apple Developer Forums 742022](https://developer.apple.com/forums/thread/742022).
- **A/V offsets live in MP4 edit lists (`elst`), and tools disagree on how to read them.**
  - One reported file had an `elst` delay of 80 ms for video and 14 ms for audio, matching what FFmpeg reported — [VideoHelp forum](https://forum.videohelp.com/threads/391977-How-to-retrieve-stream-offsets).
  - Avidemux showed the first frame of another file at 0.146 s even though the video PTS was 80 ms and the audio 14 ms. The dispute is whether the `elst` delay is relative to PTS or DTS — [avidemux.org forum](https://avidemux.org/smif/index.php?msg=85672).
  - `AVStream.start_time` is only the first frame's timestamp, not a separate track offset — [VideoHelp forum](https://forum.videohelp.com/showthread.php?p=2540969).
- **ffprobe does not flag VFR.** The stream frame rate can show a constant value (e.g. 24/1) while the file is VFR. Check per-frame timestamp gaps instead (`-show_frames`, or `-show_entries frame=pts_time,duration_time`) — [Shotcut forum](https://forum.shotcut.org/t/why-shotcut-think-the-mp4-as-variable-frame-rate/48999); [FFmpeg trac #10799](https://trac.ffmpeg.org/ticket/10799).
- **PyAV exposes exact per-frame timing.**
  - `Frame.pts` is "the presentation timestamp in time_base units", `Frame.time` is the presentation time in seconds, and `Frame.dts` is copied from the packet — [PyAV Frame API](https://pyav.basswood.io/docs/stable/api/frame.html).

### Inferences
- **[in-house] What audio can actually deliver.**
  - At 44.1/48 kHz, GCC-PHAT between two microphones in the same room usually gives a well-defined peak. Its resolution is far finer than the 16.7 ms video frame.
  - Sound-path difference adds about 2.9 ms per metre of difference in microphone-to-subject distance (343 m/s). With phones 1–3 m from the signer, that bias is a few ms at most.
  - The real limit is that audio lag = video lag + (A/V offset in file 1 − A/V offset in file 2). Those offsets are unknown for the re-encoded 480p file, which has no metadata. So audio gives a coarse lag that is very precise but possibly biased by tens of ms.
- **[in-house] Use audio as a check, not as the answer.**
  - Compare the audio lag with the pose-based lag. If they agree within ~1 frame, that is independent evidence that the coarse wrist-speed peak is the right one: no cycle slip on the repetitive signing motion.
  - A persistent difference estimates the combined A/V offset. Do not use it to correct the pose lag, because the geometric refinement measures the video lag directly.
- **[in-house] Audio content.** Hand signing makes little sound. The usable audio is probably room noise, speech before or after the take, clothing or suit rustle, and handling noise from starting the recording. GCC-PHAT whitens the spectrum, so it works on broadband transients like these better than plain cross-correlation. Onset-envelope correlation is a robust fallback.
- **[in-house] Reading timing correctly.**
  - Decode with PyAV and record `frame.time` for every video and audio frame.
  - Dump the `elst` boxes (ffprobe `-show_streams` / `-show_entries stream=start_time`, or MP4Box/`mp4dump`).
  - Check whether FFmpeg has already applied the edit list (current FFmpeg applies MP4 edit lists by default unless `-ignore_editlist` is set). Then express video PTS, audio PTS and lag on one container timeline.
  - OpenCV `CAP_PROP_POS_MSEC` on a VFR file can be the nominal frame index divided by the average fps rather than the true PTS, depending on backend. I did not verify this for the installed OpenCV version.
  - **Concrete check:** compare OpenCV times against PyAV `frame.time` for the 480p file. If they diverge by more than a few ms over the take, every current lag estimate is affected.
- **[in-house, prior knowledge, unverified this round]** AAC encoders add "priming" samples (often 1024 or 2112 samples, about 21–48 ms at 44.1/48 kHz), normally compensated through the edit list or iTunSMPB metadata. A messaging-app re-encode may drop or mis-state this, which is one plausible source of tens-of-ms A/V shifts.

### Gaps
- No published measured accuracy (ms) of audio-based sync for consumer phone video was retrieved. The Shrestha 2007/2010 and Bryan 2012 accuracy tables were not accessible (the ICASSP PDF returned 404).
- No published measurement of how much WhatsApp or other messaging-app re-encoding shifts audio relative to video. This needs a local test (in-house suggestion: record a clap on one phone, send it through the same app, compare A/V offsets before and after).
- Exact AAC priming and edit-list behaviour for iPhone 17 files was not verified from a primary Apple source.

## 2. Continuous-time sub-frame sync (splines, epipolar/reprojection, spatiotemporal BA, rolling shutter)

### Takeaway
The literature strongly supports two ideas: model each 2D trajectory in continuous time (linearly, by spline, or with a physical motion prior), and estimate the time shift together with the geometry by minimising epipolar or reprojection error. Sub-frame precision is routinely claimed but rarely quantified in milliseconds. For the SignSure case, the existing approach (cross-correlation, then reprojection refinement) is the right family. The upgrades are:
- a continuous sub-frame search instead of a quarter-frame grid;
- cubic or smoothing-spline interpolation;
- an optional clock-rate factor;
- a curvature-based standard error.

### Cited Findings
- **Albl et al., CVPR 2017** — [ar5iv 1704.06843](https://ar5iv.labs.arxiv.org/html/1704.06843); [CVPR poster](https://openaccess.thecvf.com/content_cvpr_2017/poster/2003_POSTER.pdf):
  - Models the time mapping as t′ = β + ρ·i, i.e. offset plus frame-rate ratio, and linearises the image trajectory locally ("approximating the image motion locally by a straight line").
  - Provides minimal solvers that estimate F or H together with β: 8 correspondences for F, 9 for a generalised-eigenvalue F, and 4.5 for H. These run inside RANSAC.
  - An iterative algorithm handles shifts of several seconds (about 5 s on Marker/Hockey, 2–2.5 s on UvA/KITTI). On real data a single RANSAC synchronised shifts of 2–5 frames.
  - Sub-frame precision is described only qualitatively: "very precise for various levels of noise", synthetic σ = 0.5 px. It was not tested on real data because real ground truth was lacking.
  - Linearisation fails on highly non-linear trajectories.
  - Baselines: linear interpolation (Noguchi 2007) and spline interpolation (Nischt 2009).
- **Sinha & Pollefeys (IJCV 2005)** use space-time trajectories of moving objects to obtain sub-frame temporal correspondence and calibration of unsynchronised stationary cameras — [Springer IJCV](https://link.springer.com/article/10.1007/s11263-005-4842-z); [PDF](https://facerec.ece.wisc.edu/cameranet/sinha05.pdf).
- **Patent EP2309451** models matched-feature trajectories with spline interpolation and runs a non-linear search over the sync parameters under the epipolar constraint until convergence — [EPO EP2309451](https://data.epo.org/publication-server/rest/v1.2/patents/EP2309451NWA1/document.html).
- **Vo, Narasimhan & Sheikh — spatiotemporal bundle adjustment (CVPR 2016; extended arXiv 2007.12806)** — [CVPR 2016 paper](https://openaccess.thecvf.com/content_cvpr_2016/papers/Vo_Spatiotemporal_Bundle_Adjustment_CVPR_2016_paper.pdf); [CMU RI page](https://www.ri.cmu.edu/publications/spatiotemporal-bundle-adjustment-for-dynamic-scene-reconstruction); [arXiv 2007.12806](https://arxiv.org/pdf/2007.12806v1.pdf):
  - Standard bundle adjustment's triangulation constraint is invalid for moving points seen by unsynchronised cameras.
  - The method jointly estimates sub-frame offsets and 3D trajectories using physics-based motion priors (least kinetic energy, least force, least action), evaluated on the CMU mocap database.
  - Direct optimisation falls into local minima, so the authors use incremental reconstruction plus temporal alignment.
  - The journal version fits a statistical human body model to the unsynchronised streams.
  - I did not open the full PDFs, so their ms numbers are not reported here.
- **VisualSync (arXiv 2512.02017, 2025)** — [arXiv HTML](https://arxiv.org/html/2512.02017v1):
  - Minimises the Sampson (epipolar) error over cross-view tracklets.
  - Pairwise frame-granular search, then global robust (Huber/IRLS) offsets in continuous time.
  - Median per-video errors: 46.6 ms on Egohumans, 41.5 ms on CMU Panoptic, 77.8 ms on 3D-POP, 5.9 ms on UDBD (Sync-NeRF 0.2 ms on UDBD).
  - Halving CMU Panoptic from 30 to 15 fps raised the mean error from 112.6 to 157.2 ms.
  - Stated limitations: needs reliable camera poses; cannot handle non-uniform playback speed; O(N²) pairs.
  - These are generic-scene numbers with estimated poses. They are much worse than what a two-view, single-person setup with calibrated-by-body geometry can do.
- **Pose2Sim's sync module** — [Pose2Sim README](https://github.com/perfanalytics/pose2sim/blob/main/README.md):
  - Computes the mean vertical speed of chosen keypoints (default all; wrists and elbows recommended) after a 6 Hz, order-4 low-pass filter, ignoring keypoints with likelihood < 0.4.
  - Takes the offset that maximises correlation, within ±2 s (`time_range_around_maxspeed`) of an approximate max-speed time.
  - Works best with a clear vertical movement, no motion towards or away from the cameras, and captures of ≥5 s but not more than a few minutes, because cameras may drift.
  - The README does not state sub-frame precision. It is essentially the same as SignSure's current coarse step.

### Inferences
- **[in-house] Recommended video↔video refinement.**
  - Parameterise the 2D keypoint tracks of the VFR view as a smoothing cubic spline in true PTS time, or a cubic Hermite (PCHIP) to avoid overshoot. Smooth with a penalty matched to the 6 Hz Butterworth band.
  - Evaluate the VFR spline at t_ref + β (or, with drift, β + ρ·t_ref) for every 60 fps reference frame.
  - Minimise robust reprojection error over moving frames with a 1-D bounded scalar optimiser (Brent) on β, or a 2-D one on (β, ρ). Alternate with the camera self-calibration, as Vo et al. do incrementally.
  - This replaces the quarter-frame grid (4 ms steps on the 60 fps grid, 8 ms on the 30 fps grid) with continuous estimation, and gives a cost curve whose curvature yields a standard error (section 5).
- **[in-house] Expected precision.** A lag error δ creates a 2D disparity of about v·δ pixels, where v is image speed. Example: a wrist at 2 m/s, 2–3 m from a 1080p phone (focal ≈ 1500 px) moves about 1000–1500 px/s, so 1 ms ≈ 1–1.5 px. With ~3 px RTMW keypoint noise averaged over hundreds of fast frames and several joints, the reprojection minimum should localise β to a few ms. That matches the earlier <0.26-frame (≈ 4–8 ms) result. Not validated on these takes: use the simulator `single_take_simulation.py` with a known injected lag to measure it.
- **[in-house] Clock-rate (ρ) estimation.** Ordinary phone clocks have only small rate errors (typically tens of ppm, unsourced here); over a 5–15 s take that is under 1 ms. But a messaging-app re-encode that retimed frames could introduce real scale or jitter. Check by fitting ρ freely: if |ρ − 1| × duration < ~2 ms, fix ρ = 1 to avoid an extra parameter.
- **[in-house] Rolling shutter.** Each row of a rolling-shutter frame is exposed at a different time. In a 1080p iPhone frame, readout is roughly 10–30 ms top to bottom (unsourced estimate), so wrists high versus low in the frame are effectively sampled at different times. Albl's group has separate rolling-shutter SfM work, but no rolling-shutter-aware sync paper was retrieved. A software-only fix is to add a per-camera row-time term (t = t_frame + β + κ·y/H) and estimate κ jointly. It is weakly identifiable; treat it as a sensitivity analysis.

### Gaps
- Quantified ms accuracy for Albl 2017 (only figures), Sinha & Pollefeys and Vo et al. was not extracted; full PDFs were not accessible or not opened (CVF returned 403).
- No retrieved paper on rolling-shutter-aware temporal sync with numbers.
- No paper reporting sub-frame sync accuracy for human-pose (keypoint-only) two-phone setups specifically. The <0.26-frame figure comes from the earlier SignSure research round.

## 3. Handling variable-frame-rate video: reference choice, resampling and interpolation

### Takeaway
Use the 60 fps constant-frame-rate iPhone view as the reference time grid. Place the VFR view's keypoints at their true PTS (from PyAV), not at index/fps. Interpolate them with a cubic or smoothing spline rather than linearly. For fast signing, linear interpolation over 33–52 ms gaps can cause centimetre-scale errors.

### Cited Findings
- ffprobe's stream frame rate can show a constant value for a VFR file; per-frame timestamps must be inspected to detect VFR — [Shotcut forum](https://forum.shotcut.org/t/why-shotcut-think-the-mp4-as-variable-frame-rate/48999).
- PyAV gives each decoded frame's presentation time (`Frame.pts`, `Frame.time`, `Frame.time_base`) — [PyAV Frame API](https://pyav.basswood.io/docs/stable/api/frame.html).
- Albl et al. compare linear interpolation (Noguchi 2007) and spline interpolation (Nischt 2009) as baselines for sub-frame trajectory models. Locally linear models fail on strongly non-linear trajectories — [ar5iv 1704.06843](https://ar5iv.labs.arxiv.org/html/1704.06843).
- VisualSync cannot handle non-uniform playback speed, and its error grows when the frame rate is halved (mean 112.6 → 157.2 ms) — [arXiv 2512.02017](https://arxiv.org/html/2512.02017v1).

### Inferences
- **[in-house] Interpolation error estimate.** For a sinusoidal wrist motion of amplitude A and frequency f, the maximum linear-interpolation error between samples spaced h apart is about A(2πf)²h²/8.
  - With A = 0.15 m and f = 3 Hz (plausible for fast signing): h = 33 ms gives ≈ 7 mm; h = 52 ms (the largest VFR gap) gives ≈ 18 mm.
  - Cubic-spline error scales with h⁴ and is roughly an order of magnitude smaller at these h.
  - In 2D at ~500 px/m (480p view), that is about 3.5–9 px for linear interpolation: comparable to or larger than keypoint noise. Interpolation choice therefore matters, especially near motion reversals where the velocity changes sign.
- **[in-house] Why the 60 fps view should be the reference.**
  - Triangulating on the 60 fps grid means only the VFR view is interpolated. Its query times then fall at most ~half a gap (≤ 26 ms) from a real sample.
  - Using the VFR view as the reference instead throws away half the iPhone frames and interpolates the high-quality view.
  - The code currently uses "the first view's time grid", which is sometimes the VFR one; this should be fixed regardless.
- **[in-house] Filter in true time.** Apply the 6 Hz Butterworth after resampling to the uniform 60 fps grid. Alternatively, use a smoothing spline with the equivalent cut-off directly on the non-uniform samples. A zero-lag Butterworth applied to non-uniform VFR samples treated as uniform distorts both timing and amplitude.
- **[in-house] VFR frames do not form a regular grid.** Check for duplicated or dropped frames in the 480p file: identical consecutive images, or intervals near 2× nominal. The re-encoder may have duplicated frames with fresh PTS; those frames carry no new information and should be dropped before spline fitting.
- **[in-house] Interpolate uncertainty too.** Keypoint noise for interpolated frames is correlated across neighbours. The Monte Carlo should perturb the original VFR samples and then re-interpolate, rather than perturbing interpolated values independently.

### Gaps
- No source quantifying interpolation error for human-pose keypoints from VFR phone video was found. The error estimate above is analytic, in-house.

## 4. Video↔IMU-suit alignment without events

### Takeaway
The established event-free method for camera↔IMU temporal calibration is cross-correlation of rotation-invariant signals, typically the angular-velocity norm, computed from each modality. Refine it with sub-sample peak interpolation or continuous-time optimisation. Lab camera–IMU systems reach sub-ms precision (Kalibr lineage). Wearable/video studies report much coarser figures: SyncWISE reaches 90% within a 700 ms tolerance from wrist accelerometry on long free-living videos. A multi-signal consensus of segment angular-velocity norms, knuckle and wrist linear speed, and possibly acceleration norms, with a parabolic or spline peak fit, is the best software option here.

### Cited Findings
- **Cross-correlating angular-velocity norms.**
  - A granted patent aligns an IMU and a camera by computing angular velocity from each stream and picking the shift with maximal normalised cross-correlation — [USPTO 12361720](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12361720).
  - The visual-inertial literature uses the same principle: angular-velocity norms from camera and IMU should match at the same instant, and the offset is the lag maximising their correlation. Camera angular velocity comes from differentiating estimated rotations — [arXiv 1808.00692 (Qin & Shen, online temporal calibration)](https://arxiv.org/pdf/1808.00692); [arXiv 1611.09498](https://arxiv.org/pdf/1611.09498).
- **Founding work.**
  - Mair et al. (2011) estimate the camera–IMU time offset as an independent preprocessing step, before spatial alignment, using cross-correlation or phase congruency — [TUM PDF (unreachable when fetched)](https://archivedsite.air.in.tum.de/Main/Publications/mair2011b.pdf).
  - Kelly & Sukhatme aligned camera and IMU rotation curves and are credited with the first principled treatment of camera–IMU time offset. Li & Mourikis (2014) show that an uncorrected offset adds unmodelled error, and estimate it online — [Li & Mourikis IJRR 2014](https://intra.ece.ucr.edu/~mourikis/papers/Li2014IJRR_timing.pdf).
- **Precision in the Kalibr / continuous-time calibration lineage.**
  - Rehder's ETH thesis reports temporal precisions on the order of 1/20 ms for camera–laser calibration — [ETH Research Collection](https://www.research-collection.ethz.ch/server/api/core/bitstreams/f3263ec4-4c7d-4d62-8836-4e7d23ac9d67/content).
  - A robotics paper reports σ ≈ 0.5 ms for IMU–IMU offsets estimated by correlation plus gradient refinement and averaged across runs and axes — [Boxi, arXiv 2504.18500](https://arxiv.org/pdf/2504.18500).
  - These are hardware-rich, high-rate settings. Upper bounds on what is possible, not expectations for phone video.
- **Wearable-to-video results are much coarser.**
  - SyncWISE estimates acceleration from video and compares it with wearable accelerometry in sliding windows. It reports 90% sync accuracy within a 700 ms tolerance on 163 free-living videos (45.2 h, 21 participants), and state-of-the-art results on CMU-MMAC — [Illinois Experts](https://experts.illinois.edu/en/publications/syncwise-window-induced-shift-estimation-for-synchronization-of-v/); [Hackster summary](https://www.hackster.io/news/have-you-got-the-time-e39c0e8c2f5f).
  - A TU Wien thesis aligning body-worn IMUs (IMU↔IMU) by windowed cross-correlation on marker actions reports 4.8 ms for full-body walking and 17.0 ms for upper-body-only clapping — [TU Wien repositum](https://repositum.tuwien.at/handle/20.500.12708/226907).
  - The Sevivi tool aligns smartphone video with IMUs by deriving acceleration from both streams — [Sevivi docs](https://sevivi.readthedocs.io/en/latest/background.html).
  - A magnetometer-based IMU sync paper reports a maximum error of 40 ms per hour, limited by a 25 Hz sample rate — [Frontiers Comp. Sci. 2024](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2024.1385392/pdf).
- **Drift caveat.** Pose2Sim warns that cameras may drift over long captures, so it recommends captures no longer than a few minutes — [Pose2Sim README](https://github.com/perfanalytics/pose2sim/blob/main/README.md).

### Inferences
- **[in-house] The Rokoko FBX is not raw IMU data.** It is a fused, skeleton-solved animation at 60 fps, so there is no raw gyro or accelerometer to correlate. Derive the same quantities from both sides instead: segment angular-velocity norms of the forearm and upper arm (from FBX bone rotations, and from triangulated video segment directions as the rate of change of unit vectors), and linear speed of the knuckle centre or wrist. These are rotation- and frame-invariant, so no spatial calibration between suit and camera frames is needed.
- **[in-house] Multi-signal consensus.**
  - Estimate the lag separately from each of 4–8 signals: left/right forearm ω-norm, upper-arm ω-norm, knuckle-centre speed, wrist speed.
  - For each, take the peak of the normalised cross-correlation, refined by a parabolic fit to the three samples around the peak. Or upsample the correlation by FFT zero-padding, or minimise a continuous-lag L2 cost with spline-interpolated FBX signals.
  - Combine with a robust weighted median, weights from each peak's sharpness. The spread between signals is a direct, non-circular uncertainty estimate. The current ~8 ms wrist-speed vs elbow-angle-rate agreement is one instance of this.
- **[in-house] Circularity warning.** The elbow-angle-rate signal is the derivative of a tested angle (elbow flexion). Choosing or refining the lag with it partly aligns the tested quantity and can bias toward equivalence. Pre-register a lag signal set that excludes the nine tested angles and their derivatives (e.g. linear speeds and segment ω-norms). Report the elbow-rate lag only as a sensitivity check. A segment ω-norm is not one of the nine unsigned inter-segment angles, though it shares the same segments; mention this residual dependence.
- **[in-house] Expected accuracy.** Peak localisation precision for cross-correlation scales roughly as 1/(signal bandwidth × √(effective SNR × duration)). With motion band-limited to ~6 Hz and only a few seconds of signing (effective n ≈ 2–7 independent motion events), expect about 5–15 ms. The ~8 ms inter-signal agreement is consistent with this. Sub-ms Kalibr-type figures need high-rate raw gyros and textured scenes and are not attainable here.
- **[in-house] Drift.** Estimate a linear time scale between suit and video by fitting the lag in two halves of the take (early vs late window), or by fitting (β, ρ) in a continuous-lag cost. For takes of ≤ 30 s, expected drift is under a millisecond unless the FBX export resampled time (e.g. a 59.94 vs 60 fps mismatch would accumulate 1 ms per second ≈ 10 ms over 10 s). Check the FBX time mode and the iPhone's nominal rate (59.94 vs 60) explicitly; that mismatch is the most plausible real "drift".
- **[in-house] Restrict the window.** Compute the cross-correlation on the FBX-defined sign window plus margins, not the full recording. Long rest periods add near-zero signal that broadens the peak, and cyclic signing can produce secondary peaks one movement period away. Reject estimates where the second-best peak is within ~10% of the best (VisualSync uses a similar ratio test with threshold 0.1 — [arXiv 2512.02017](https://arxiv.org/html/2512.02017v1)).

### Gaps
- No published accuracy figure for camera-to-IMU-suit (fused skeleton) cross-correlation sync was found. SyncWISE (700 ms tolerance) addresses a much harder free-living case.
- Mair et al. 2011 and Kelly & Sukhatme ms-level results could not be retrieved (TUM archive unreachable).
- The original Furgale, Rehder & Siegwart (IROS 2013) temporal calibration paper's accuracy figures were not retrieved; only Rehder's thesis figure was.

## 5. Uncertainty: lag standard error and propagation into the Monte Carlo without circularity

### Takeaway
Treat both lags (video↔video and video↔FBX) as uncertain parameters with an estimated standard error and draw them in every Monte Carlo replicate, instead of holding them fixed. Estimate the standard error by at least two of: cost-curvature (Laplace) approximation, moving-block bootstrap over time, and spread across independent signals. Use the largest as a conservative choice. Never use the tested angle differences to select or weight the lag.

### Cited Findings
- **Uncorrected time offsets add unmodelled error.** Li & Mourikis treat the offset as a state to estimate with its own covariance — [Li & Mourikis IJRR 2014](https://intra.ece.ucr.edu/~mourikis/papers/Li2014IJRR_timing.pdf). Qin & Shen also estimate it online with uncertainty — [arXiv 1808.00692](https://arxiv.org/pdf/1808.00692).
- **Averaging across runs, axes and intervals.** An IMU-offset study obtained σ ≈ 0.5 ms this way, an example of using agreement across independent estimates as the uncertainty measure — [arXiv 2504.18500](https://arxiv.org/pdf/2504.18500).
- **Ambiguous energy landscapes are rejected.** VisualSync rejects pairs whose cost has an ambiguous landscape (best-to-next-best local-minimum ratio below 0.1, or more than two minima), then combines pairwise estimates with Huber IRLS — [arXiv 2512.02017](https://arxiv.org/html/2512.02017v1).
- **Project fact (from CLAUDE.md, not re-verified):** frames within one take are autocorrelated (effective n ≈ 2–7), and frame-level bootstraps gave 11–34% false equivalence. Any bootstrap of the lag must therefore resample blocks, not frames.

### Inferences
- **[in-house] Curvature (Laplace) SE.**
  - For a least-squares cost C(β) with residual variance σ² and N effective observations, SE(β) ≈ √(2σ²/C″(β̂)).
  - Because frames are autocorrelated, inflate by √(N_frames/N_eff) or estimate with a block bootstrap instead.
  - Cheap, but optimistic if the noise model is wrong.
- **[in-house] Moving-block bootstrap.**
  - Resample blocks of about 0.3–0.5 s (longer than the 6 Hz filter memory and the typical movement duration) of the joint 2D tracks or speed signals, and re-run the full lag estimation, including coarse cross-correlation, so that cycle-slip risk is captured.
  - With only a few seconds of signing there are few blocks. Prefer a parametric bootstrap: add the project's estimated keypoint noise (still-frame noise model + TTA spread) to the 2D tracks and re-estimate the lag. This plugs directly into the existing `conditional_equivalence.py` Monte Carlo.
- **[in-house] Signal-spread SE.** Use the standard deviation (or MAD × 1.4826) of lags from independent signals (section 4), and for video↔video the audio-lag vs pose-lag difference. Use it as a floor on the SE.
- **[in-house] Propagation.**
  - In every Monte Carlo draw, re-estimate the lags from the perturbed data. This is the most faithful option: it captures correlation between lag error and calibration error.
  - If too slow, draw β_vv ~ N(β̂_vv, SE_vv²) and β_vf ~ N(β̂_vf, SE_vf²), with SEs from the bootstrap, then resample the VFR view with the spline and the FBX with its spline at the shifted times.
  - Report the share of RMS-bound inflation due to lag uncertainty, by running with lags fixed versus drawn.
- **[in-house] Non-circularity rules (pre-register in `equivalence_margins.json` before the next take).**
  1. Lag signals exclude the nine tested angles and their time derivatives.
  2. Video↔video lag is chosen by reprojection error, which is geometric and independent of the angle comparison.
  3. Video↔FBX lag uses linear speeds and segment ω-norms only.
  4. The lag window is the FBX-defined sign window, fixed before angle comparison.
  5. A sensitivity table shows the TOST decision at β̂ ± 2 SE. A decision that flips within that range is reported as lag-sensitive.
- **[in-house] What the lags plausibly do to the angles.** A 10 ms video↔FBX lag error at a peak angular rate of about 300°/s for a fast elbow gives up to 3° instantaneous angle difference. Its RMS contribution over the sign is smaller (maybe 1–2°), but it is not negligible against the ~9° true-RMS pass threshold at ±15°. Lag uncertainty should therefore be propagated, not ignored. Check with `single_take_simulation.py` by injecting known lag errors.

### Gaps
- No published method retrieved specifically for propagating temporal-alignment uncertainty into equivalence tests of biomechanical angles. The recommended propagation scheme is in-house.
- No source gives recommended block length for block bootstrap of short human-motion time series; the 0.3–0.5 s choice is in-house.
