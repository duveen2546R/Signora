# Validation norms for inertial mocap suits (upper limb), reference standards, margins and analyses

Scope note: I used about 15 searches and fetches (Consensus MCP plus web). PubMed Central full texts were mostly blocked by a CAPTCHA, so several numbers come from abstracts or secondary summaries. These are flagged. Unless a value is marked "full text", it comes from the abstract or search snippet.

## 1. Elbow, shoulder and wrist accuracy of Rokoko, Xsens, Perception Neuron and similar IMU suits vs optical capture

### Takeaway
Against optical marker-based capture, commercial IMU suits usually reach about 2–7° RMSE for elbow and shoulder flexion/extension in simple or sagittal tasks. Errors grow to 10–15° or more for transverse or out-of-plane angles, fast or complex tasks, and long trials or magnetically disturbed trials. Offsets (bias) of around 10° at the elbow are common even when waveform shape matches well (r or CMC above 0.85). That is the main reason authors conclude "good for patterns, worse for absolute angles". Rokoko has almost no peer-reviewed validation.

### Cited Findings
**Xsens/Movella**
- Xsens MVN vs Qualisys, tennis forehand, N=29: CMC ≥0.95 for most variables. RMSE ranged 1.5–6.7° (rated "good to tolerable"), except elbow transverse plane at 13.1° (CMC 0.79). 1D SPM showed agreement except elbow transverse — [Pedro et al. 2021, J Biomech](https://consensus.app/papers/details/133fee8efeb95b75a503b7f83cb160cb/?utm_source=claude_code)
- Xsens vs optical, military tasks, N=18: flexion-extension RMSE below 9° (lower limb) and below 15° (upper limb). The authors state that "the underlying biomechanical model and associated coordinate systems appear to influence RMSE values the most" — [Mavor et al. 2020, Sensors](https://consensus.app/papers/details/a2c52d469d7d5d04b1efdf90a3160fca/?utm_source=claude_code)
- Xsens with an Optotrak cluster fixed on every IMU, N=12, handling tasks: "technological error" (same segment definitions) stayed under 5° RMSE. This design isolates sensor error from biomechanical-model error — [Robert-Lachaine et al. 2017, Med Biol Eng Comput, DOI 10.1007/s11517-016-1537-2](https://unpaywall.org/10.1007%2FS11517-016-1537-2) (abstract via search snippet)
- Magnetic disturbance (Xsens, Optotrak clusters, N=12): joint-angle RMSE was highest for rotations about the longitudinal (Y) axis and during longer disturbances (tested 30–240 s). Error stayed high right after a disturbance and returned near baseline after about 30 s in an undisturbed field. Correction methods helped only modestly or poorly — [Robert-Lachaine et al. 2017, Applied Ergonomics](https://consensus.app/papers/details/225bc85b90fc53c48e100c035bfc5693/?utm_source=claude_code)

**Perception Neuron (Noitom)**
- Perception Neuron vs Vicon, N=10, walk/jog/floorball shot, 120 Hz (full text): elbow flexion/extension RMSE generally below 4°, Pearson r 0.84–0.96. However, Bland–Altman **bias exceeded 10° for elbow flexion/extension in all movements**. Shoulder abduction/adduction RMSE was 5.36–15.15°. Errors appeared heteroscedastic (larger at larger angles). The authors blamed drift, magnetic perturbation, soft-tissue artefact and short trials between calibrations, and concluded the system is unsuitable for replicating raw joint angles but adequate for normalised angles and movement patterns — [Choo et al. 2022, PLoS ONE](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0262730)
- Perception Neuron vs Vicon, upper-body functional ROM (neck, thorax, shoulder): valid for most upper-body ROM to within 5°. Systematic biases ≤4.5° and random error ≤±4.5° except neck extension — [Sers et al. 2020, Measurement, DOI 10.1016/j.measurement.2019.107024](https://repository.lboro.ac.uk/articles/Validity_of_the_Perception_Neuron_inertial_motion_capture_system_for_upper_body_motion_analysis/9779261) (via search summary; no elbow-specific value found)
- Perception Neuron lower limb vs OptiTrack, N=20, two sessions: CMC 0.47–0.99, RMSE 3.57–13.14° — [Shuai et al. 2022, Sensors](https://consensus.app/papers/details/d9d7923b1cb75b358487cfe916a15960/?utm_source=claude_code)

**Rokoko Smartsuit Pro**
- One IEEE MeMeA conference paper compared Smartsuit Pro with OptiTrack for shoulder and elbow flexion/extension ROM (three motions × three repetitions). It reports Pearson r of 0.70 (shoulder) and 0.77 (elbow), sub-degree RMSE values (0.31–0.66°) that look implausible and are reported ambiguously, and Bland–Altman "comparable". Sample size was not visible — [Mihcin et al. 2019, IEEE MeMeA, DOI 10.1109/memea.2019.8802208](https://avesis.istanbul.edu.tr/yayin/b6335d1a-ef27-46a3-9eff-efe6700f667f/investigation-of-wearable-motion-capture-system-towards-biomechanical-modelling)
- Rokoko vs Kinovea (smartphone 2D video), lower limb, N=5: RMSE ≤3.51°, r=0.96, Bland–Altman. The reference here was itself video — [Çıklaçandır et al. 2022, ASYU conference](https://consensus.app/papers/details/c9fc161f330b53da8da957f987fcc55d/?utm_source=claude_code)
- A practitioner review notes drift with the first-generation Smartsuit Pro. This is non-peer-reviewed, lower-grade evidence — [bassdrum substack review](https://bassdrum.substack.com/p/rokoko-technical-director-reviews)

**Other IMUs and pooled evidence**
- Valor IMU vs Vicon: mean absolute difference 1.81–17.46°, RMSE 1.89–16.62°, ICC 0.57–0.99 across joints and tasks — [Smith et al. 2024, Sensors](https://consensus.app/papers/details/8fef8a8c838c587299bfe3fe6d3ea130/?utm_source=claude_code)
- Meta-analysis, upper-extremity ROM, IMU vs optical (51 studies, 16 pooled): elbow flexion-extension r=0.954, ICC=0.929, **pooled mean difference 10.61°** (not significant, p=0.36, which means it is highly heterogeneous). Shoulder flexion-extension mean difference −3.19°. Wrist flexion-extension −4.20°. Shoulder internal/external rotation −9.13° (p<0.0001) — [Li et al. 2024, Wearable Technologies](https://consensus.app/papers/details/e18407ddfaca55d5baddb82df791b838/?utm_source=claude_code)
- Systematic review (42 studies): validity is higher for simple tasks and lower-limb joints. Upper-limb RMSE ranges attributed to it are shoulder 0.2–64.5°, elbow 0.2–30.6° and wrist 2.2–30°. These ranges come from a secondary citation and were not verified — [Poitras et al. 2019, Sensors](https://consensus.app/papers/details/7888127f7af9572ba710afa27db7170a/?utm_source=claude_code); ranges via [search summary of Li et al.](https://www.mdpi.com/1424-8220/23/14/6535/html)

### Inferences
- For a well-calibrated suit with short trials, an elbow flexion RMSE of about 3–6° against optical capture is a realistic expectation. A constant offset of 5–10° is plausible from skeleton and calibration differences alone.
- Speed and complexity raise error. Studies of fast sports tasks report larger errors than studies of slow ROM tasks. No sign-language-speed study was found.
- Sign performances that are long, or recorded near metal (desks, laptops, phones), risk drift and magnetic heading error. Heading error mostly affects axial rotations, which also propagate into decomposed elbow and forearm angles.

### Gaps
- No peer-reviewed journal validation of Rokoko Smartsuit Pro II against Vicon or Qualisys for upper-limb angles was found. The only study is one conference paper with questionable numbers.
- Manufacturer white papers (Xsens/Movella, Rokoko) were not retrieved.
- I could not open the full texts of Poitras 2019 or Li 2024 to confirm per-joint tables.

## 2. Typical validation designs and statistics: N, trials, tasks, RMSE, Bland–Altman, ICC, CMC, SPM, TOST, and margin justification

### Takeaway
Typical designs use 10–30 healthy adults, several repeated trials of standardised tasks, and simultaneous capture against an optical criterion. They report waveform RMSE plus correlation or CMC, often add Bland–Altman bias and LoA and ICC, and increasingly use SPM. Acceptability is usually judged against a rule of thumb (RMSE ≤5° "reasonable", sometimes LoA ±10° in ergonomics) traced to gait-reliability literature (McGinley 2009). Formal TOST equivalence testing is rare in this field. A ±5° margin is defensible but tight for elbow given the reported biases.

### Cited Findings
- Sample sizes in the studies above: 10 ([Choo 2022](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0262730)), 12 ([Robert-Lachaine 2017](https://consensus.app/papers/details/225bc85b90fc53c48e100c035bfc5693/?utm_source=claude_code)), 18 ([Mavor 2020](https://consensus.app/papers/details/a2c52d469d7d5d04b1efdf90a3160fca/?utm_source=claude_code)), 20 ([Shuai 2022](https://consensus.app/papers/details/d9d7923b1cb75b358487cfe916a15960/?utm_source=claude_code)), 29 ([Pedro 2021](https://consensus.app/papers/details/133fee8efeb95b75a503b7f83cb160cb/?utm_source=claude_code)), 10 ([Francia 2026](https://consensus.app/papers/details/0cd0a4a588bd51eaa1a1ee7e867a5563/?utm_source=claude_code)). Markerless gait validations go larger: 35 participants, 114 trials, 228 cycles ([Ripic 2023](https://consensus.app/papers/details/37ed848240605735b559fbcbc13a6090/?utm_source=claude_code)); 437 trials ([Turner 2024](https://consensus.app/papers/details/9245df4285745451bb5953b029c5e7b1/?utm_source=claude_code)).
- Statistics used: RMSE and CMC ([Shuai 2022](https://consensus.app/papers/details/d9d7923b1cb75b358487cfe916a15960/?utm_source=claude_code)); RMSE, CMC and 1D SPM ([Pedro 2021](https://consensus.app/papers/details/133fee8efeb95b75a503b7f83cb160cb/?utm_source=claude_code)); Pearson, RMSE and Bland–Altman ([Choo 2022](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0262730)); RMSE, %RMSE, ROM accuracy, ICC, Spearman, Bland–Altman and Wilcoxon ([Francia 2026](https://consensus.app/papers/details/0cd0a4a588bd51eaa1a1ee7e867a5563/?utm_source=claude_code)); RMSE, ΔROM, r and ICC ([Ripic 2023](https://consensus.app/papers/details/37ed848240605735b559fbcbc13a6090/?utm_source=claude_code)); repeated-measures ANOVA on RMSE ([Robert-Lachaine 2017](https://consensus.app/papers/details/225bc85b90fc53c48e100c035bfc5693/?utm_source=claude_code)).
- Thresholds cited in Choo et al. (full text): RMSE up to 5° is "regarded as reasonable" by most studies, and errors above 5° may mislead clinical interpretation. LoA of 10° is acceptable for occupational biomechanics. Mean bias below 10° is used as the benchmark. Optical reference accuracy is <1° static and <1.5° dynamic RMS — [Choo et al. 2022](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0262730)
- Pedro et al. label 1.5–6.7° as "good to tolerable" — [Pedro 2021](https://consensus.app/papers/details/133fee8efeb95b75a503b7f83cb160cb/?utm_source=claude_code)
- McGinley et al. 2009 (gait 3D kinematics reliability, 15 manuscripts plus 8 abstracts): most error estimates were small, with hip and knee transverse plane worst, and clinically acceptable errors are possible but not always achieved — [McGinley et al. 2009, Gait & Posture, DOI 10.1016/j.gaitpost.2008.09.003](https://www.doi.org/10.1016/j.gaitpost.2008.09.003). The commonly cited bands (≤2° acceptable, 2–5° "reasonable" but needing consideration in interpretation, >5° a cause for concern) come from this paper, but the search abstract did not display them. Verify against the full text before quoting.
- McGinley's thresholds are about **test–retest reliability of gait** (marker-based), not between-system validity of upper limb. Applying them to elbow validation is a borrowed convention — [McGinley 2009](https://salford-repository.worktribe.com/output/1452559/the-reliability-of-three-dimensional-kinematic-gait-measurements-a-systematic-review)
- TOST in a similar context: IMU vs Kinect upper-limb angles, N=10, a **±10° acceptance margin**, plus MAE/RMSE. Shoulder was equivalent. For the elbow, TOST was "significant" but the equivalence interval slightly exceeded the bound, so agreement was weak. The authors framed this as proof of concept against a "practical benchmark" — [Ceccarelli et al. 2026, Biomechanics](https://consensus.app/papers/details/d479416580845f0680a6a3787b3963de/?utm_source=claude_code)
- Bland–Altman defines LoA but does not say whether they are acceptable. Acceptable limits must be set **a priori** from clinical or other needs — [Giavarina 2015, Biochemia Medica](https://consensus.app/papers/details/7939012957ff5ed797557cfed025a7dd/?utm_source=claude_code). Bland–Altman remains the standard for method comparison, and critics (Hopkins, Krouwer) were answered — [Mansournia et al. 2020](https://consensus.app/papers/details/fc97194657b2519e9391e16c49163136/?utm_source=claude_code). An inferential extension tests equivalence of means (accuracy), variances (precision) and bisector concordance — [Silveira et al. 2024](https://consensus.app/papers/details/03ab450e1f6256168ee8dec2ea5b6b0a/?utm_source=claude_code)

### Inferences
- A single-performance, single-signer design is far below field norms of 10–30 participants with repeated trials. A TOST on RMS difference within one take tests agreement for that take, but the inference does not generalise to the suit. Frames within a take are strongly autocorrelated, so the effective sample size is much smaller than the frame count, and block or bootstrap methods are needed.
- A ±5° margin matches the "RMSE ≤5° reasonable" convention. But Li et al.'s pooled elbow mean difference (about 10°) and Choo et al.'s elbow bias (above 10°) suggest a suit-vs-optical comparison could itself fail ±5° on absolute angles. Adding about 2–6° of video error makes failure more likely unless the bias is removed (offset-corrected or ROM-based metrics).
- The field rarely uses TOST, so using it is a methodological strength. The margin justification should be stated explicitly, with sources for both the 5° convention and its limits.

### Gaps
- I found no consensus guideline (COSMIN-like, specific to kinematic system validity) that prescribes a minimum N or margin for upper-limb suit validation.
- No formal sample-size or power calculations were seen in the suit studies retrieved.

## 3. Is markerless video an acceptable reference? The no-gold-standard problem

### Takeaway
Optical marker-based capture is the accepted criterion. Markerless video, including two-smartphone systems, is itself still under validation, with pooled errors of about 5° and worse upper-limb than lower-limb performance. Studies that compare two non-gold-standard systems explicitly frame the result as **inter-method discrepancy**, an upper bound on combined error, not as accuracy, validity or equivalence to truth.

### Cited Findings
- OpenCap (two smartphones) vs optical, lower limb: grand mean MAE 3.85° and RMSE 4.34°. Sagittal CMC above 0.94; frontal and transverse CMC 0.47–0.78 — [Turner et al. 2024, J Biomech](https://consensus.app/papers/details/9245df4285745451bb5953b029c5e7b1/?utm_source=claude_code)
- OpenCap meta-analysis (11 studies, 184 participants): pooled RMSE 5.88°, falling to 5.20° after sensitivity analysis and 4.94° after trim-and-fill. Performance drops for high-velocity and complex movements — [Çabuk et al. 2025, Biology of Sport](https://consensus.app/papers/details/f59b1304923c517d90baa460ab4de789/?utm_source=claude_code)
- OpenCap scoping review (51 studies): accuracy is higher for lower than upper extremity and for sagittal planes, and occlusion robustness still needs work — [Zhang et al. 2026, Frontiers in Digital Health](https://consensus.app/papers/details/2213abd4e01f5014b3deaf0c8158090d/?utm_source=claude_code)
- Markerless pose estimation vs optoelectronic, upper limb (shoulder, elbow, wrist flexion-extension), N=10: elbow ICC above 0.91 in full ROM. There was **systematic underestimation of maximum flexion** (magnitude bias from occlusion and joint geometry) — [Francia et al. 2026, Applied Sciences](https://consensus.app/papers/details/9fabcdafd4645eb7ac96cfb586d2f6b9/?utm_source=claude_code)
- Markerless (CapturyStudio, 8 cameras) vs Xsens, i.e. two indirect systems, N=10: ICC ≥0.87, but median elbow discrepancy about 12°. The authors state that because both systems are indirect, the values represent "the discrepancy between two methods and an upper bound on the error" rather than absolute accuracy. Its magnitude is comparable to clinically meaningful goniometric changes, so the system suits pattern analysis, not absolute angles — [Francia et al. 2026, Sensors](https://consensus.app/papers/details/0cd0a4a588bd51eaa1a1ee7e867a5563/?utm_source=claude_code)
- IMU vs Kinect study: the authors call Kinect a "practical benchmark" and explicitly say the results are proof of concept, not definitive validation — [Ceccarelli et al. 2026](https://consensus.app/papers/details/d479416580845f0680a6a3787b3963de/?utm_source=claude_code)
- Rokoko was "validated" against Kinovea smartphone video, an example of a weak-reference design with N=5 — [Çıklaçandır 2022](https://consensus.app/papers/details/c9fc161f330b53da8da957f987fcc55d/?utm_source=claude_code)

### Inferences
- A two-phone markerless system with about 2–6° elbow RMSE vs optical capture is not an accepted criterion. Comparing the suit to it can show **agreement and interchangeability between two methods** within a margin, not suit validity.
- If the errors are independent, the expected RMS difference is roughly √(suit² + video²). For example, suit 4° and video 4° give about 5.7°, which already exceeds a ±5° margin. So a ±5° RMS-difference margin implicitly needs both systems to be better than about 3.5° each. Failing equivalence would therefore be uninformative about which system is wrong.
- Recommended framing, consistent with Francia 2026 and Bland–Altman practice: call it a method-agreement study, pre-specify the margin, report bias and LoA with CIs, and ideally anchor at least a subset against optical capture (or a goniometer or static poses) so that each system's error is known. Static reference poses (for example the elbow at known angles) give a partial ground truth.

### Gaps
- I did not retrieve formal statistical literature on latent-truth or errors-in-variables models (for example Dunn's method-comparison models or Deming regression) applied to kinematics. They are worth adding from the statistics literature.

## 4. Skeleton and joint-centre definition mismatch (retargeted suit skeleton vs video keypoints)

### Takeaway
Differences in model, segment coordinate system and joint-centre definition are repeatedly identified as the dominant source of between-system angle differences, often larger than sensor error. They produce systematic offsets of several degrees in sagittal angles and 5–10° or more out of plane.

### Cited Findings
- Xsens vs optical: "the underlying biomechanical model and associated coordinate systems appear to influence RMSE values the most." Upper-limb RMSE was up to 15°, versus under 5° technological error when the same segment definitions were used — [Mavor et al. 2020](https://consensus.app/papers/details/a2c52d469d7d5d04b1efdf90a3160fca/?utm_source=claude_code); [Robert-Lachaine et al. 2017 MBEC](https://unpaywall.org/10.1007%2FS11517-016-1537-2)
- Markerless vs marker-based, N=30 running: joint centres differed by ≤3 cm, sagittal angles by ≤5°, and frontal/transverse angles by 5–10°. Differences were "sensitive to segment coordinate system definitions" — [Kanko et al. 2024, J Appl Biomech](https://consensus.app/papers/details/463408c3ab1b5972b865b3220f489080/?utm_source=claude_code)
- Pose-estimation joint centres (OpenPose, AlphaPose, DeepLabCut) vs markers: systematic offsets of about 30–50 mm at hip and knee, attributed to mislabelled training data. Ankle offsets were 1–15 mm — [Needham et al. 2021, Sci Rep](https://consensus.app/papers/details/aa33d7bd92135d3fbbb6de2b7237908d/?utm_source=claude_code)
- Ripic 2023 calls for "improvements in … markerless keypoint model definitions, and standardization of comparison study protocols" — [Ripic et al. 2023](https://consensus.app/papers/details/37ed848240605735b559fbcbc13a6090/?utm_source=claude_code)
- Even within one IMU suit, calibration-pose differences (T-pose vs N-pose) and zeroing affect offsets. Choo et al. found bias above 10° at the elbow despite RMSE below 4°, i.e. offset-dominated after their processing — [Choo 2022](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0262730)

### Inferences
- Mixamo-style retargeted bones are not anatomical: bone lengths and rest-pose orientations are rescaled, and the elbow "angle" is a bone-rotation value relative to the rest pose. Video keypoints sit at estimated anatomical centres. A constant offset of roughly 5–10° at the elbow is plausible, and an amplitude-dependent (scaling) bias is possible if the rest-pose carrying angle or forearm twist is distributed differently. This is an inference; I found no study that measured Mixamo retarget error directly.
- Common mitigations: compute both angles from 3D joint positions with the same definition (the angle between upper-arm and forearm vectors). Align at a static calibration pose (subtract the offset), then report offset-removed RMSE separately from raw bias. Use ROM or peak differences, and use SPM to localise disagreement in time.

### Gaps
- I found no quantitative study of retargeting (FBX/Mixamo) error on joint angles.

## 5. Mocap validation for sign language or fine upper-limb and hand gestures

### Takeaway
Sign-language mocap literature evaluates mostly through **perceptual intelligibility with signers** and capture-pipeline quality (marker labelling, glove calibration). It does not use angle-level statistical validation against a criterion. I found no published equivalence or TOST validation of a suit for signing.

### Cited Findings
- Alexanderson & Beskow 2015 (key word signing avatar): optical markers work well for body and proximal joints, while gloves are better for distal fingers. A reduced 11-marker set plus glove data was about as intelligible as 21 markers. With 25 sign-fluent raters, 73% of signs were correctly identified and 13% were wrong — [review summary](https://a11y-paradise.onrender.com/reviews/69cda479ac5300caf88ae0fa) (secondary summary; verify against original)
- French Sign Language avatar data, perceptual rating by 41 participants (intelligibility, accuracy, realism) — [LREC 2020](https://aclanthology.org/2020.lrec-1.736)
- CyberGlove3 semi-automatic calibration for sign corpora — [LREC 2016 workshop](https://www.sign-lang.uni-hamburg.de/lrec/pub/16020.html)
- Sensor gloves give acceptable results but err with finger proximity and drift. A colour-glove hybrid reached 97% correct marker assignment on German Sign Language data — [TH Köln 2024 preprint](https://cg.web.th-koeln.de/wp-content/uploads/2024/02/Deep_neural_labeling__Hand_pose_estimation_using_using_unlabled_motion_capture_data_with_color_gloves-_PREPRINT.pdf)
- DexAvatar used a 9-camera Vicon setup plus Manus gloves as the capture reference for fingerspelling (8 signers) — [arXiv 2512.21054](https://arxiv.org/pdf/2512.21054)

### Inferences
- For sign language, the field's de facto acceptance criterion is perceptual (comprehension by Deaf or fluent signers), with optical Vicon as the capture standard. An angle-equivalence study would be novel, but reviewers would likely expect it to be paired with optical capture or perceptual evaluation.
- Signing is fast and involves rapid forearm pronation/supination and wrist motion near the torso. Those are the conditions where both IMU error (axial, fast motion) and video error (occlusion, self-contact) increase.

### Gaps
- I found no study reporting elbow or wrist RMSE of IMU suits specifically during signing.
