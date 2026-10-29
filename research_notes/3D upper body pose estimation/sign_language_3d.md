# 3D Upper-Body and Hand Pose from Video in Sign Language Research and Products (as of Oct 2026)

Scope: what sign-language (SL) recognition, translation, production and assessment work uses to get 3D upper-body and hand poses from monocular video, and lessons for SignSure (a learner's webcam signing compared against Mixamo-style FBX reference animations). Years are given for each work; anything before 2024 is marked [older].

Note: the Consensus paper search tool returned a connection error (ECONNRESET), so all sources below come from web search and direct fetches of arXiv, CVF and project pages.

## 1. SL-specific 3D reconstruction: SGNify, SignAvatars, How2Sign 3D, Neural Sign Actors, and 2024-2026 work

### Takeaway
Every serious SL 3D reconstruction work since 2023 fits **SMPL-X** (body, hands and face; MANO for hand-only subsets) to monocular video. They do it by **optimisation (SMPLify-X style) on 2D keypoints**, starting from a general whole-body regressor (OSX, SMPLer-X, HaMeR) and adding SL-specific priors: linguistic, biomechanical, temporal and anti-interpenetration. The best reported method, DexAvatar (Dec 2025), still has about 30 mm upper-body and about 13 mm hand vertex error on the only SL benchmark (SGNify mocap, 57 German signs). These pipelines are offline and GPU-heavy, not webcam real-time.

### Cited Findings
**SGNify (CVPR 2023) [older]**
- SGNify adds linguistic constraints to SMPL-X fitting to make hand-pose estimates from SL video more reliable under occlusion and motion blur. It introduces two class-dependent constraints: hand-pose **symmetry** (following Battison's sign classes; it applies to the hands only, not the arms) and hand-pose **invariance** (the handshape is static, or moves from one pose to another, across a sign) — [CVPR 2023 paper](https://openaccess.thecvf.com/content/CVPR2023/papers/Forte_Reconstructing_Signing_Avatars_From_Video_Using_Linguistic_Priors_CVPR_2023_paper.pdf); [ar5iv](https://ar5iv.labs.arxiv.org/html/2304.10482)
- It defines eight sign classes, each with its own set of active constraints — [CVPR 2023 supplemental](https://openaccess.thecvf.com/content/CVPR2023/supplemental/Forte_Reconstructing_Signing_Avatars_CVPR_2023_supplemental.pdf)
- It outperformed state-of-the-art body-pose and shape methods on SL video. In a perceptual study its reconstructions were significantly more comprehensible and natural than earlier methods' — [MPI-IS page](https://is.mpg.de/publications/forte23-cvpr-sgnify)
- Code and data: [sgnify.is.tue.mpg.de](https://sgnify.is.tue.mpg.de/). Its mocap set (ground-truth SMPL-X from a 4D scanner plus mocap, signs about 1.7–3.5 s long) is the standard SL reconstruction benchmark — [arXiv 2304.10482](https://arxiv.org/pdf/2304.10482)
- Follow-up: Forte's PhD thesis (Tübingen, Nov 2025) adds **BioTUCH**, which detects self-touch through electrical bioimpedance between the wrists (skin contact lowers high-frequency bioimpedance). The contact timing is used to refine arm poses. This needs hardware, so it is not a vision-only method — [Tübingen thesis](https://bibliographie.uni-tuebingen.de/xmlui/handle/10900/172679); [MPI-IS](https://is.mpg.de/publications/forte25-phd-language)

**SignAvatars (ECCV 2024)**
- Dataset: about 70K clips, 153 signers, 8.34M frames (about 117 h), with SMPL-X whole-body annotations and a MANO hand-only subset. Sources: How2Sign (about 34K sentence-level ASL clips, Green Screen subset), PHOENIX14T (about 8.25K DGS clips), WLASL (about 21K word-level clips), and a HamNoSys subset (about 5.8K isolated signs from the PJM, DGS Corpus and Dicta-Sign corpora). Supports 3D SLR and 3D SL production from text, words or HamNoSys — [arXiv 2310.20436](https://arxiv.org/html/2310.20436); [GitHub](https://github.com/ZhengdiYu/SignAvatars); [ECCV paper](https://www.ecva.net/papers/eccv_2024/papers_ECCV/papers/00653.pdf)
- Annotation pipeline: OSX initialisation fused with ACR and PARE for robustness to occlusion and truncation. The 2D keypoints are a ViTPose-based whole-body model (COCO-WholeBody) **fused with MediaPipe through a confidence-guided filter**. The fitting energy combines 2D reprojection, SMPLify-X priors, temporal smoothness, angle limits and a **biomechanical hand term** (bone-length bounds, palm curvature, flexion and abduction limits). Shape is optimised early, then frozen per clip — [arXiv 2310.20436](https://arxiv.org/html/2310.20436)
- The authors say 2D-only annotation is insufficient because different signs can look identical in 2D (depth ambiguity). They report no established SL reconstruction benchmark, so SL accuracy is judged qualitatively; on the general EHF benchmark the biomechanical term lowers hand PA-MPVPE from 5.4 to 4.7 — [arXiv 2310.20436](https://arxiv.org/html/2310.20436)
- Internal inconsistency: the paper says "seven subsets" in one place but describes four elsewhere — [arXiv 2310.20436](https://arxiv.org/html/2310.20436)

**How2Sign (CVPR 2021) [older]**
- More than 80 h of multiview ASL with more than 35K aligned sentences. About 3 h were re-recorded in the CMU **Panoptic studio** (a dome with hundreds, reportedly more than 500, cameras), giving high-quality **3D keypoints** for that subset. There are 2D keypoints (OpenPose) for more than 6M frames — [arXiv 2008.08143](https://arxiv.org/pdf/2008.08143); [CVPR 2021](https://openaccess.thecvf.com/content/CVPR2021/html/Duarte_How2Sign_A_Large-Scale_Multimodal_Dataset_for_Continuous_American_Sign_Language_CVPR_2021_paper.html)

**Neural Sign Actors (CVPR 2024)**
- Text-to-3D SL production using a diffusion model on an anatomically informed GNN defined on the SMPL-X skeleton; it regresses SMPL-X poses directly. The authors annotated How2Sign (more than 16K word tokens) with SMPL-X using a hybrid regression-optimisation method and call it the first large-scale 3D ASL dataset — [arXiv 2312.02702](https://arxiv.org/pdf/2312.02702); [CVF](https://openaccess.thecvf.com/content/CVPR2024/html/Baltatzis_Neural_Sign_Actors_A_Diffusion_Model_for_3D_Sign_Language_CVPR_2024_paper.html)
- Its fitting uses OSX initialisation, then optimisation with a PCA mesh prior learned from AMASS and ARCTIC (as described by DexAvatar) — [DexAvatar arXiv 2512.21054](https://arxiv.org/html/2512.21054v1)

**DexAvatar (arXiv, Dec 2025), the current best SL reconstruction result I found**
- SMPL-X optimisation (L-BFGS) initialised from **SMPLer-X** (body) and **HaMeR** (hands). 2D keypoints come from **Sapiens** (body) and **HaMeR** (hands), with a Geman-McClure confidence-weighted reprojection loss. Lower-body joints are excluded — [arXiv 2512.21054](https://arxiv.org/html/2512.21054v1)
- It replaces VPoser with SL-specific VAE priors. **SignBPoser** is trained on SignAvatars and How2Sign 3D body data, filtered by range of motion and signing space. **SignHPoser** is trained on new mocap: 8 signers (6 Auslan, 2 ASL) fingerspelling 93 words in Manus gloves with a 9-camera Vicon system, retargeted to SMPL-X in Blender. Other terms: interpenetration (SMPLify-X style BVH self-collision), temporal smoothness, and biomechanical joint limits. SGNify's sign classifier decides one-handed versus two-handed, and for one-handed signs the non-dominant arm is dropped from the optimisation — [arXiv 2512.21054](https://arxiv.org/html/2512.21054v1)
- TR-V2V error (mm) on the SGNify benchmark for upper body without face / left hand / right hand. Lower is better.

  | Method | Upper body | Left hand | Right hand |
  |---|---|---|---|
  | FrankMocap | 78.07 | 20.47 | 19.62 |
  | PIXIE | 60.11 | 25.02 | 22.42 |
  | PyMAF-X | 68.61 | 21.46 | 19.19 |
  | SGNify | 55.63 | 19.22 | 17.50 |
  | OSX | 47.32 | 18.34 | 18.12 |
  | Neural Sign Actors | 46.42 | 16.17 | 15.23 |
  | EVA* | 40.38 | 13.73 | 13.68 |
  | **DexAvatar** | **30.13** | **13.53** | **13.08** |

  It reports a 35.11% upper-body improvement over the earlier state of the art. Swapping in VPoser gives a much worse upper-body error (36.79) — [arXiv 2512.21054](https://arxiv.org/html/2512.21054v1)
- Limitations: one small benchmark whose ground truth itself contains implausible hand poses; the hand prior covers fingerspelling only; it depends on off-the-shelf detectors that "often struggle with sign language data"; wrist rotations could not be transferred from the mocap; no runtime reported (offline, RTX 4090) — [arXiv 2512.21054](https://arxiv.org/html/2512.21054v1)

**Other 2024–2026 work**
- **Ivashechkin (Surrey PhD, Dec 2025):** a 2D-to-3D skeletal lifter with physical constraints (joint limits, symmetry) trained on multiview data; hand-crop features plus a temporal transformer for the hands; an occupancy network with an **intersection loss** that "significantly reduces hand intersections"; NeRF and 3DGS rendering. A diffusion variant was too slow for real-time use — [Surrey viva listing](https://www.surrey.ac.uk/events/20251216-improving-3d-human-pose-estimation-and-rendering-sign-language)
- **Ivashechkin, Mendez & Bowden, "Improving 3D Pose Estimation for Sign Language" (2023) [older]:** lifts 2D keypoints to 3D by predicting joint rotations and bone lengths, then applies forward kinematics. It is significantly more accurate than MediaPipe in per-joint error and runs at 100–200 ms per image on CPU — [arXiv 2308.09525](https://arxiv.org/abs/2308.09525v1); [DeepAI](https://www.deepai.org/publication/improving-3d-pose-estimation-for-sign-language)
- **M3T (BMVC 2026, arXiv 2603.23617):** argues that SMPL-X fits lack facial detail. It proposes **SMPL-FX** (SMPL-X plus the FLAME expression space), tokenised with per-modality FSQ-VAEs (face codebook use rises from 78.8% to 99.0%), and reaches 58.3% versus 49.0% on NMFs-CSL — [arXiv 2603.23617](https://arxiv.org/abs/2603.23617)
- **PHOSA / MVSign (arXiv Sep 2026; Hugging Face card says ECCV 2026):** a multi-view Chinese SL dataset built with Deaf experts. A hybrid fitting pipeline gives SMPL-X body, hand and face parameters and also works on monocular video. Motion-aware sampling handles motion blur — [arXiv 2609.29292](https://arxiv.org/abs/2609.29292); [HF dataset](https://huggingface.co/datasets/naaaaapi/MVSign)
- **MySign (NeurIPS 2026):** a Malaysian SL **mocap** dataset with 5,000 3D samples, 1,000 glosses and 5 Deaf signers. It provides ground-truth SMPL-X sequences, motivated by the depth ambiguity and finger-articulation errors of video-regressed SMPL-X — [NeurIPS 2026 poster](https://neurips.cc/virtual/2026/poster/139615)
- Also found but not examined in detail: Signs as Tokens (ICCV 2025, multilingual SL generator), SignAvatar (arXiv 2405.07974, 2024) and BOBSL3DT (hand-motion text dataset, 2025) — [arXiv 2411.17799](https://arxiv.org/pdf/2411.17799); [arXiv 2405.07974](https://arxiv.org/html/2405.07974v1); [arXiv 2508.15902](https://arxiv.org/pdf/2508.15902v1)

### Inferences
- The SL research consensus representation is SMPL-X; the reference pipeline is a general whole-body regressor, then SL-prior optimisation on 2D keypoints. For a webcam product, a feed-forward regressor (SMPLer-X or OSX for the body, HaMeR or WiLoR for the hands) without the slow optimisation stage is the realistic subset. That will produce roughly OSX-level errors (about 47 mm upper body, about 18 mm hands on the SGNify benchmark), not DexAvatar-level.
- 2D detector quality on hands is the bottleneck everyone names. Investing in a strong hand model (HaMeR-family) likely matters more than the body model.

### Gaps
- No runtime or FPS figures were reported for SGNify, SignAvatars or DexAvatar fitting.
- I could not read PHOSA's full PDF (compressed); its fitting details and accuracy numbers are unverified.
- M3T's abstract does not say how its SMPL-FX fits are obtained from video.

## 2. Which 3D representation SL recognition and assessment systems use in practice, and why

### Takeaway
In practice, recognition, translation evaluation and learner-feedback systems overwhelmingly use **MediaPipe Holistic** landmarks, usually **2D or normalised**, because they are cheap, real-time and easy to use. SMPL-X is recognised as more expressive but is rarely used downstream because it is hard to extract. MediaPipe's z/depth channel is considered unreliable for hands.

### Cited Findings
- WMT 2025 "Meaningful Pose-Based Sign Language Evaluation" (Jiang, Moryossef et al.) calls MediaPipe Holistic the most-used choice in SL processing. Its main experiments use 2D MediaPipe poses, and it acknowledges that 3D SMPL-X "would be a visually more expressive choice" but has no equally easy common extraction method — [arXiv 2510.07453](https://arxiv.org/html/2510.07453)
- The same paper's SkeletonVAE metric first **lifts 2D MediaPipe poses to constrained 3D skeletons**. Its keypoint subsets range from all 586 points down to YouTube-ASL (85) and SignCLIP (203); **hands-only** keypoints gave the best sign retrieval — [arXiv 2510.07453](https://arxiv.org/html/2510.07453)
- A low-resource SLR study found that **adding MediaPipe depth predictions made performance worse**, plausibly because depth is poor for some signers. MediaPipe's hand keypoints were the most accurate of the estimators tested, thanks to its dedicated hand model — [arXiv 2306.17558](https://arxiv.org/pdf/2306.17558)
- A LIBRAS isolated-sign study deliberately works in 2D and discards MediaPipe depth — [arXiv 2510.24887](https://arxiv.org/html/2510.24887v3)
- OpenHands (2021) [older] made pose-based (2D keypoint) pretrained SLR models the accessible baseline across languages — [arXiv 2110.05877](https://arxiv.org/pdf/2110.05877)
- Learner-feedback systems:
  - **SIGNU** (Mexican SL, CDSR 2026) uses MediaPipe 3D hand landmarks, Procrustes alignment (removing scale, position and tilt) and a "ghost sign" overlay. Its authors note that purely geometric comparison is less robust to natural hand-shape differences — [CDSR 2026](https://www.avestia.com/CDSR2026_Proceedings/files/paper/CDSR_141.pdf)
  - An MDPI *Technologies* 2025 study uses 48 MediaPipe hand and face keypoints, normalisation, and DTW against reference trajectories, with a threshold for correct/incorrect — [MDPI](https://www.mdpi.com/2227-7080/13/12/540)
  - A two-stage scoring paper reconstructs **3D hand features** from monocular video, then smooths, embeds and aligns them. It notes most teaching systems give only right/wrong or a regressed score, with no feedback — [arXiv 2404.10383](https://arxiv.org/html/2404.10383v1)
  - QuickSign (ASL learning app) uses MediaPipe and splits feedback into handshape, location, orientation and movement — [DEV](https://dev.to/quicksign/building-an-asl-learning-app-that-uses-computer-vision-to-evaluate-your-signs-in-real-time-4j8m)

### Inferences
- A pragmatic SignSure baseline is MediaPipe Holistic (or Hands plus Pose world landmarks) with Procrustes or shoulder normalisation and angle features. Upgrade the **hands** to a 3D hand mesh model if depth or handshape errors show up in testing.
- Splitting feedback by phonological parameter (handshape, location, orientation, movement) is an established product pattern that maps naturally onto per-joint-group comparison.

### Gaps
- I found no study directly comparing MediaPipe 3D, lifted 3D and SMPL-X for learner assessment accuracy.

## 3. Signing-specific problems (hand-face contact, hands in front of torso, self-occlusion, fast motion, hand depth) and how papers address them

### Takeaway
The named problems are depth ambiguity, hand-hand and hand-body/face contact, self-occlusion, motion blur and implausible finger poses. Papers address them with:
- biomechanical joint and bone limits
- SL-specific learned pose priors
- linguistic priors (symmetry, static handshape)
- temporal smoothness
- interpenetration or intersection losses
- a one-handed versus two-handed decision
- fused or multiple detectors
- hand-specific detectors or crops

None solves contact well from monocular video.

### Cited Findings
- **Depth ambiguity:** different signs can look identical in 2D, which motivates 3D annotation — [SignAvatars](https://arxiv.org/html/2310.20436). Video-regressed SMPL-X suffers from depth ambiguity and finger-articulation errors, which is why MySign captures mocap instead — [MySign NeurIPS 2026](https://neurips.cc/virtual/2026/poster/139615)
- **Occlusion and motion blur:** SGNify's symmetry and invariance priors target these — [SGNify](https://openaccess.thecvf.com/content/CVPR2023/papers/Forte_Reconstructing_Signing_Avatars_From_Video_Using_Linguistic_Priors_CVPR_2023_paper.pdf). SignAvatars fuses OSX, ACR and PARE for occlusion and truncation — [SignAvatars](https://arxiv.org/html/2310.20436). PHOSA uses motion-aware sampling against blur — [arXiv 2609.29292](https://arxiv.org/abs/2609.29292)
- **Fast motion:** SignAvatars handles it only indirectly, through temporal smoothing — [SignAvatars](https://arxiv.org/html/2310.20436)
- **Contact and interpenetration:** DexAvatar says existing methods do not enforce realistic hand-hand or hand-body contact; it adds a self-collision penalty and temporal terms — [DexAvatar](https://arxiv.org/html/2512.21054v1). Ivashechkin's occupancy-based intersection loss reduces hand intersections — [Surrey](https://www.surrey.ac.uk/events/20251216-improving-3d-human-pose-estimation-and-rendering-sign-language). BioTUCH uses a wrist bioimpedance sensor for touch timing — [Forte thesis](https://is.mpg.de/publications/forte25-phd-language)
- **Hand-face contact:** SignAvatars does not address it specifically — [SignAvatars](https://arxiv.org/html/2310.20436)
- **Implausible poses:** biomechanical limits on 15 hand joints plus a signing-space body filter improve the priors, and an unfiltered body prior gives 34.06 mm versus 30.28 mm filtered — [DexAvatar](https://arxiv.org/html/2512.21054v1)
- **Non-manuals:** SMPL-X face dimensions are too low for mouthings and eyebrows, which motivates SMPL-FX — [M3T](https://arxiv.org/abs/2603.23617)
- **General-domain models:** models trained on walking-type motion generalise poorly to signing — [Surrey](https://www.surrey.ac.uk/events/20251216-improving-3d-human-pose-estimation-and-rendering-sign-language)

### Inferences
- For assessment, the **location** parameter (for example, a hand at the chin versus the chest) is where monocular depth errors hurt most. Measuring hand-to-face and hand-to-body distances in the 2D image plane, normalised by shoulder width, may be more robust than trusting z.
- Anti-penetration and joint-limit clamps are cheap to add after any per-frame estimator.

### Gaps
- I found no quantitative evaluation specifically of hand-face contact accuracy.

## 4. Comparing a user's 3D pose to a reference animation or skeleton (retargeting, normalisation, joint angles versus positions, DTW)

### Takeaway
SL evaluation work favours **DTW over normalised keypoints**, with shoulder-centred and shoulder-width-scaled coordinates, often **hands-only**, and explicit handling of missing keypoints. Learner systems add Procrustes alignment or joint-angle features for invariance. No SL paper compares learner poses against a Mixamo rig directly. The proven route to different skeletons is SMPL-X as the shared intermediate, with retargeting done in Blender.

### Cited Findings
- **pose-evaluation toolkit (WMT 2025):**
  - Normalisation: shoulder midpoint as origin, shoulder width = 1. Signing-inactive frames are trimmed and low-confidence joints masked — [arXiv 2510.07453](https://arxiv.org/html/2510.07453)
  - DTW-based metrics beat padding-based ones. The best keypoint metrics were DTWpp (trim, mask fill 10.0, hands-only, no normalisation; 53% mAP) and nDTWpp (normalised, fill 1.0, hands-only; 55% mAP), against 27% for the Ham2Pose nDTW baseline. Embedding-based SignCLIP fine-tuned in-domain reached 91% — [arXiv 2510.07453](https://arxiv.org/html/2510.07453)
  - Code: [github.com/sign-language-processing/pose-evaluation](https://github.com/sign-language-processing/pose-evaluation)
- **Learner-feedback examples:**
  - Procrustes alignment for hand comparison — [SIGNU](https://www.avestia.com/CDSR2026_Proceedings/files/paper/CDSR_141.pdf)
  - DTW with a threshold on normalised MediaPipe keypoints — [MDPI 2025](https://www.mdpi.com/2227-7080/13/12/540)
  - DTW over joint-connection **angles**, which are invariant to orientation and scale — [GitHub mammhoud](https://github.com/mammhoud/Sign-Language-Recognition--MediaPipe-DTW)
  - Earlier work combining joint angles with DTW is cited by the two-stage scoring paper — [arXiv 2404.10383](https://arxiv.org/html/2404.10383v1)
- **Retargeting precedent in SL:** DexAvatar retargeted Vicon and Manus glove mocap to SMPL-X in Blender. Finger-length and knuckle discrepancies remained, and wrist rotations could not be transferred — [DexAvatar](https://arxiv.org/html/2512.21054v1). This is a concrete warning about mapping between rigs with different hand proportions.

### Inferences
- For SignSure, the most robust approach is to **compare in a skeleton-agnostic space**: per-bone direction vectors or joint angles (elbow flexion, wrist orientation, finger flexion) computed from both the learner's estimate and the Mixamo reference, rather than retargeting animation between rigs. Alternatively, sample the Mixamo FBX's global joint positions for a matched subset (shoulders, elbows, wrists, finger joints), normalise both with shoulder-centred, shoulder-width scaling, and run DTW.
- Joint angles avoid bone-length and proportion differences between learner and avatar. Positions capture **location** (hand near face), which angles alone can miss, so a combination of both per phonological parameter is sensible.
- Mixamo hands have finger bones in a similar hierarchy to MediaPipe's 21 points (MCP, PIP, DIP, tip) but no explicit fingertip joint in some rigs. Map carefully. This is inference, not verified from a source.

### Gaps
- I found no SL paper that evaluates retargeting to or from Mixamo rigs specifically, or compares angle-based versus position-based learner scoring head to head.

## 5. Tools that export 3D pose to FBX/BVH or drive Mixamo rigs from video

### Takeaway
No SL-specific end-to-end tool exists. The pieces are:
- MediaPipe-to-BVH or rig solvers (Mocapy, Kalidokit)
- the official SMPL-X Blender add-on (SMPL-X animation .npz to FBX)
- Blender retargeting add-ons that accept SMPL/SMPL-X (MoveNow, BVH Retargeter, Auto-Rig Pro, Rokoko)

These are community tools whose status and licences I did not verify.

### Cited Findings
- **Mocapy:** runs MediaPipe pose, hands and face, solves bone rotations and writes BVH, with a rest-pose first frame. The step from BVH to a Mixamo FBX goes through Blender — [GitHub Mocapy](https://github.com/justinjohn0306/Mocapy)
- **Kalidokit:** a MediaPipe-based kinematics and blendshape solver, pointed to on three.js forums for animating Mixamo characters from MediaPipe landmarks — [three.js forum](https://discourse.threejs.org/t/how-can-i-animate-a-character-arm-hand-rig-from-recorded-mediapipe-landmark-data/92216)
- **Official SMPL-X Blender add-on (MPI-IS):** imports AMASS or SMPL-X .npz animation. Its exported FBX imports into Unity and Unreal without extra rotation or scaling. Downloading the model requires free registration — [MPI GitLab](https://gitlab.tuebingen.mpg.de/jtesch/smplx_blender_addon/-/commit/4f5d7a52a14e79d6a10af51e7f58b4c559fa7672)
- **MoveNow (Blender add-on):** its listing says it supports AI-generated SMPL/SMPL-X data, Mixamo, Rokoko and EasyMocap, but not fully custom non-standard hierarchies (unverified product claim) — [Product Hunt](https://www.producthunt.com/products/movenow-add-on-for-blender)
- **BVH Retargeter (formerly MakeWalk):** a Blender add-on for retargeting BVH data — [BlenderArtists](https://blenderartists.org/t/bvh-retargeter-the-add-on-formerly-known-as-makewalk/1216579)
- **Mixamo-side Blender tooling:** Adobe's official Mixamo add-on is unsupported and breaks on Blender 4.x (bone layers were replaced by bone collections), so community replacements exist; Mixaify (Mixamo to Rigify) is Blender 5+ only — [Cinevva guide](https://app.cinevva.com/guides/mixamo-to-blender-2026); [mixaify](https://github.com/netherby/mixaify-retarget)
- **prompt2rig:** browser MediaPipe Pose retargeting for Mixamo characters, with a GVHMR higher-quality pass (low-reliability listing) — [everydev](https://www.everydev.ai/tools/prompt2rig/llms.txt)

### Inferences
- For SignSure, the direction that matters is probably the reverse: **extract joint transforms from the Mixamo FBX** (for example with Blender Python, three.js FBXLoader or Assimp, sampling world positions and rotations per frame) and compare them against the learner's estimate in a shared joint subset. That avoids retargeting the learner's motion onto the rig at all. Retargeting tools are mainly useful for visualising the learner's attempt on the same avatar (a "ghost" overlay).

### Gaps
- I did not verify the maintenance status, licence or hand (finger) support of Mocapy, Kalidokit, MoveNow or prompt2rig.
- I found no tool that retargets MediaPipe **hand** landmarks to Mixamo finger bones with documented accuracy.
