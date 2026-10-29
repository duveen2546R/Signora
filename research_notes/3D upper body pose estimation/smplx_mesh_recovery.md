# Parametric 3D Body-Mesh Recovery (SMPL / SMPL-X / MANO) for Upper Body + Hands, as of Oct 2026

Scope note: these notes are for a sign-language analysis project that needs anatomically consistent 3D shoulders, elbows, wrists, fingers and joint rotations, for example to compute elbow flexion. Fetched sources were limited, so some well-known methods (ExPose, PIXIE, WHAM, TRAM, 4DHumans/PHALP, CameraHMR, NLF) appear only through comparison tables or not at all. Those are flagged under Gaps.

## Whole-body SMPL-X regressors: which handle hands well, benchmarks, typical errors

### Takeaway
SMPLest-X (Jan 2025, extends SMPLer-X) is the strongest openly benchmarked one-stage SMPL-X regressor in the sources found. Its whole-body PVE on EHF/UBody is about 40–50 mm and its hand PVE is about 23–37 mm, well ahead of OSX, Hand4Whole and PyMAF-X; AiOS and Multi-HMR come next. Meta's SAM 3D Body (Nov 2025, CVPR 2026) is the newest strong full-body-plus-hands option, but it outputs its own MHR rig, not SMPL-X. Every whole-body regressor is still clearly worse on hands than dedicated hand models, because hands are small in a full-body crop.

### Cited Findings
**SMPLer-X (NeurIPS 2023; older generation)**
- Five variants, all trained on 32 datasets (4.5M instances). Each line gives parameters, MPE (mean primary error across AGORA, EgoBody, UBody, 3DPW and EHF) and V100 speed at batch size 1 — [SMPLer-X GitHub](https://github.com/caizhongang/SMPLer-X)
  - S32: 32M, MPE 82.6, 36.2 FPS
  - B32: 103M, 74.3, 33.1 FPS
  - L32: 327M, 66.2, 24.4 FPS
  - H32: 662M, 63.0, 17.5 FPS
  - H32*: 59.7 MPE at the same FPS; the README says it "fixes the camera estimation issue on 3DPW-like data"
- Install stack is old: Python 3.8, PyTorch 1.12.0, CUDA 11.3, mmcv-full 1.7.1, plus an editable mmpose. A docker image (H32) was tested on an RTX 3090 under WSL2 — [SMPLer-X GitHub](https://github.com/caizhongang/SMPLer-X)

**SMPLest-X (arXiv 2501.09782, Jan 2025)**
- Extends SMPLer-X with data scaling to 40 datasets and up to 10M instances, and model scaling up to ViT-Huge. The architecture is stripped to encoder, decoder and regression heads, with "a special edge on hand estimation in a one-stage manner". It also introduces the SynHand close-up hand benchmark — [arXiv 2501.09782](https://arxiv.org/html/2501.09782v1)
- SMPLest-X-H40 results, given as PA-PVE (all / hands / face) then PVE (all / hands / face), in mm — [arXiv 2501.09782](https://arxiv.org/html/2501.09782v1)
  - EHF: 34.7 / 11.4 / 3.4, then 49.7 / 36.4 / 16.2. Finetuned: PVE 40.9 / 33.3 / 20.2
  - UBody (upper-body, includes sign-language-like video): 27.8 / 7.9 / 2.5, then 51.1 / 32.9 / 21.4
  - ARCTIC: 24.2 / 10.9 / 3.3, then 40.3 / 24.1 / 28.0
  - SynHand: 21.7 / 9.8 / 2.1, then 34.4 / 23.7 / 15.4
  - AGORA-val: 39.2 / 7.3 / 2.7, then 56.1 / 36.9 / 26.5
  - AGORA test (finetuned): MVE all 86.6, body 57.4, left hand 30.8, right hand 31.5
- Competitors' whole-body PVE from the same paper's tables (mm) — [arXiv 2501.09782](https://arxiv.org/html/2501.09782v1)
  - OSX: EHF 70.8, UBody 92.4, SynHand 107.0
  - Hand4Whole: EHF 76.8, UBody 104.1, SynHand 116.3
  - PyMAF-X: EHF 64.9, UBody 146.7, SynHand 112.6
  - AiOS: EHF 45.4, UBody 58.6, SynHand 94.1, AGORA-val 63.4
  - Multi-HMR: SynHand 70.3
  - PIXIE: UBody 168.4
  - HybrIK-X: UBody 201.6, SynHand 96.5
  - Some numbers come from different training regimes, which the paper notes.
- Hand-focused summary, given as MPE / hand-MPE / hand-PA-MPE in mm — [arXiv 2501.09782](https://arxiv.org/html/2501.09782v1)
  - SMPLest-X-H40: 58.9 / 31.6 / 9.3
  - AiOS: 70.6 / 41.9 / 11.4
  - OSX: 111.6 / 55.8 / 14.0
  - Hand4Whole: 115.6 / 51.4 / 11.4
- Size and training cost: SMPLest-X-H has 687M parameters. Input is a 512×384 crop. Training used 16 V100s, with SMPLest-X-H40+ taking over 2,600 GPU-hours. The paper reports no FPS (by extrapolation from SMPLer-X-H at 662M, expect roughly 15–20 FPS on a V100; this is an inference, not a reported number) — [arXiv 2501.09782](https://arxiv.org/html/2501.09782v1)
- Code: github.com/wqyin/SMPLest-X — [arXiv 2501.09782](https://arxiv.org/html/2501.09782v1)

**Multi-HMR (NAVER LABS Europe, ECCV 2024)**
- A single-shot, multi-person detector-plus-regressor. It outputs SMPL-X (body, hands, face) with 3D location in camera coordinates — [arXiv 2402.14654](https://arxiv.org/abs/2402.14654v2)
- The authors note that regressing SMPL-X from one token "tends to perform low on small body parts such as hands". They added the synthetic CUFFS dataset (close-up full-body, clearly visible hands), which improved hand predictions. ViT-S at 448×448 is described as real-time — [arXiv 2402.14654](https://arxiv.org/abs/2402.14654v2); [search summary](https://europe.naverlabs.com/research/publications/multi-hmr-multi-person-whole-body-human-mesh-recovery-in-a-single-shot/)

**SAM 3D Body (Meta, arXiv 2602.15989, CVPR 2026)**
- A promptable, single-image full-body HMR model covering body, feet and hands. It is an encoder-decoder that accepts 2D keypoint and mask prompts — [arXiv 2602.15989](https://arxiv.org/abs/2602.15989v1)
- It outputs the Momentum Human Rig (MHR), a new parametric mesh that separates skeleton from surface shape. The repo does not mention conversion to SMPL or SMPL-X — [SAM 3D Body GitHub](https://github.com/facebookresearch/sam-3d-body)
- It has an optional hand decoder for hand refinement. Checkpoints were released 2025-11-19 in two backbones, DINOv3-H+ (840M) and ViT-H (631M). Both are gated on Hugging Face. The license is the "SAM License" — [SAM 3D Body GitHub](https://github.com/facebookresearch/sam-3d-body)
- Benchmarks (DINOv3-H+ / ViT-H) — [SAM 3D Body GitHub](https://github.com/facebookresearch/sam-3d-body)
  - 3DPW MPJPE: 54.8 / 54.8
  - EMDB MPJPE: 61.7 / 62.9
  - RICH PVE: 60.3 / 61.7
  - FreiHAND PA-MPJPE: 5.5 / 5.5 (on par with the specialist WiLoR)
- The default detector is ViTDet with MoGe2 for field of view; SAM3 can be used as the detector instead — [SAM 3D Body GitHub](https://github.com/facebookresearch/sam-3d-body)
- Native ComfyUI integration with GLB and BVH export arrived 2026-08-23 — [ComfyUI wiki](https://comfyui-wiki.com/en/news/2026-08-23-sam-3d-body-native-comfyui) (secondary source)
- A third-party write-up describes a shared encoder with separate body and hand decoders, meant to reduce conflicts between body and finger supervision — [mer.vin blog](https://mer.vin/2026/06/sam-3d-body-promptable-full-body-3d-mesh-from-one-image-cvpr-2026-mhr/) (secondary, unverified)

**PromptHMR (2025)**
- A promptable HPS method that takes spatial or semantic prompts. Its video version adds temporal transformer layers at SMPL-X decoding for smooth motion — [search summary of arXiv 2504.06397](https://arxiv.org/pdf/2504.06397v2.pdf) (hand-specific accuracy not verified)

**Per-frame jitter**
- Image-based whole-body models such as SMPLer-X "process frames independently and struggle with small hand crops", which makes hand motion inaccurate and jittery — [DanceHMR, arXiv 2605.18102](https://arxiv.org/abs/2605.18102v3)

### Inferences
- For sign language, UBody and SynHand are the most relevant benchmarks: UBody is upper-body video, SynHand is close-up hands. On both, SMPLest-X leads among the SMPL-X regressors measured in its own paper. Hand PVE of about 24–33 mm (non-aligned) means finger configurations are roughly right, but fine handshape distinctions are unreliable without a dedicated hand model.
- Hand PA-PVE (about 8–11 mm) is much better than non-aligned hand PVE (about 24–37 mm). Hand *shape and articulation* is decent; the large error is in the hand's global position and orientation, which is exactly the wrist rotation that matters for sign language.
- SAM 3D Body's FreiHAND score suggests hand quality close to WiLoR inside a full-body model. However, MHR output means joint definitions differ from SMPL-X, and you would need your own retargeting or conversion.
- OSX, Hand4Whole, PyMAF-X, PIXIE and ExPose (2020–2023) are superseded on every shared benchmark. Treat them as legacy baselines.

### Gaps
- ExPose results did not appear in the fetched tables.
- No fetched source gives FPS for SMPLest-X, AiOS, Multi-HMR or SAM 3D Body.
- Licenses were not verified for SMPLest-X/SMPLer-X (a LICENSE file exists but its terms were not shown), Multi-HMR or AiOS. The exact terms of the "SAM License" for SAM 3D Body were not read.
- No source was found for CameraHMR (body-only SMPL, 2024) or NLF (Neural Localizer Fields) regarding hands or SMPL-X support.
- No direct EHF or ARCTIC head-to-head between SAM 3D Body and SMPLest-X was found.

## Hand-specific mesh models (HaMeR, WiLoR) and combining them with a body model

### Takeaway
WiLoR (CVPR 2025) beats HaMeR (CVPR 2024) on accuracy and is about 3× smoother frame to frame, and it ships a very fast hand detector. HaMeR is MIT-licensed code, while WiLoR is CC-BY-NC-ND. Both output MANO and need the MANO model, which is research-only. Combining them with a body model is a separate step, often done by pasting MANO parameters onto SMPL-X wrists, and it is known to cause wrist inconsistencies.

### Cited Findings
- FreiHAND, given as PA-MPJPE / PA-MPVPE / F@5 / F@15 — [WiLoR paper, arXiv 2409.12259](https://arxiv.org/html/2409.12259v1)
  - WiLoR: 5.5 / 5.1 mm / 0.825 / 0.993
  - HaMeR: 6.0 / 5.7 mm / 0.785 / 0.990
- HO3D v2 PA-MPJPE: WiLoR 7.5 mm vs HaMeR 7.7 mm — [WiLoR paper](https://arxiv.org/html/2409.12259v1)
- Temporal stability on HO3D, with no temporal module — [WiLoR paper](https://arxiv.org/html/2409.12259v1)
  - Jitter: WiLoR 5.92 vs HaMeR 20.43
  - MPFJE: WiLoR 0.762 vs HaMeR 1.768
- WiLoR's detector runs at 138 FPS (medium, 25 MB) and 175 FPS (small, 7 MB) on an RTX 4090. The paper gives no FPS for the full pipeline, and its own FPS claims are inconsistent (over 100, over 110, over 130) — [WiLoR paper](https://arxiv.org/html/2409.12259v1)
- WiLoR was trained on about 4.2M images, including the new WHIM dataset (over 2M in-the-wild hand images from more than 1,500 YouTube videos) — [WiLoR paper](https://arxiv.org/html/2409.12259v1)
- WiLoR repo — [WiLoR GitHub](https://github.com/rolpotamias/WiLoR)
  - License: models are CC-BY-NC-ND; the repo also depends on Ultralytics (AGPL) and MANO
  - Install: PyTorch 2.0 with CUDA 11.7, conda with Python 3.10; `--fast` (fp16) gives up to 1.6× speedup
  - A lightweight `WiLoR-mini` pip package exists
- HaMeR repo — [HaMeR GitHub](https://github.com/geopavlakos/hamer)
  - Code is MIT-licensed; it uses ViTPose and Detectron2 for detection and needs `MANO_RIGHT.pkl`
  - Install: Python 3.10 with CUDA 11.7 wheels; docker-compose is available
  - Combining with a body model is not covered by the authors; a community project, Mano2Smpl-X, integrates HaMeR hand parameters into SMPL-X
- Stitching independently estimated hands (e.g. "GVHMR + HaMeR") onto a video body sequence produces "unnatural wrist orientations and temporal inconsistencies" — [DanceHMR, arXiv 2605.18102](https://arxiv.org/pdf/2605.18102)
- Part-specific hand methods generally perform more accurately on hands than full-body methods — [SAM 3D Body paper via search](https://arxiv.org/pdf/2602.15989)

### Inferences
- A practical sign-language pipeline: run a body or whole-body model (SMPLest-X or GVHMR) for shoulders and elbows, run WiLoR for the fingers, then copy MANO finger poses into the SMPL-X hand joints. Resolve wrist orientation by blending, or by short SMPLify-style refinement against 2D wrist and hand keypoints.
- WiLoR's low jitter without a temporal module makes it attractive for per-frame handshape features.
- If commercial use is planned, HaMeR's MIT code is more permissive than WiLoR's NC-ND. Both are still bound by MANO's research-only license.

### Gaps
- No source gives FPS for HaMeR or WiLoR end to end (detector plus ViT-H reconstruction).
- No quantitative evaluation of Mano2Smpl-X wrist-merge accuracy was found.
- HaWoR (world-space hand motion) is cited by DanceHMR, but its details were not fetched.

## Video and temporal methods (WHAM, TRAM, GVHMR, 4DHumans/PHALP, DanceHMR): smoothness, world coordinates, hands

### Takeaway
GVHMR outputs SMPL/SMPL-X in both camera and world frames. Like most video HMR methods, it is body-focused, so detailed hand articulation comes from bolting on HaMeR or WiLoR. DanceHMR (2026) is the first found method that targets temporally coherent body and hands jointly in monocular video, but code availability is unconfirmed.

### Cited Findings
- GVHMR takes a video and returns SMPL/SMPL-X motion in the camera frame and the world frame. Weights are non-commercial research only, and SMPL/SMPL-X are under their own MPI licenses — [GVHMR PyPI](https://pypi.org/project/gvhmr/); [GVHMR HF](https://huggingface.co/ryanrudes/gvhmr)
- Existing video HMR "produce coherent body motion but often ignore detailed hand articulation". DanceHMR proposes residual body-hand fusion in one temporal architecture plus close-up-aware augmentation for upper-body-only framing (directly relevant to signer framing), and reports improved hand reconstruction with competitive body accuracy — [DanceHMR abstract](https://arxiv.org/abs/2605.18102v3)
- DanceHMR cites GVHMR, WHAM, HaMeR, WiLoR, SMPLest-X, PromptHMR, HaWoR, Human3R, GENMO and DUOMO as related or baseline methods — [DanceHMR PDF](https://arxiv.org/pdf/2605.18102)
- The PromptHMR video version adds temporal transformer layers at SMPL-X decoding for temporally stable output — [search summary](https://arxiv.org/pdf/2504.06397v2.pdf)
- SAM 3D Body has "full-body mesh tracking" in ComfyUI — [ComfyUI wiki](https://comfyui-wiki.com/en/news/2026-08-23-sam-3d-body-native-comfyui) (secondary)

### Inferences
- For a fixed-camera signer, world-grounding (WHAM, TRAM, GVHMR) is less important than smooth local joint rotations. A temporal model's main value here is jitter reduction on the elbow and wrist.
- If DanceHMR's code is released, it is the most directly relevant method found, because it handles close-up upper-body framing.

### Gaps
- WHAM, TRAM and 4DHumans/PHALP pages were not fetched. Their known characteristics (WHAM and TRAM output SMPL body without articulated hands; 4DHumans is HMR2.0 SMPL plus PHALP tracking) come from background knowledge, not cited sources here.
- DanceHMR's numerical results and code release status are unverified (project page: shenwenhao01.github.io/dancehmr).

## Optimisation-based fitting (SMPLify-X; fitting SMPL-X to DWPose or OpenPose 2D keypoints)

### Takeaway
SMPLify-X fits SMPL-X to whole-body 2D keypoints with a 5-stage L-BFGS optimisation. It is slow (about 12–100 s per image with the official code) and temporally unstable frame to frame. In modern pipelines it is used as a short refinement on top of a regressor's initialisation, not from scratch.

### Cited Findings
- Using the official code on a Tesla P40, SMPLify-X takes 82.72 s per image, mostly from its 5-stage optimisation. The same paper's table lists 12 s, which is an internal inconsistency — [arXiv 2010.14036](https://arxiv.org/pdf/2010.14036)
- FrankMocap lists SMPLify-X at 0.01 FPS and notes optimisation methods "suffer from temporal instability" due to the multi-stage procedure — [FrankMocap, arXiv 2008.08324](https://arxiv.org/pdf/2008.08324)
- SMPLify-X fits camera and SMPL-X parameters to OpenPose body, hand, face and feet keypoints using L-BFGS — [SMPLify-X paper](https://arxiv.org/pdf/1904.05866)

### Inferences
- Pros: fitting is fully explicit, enforces 2D reprojection consistency, works with any 2D detector (DWPose/RTMW give 133 whole-body keypoints), and can add custom priors such as joint limits and temporal smoothness.
- Cons: depth ambiguity remains (the elbow can flip toward or away from the camera), runs are slow, and outputs depend on initialisation.
- A good hybrid is to initialise from SMPLest-X or SAM 3D Body plus WiLoR, then run a few iterations against DWPose 2D keypoints with a temporal smoothness term.

### Gaps
- No benchmark of GPU-batched SMPL-X fitting speeds was found (e.g. EasyMocap or the smplx-based fitters).
- No accuracy figures were found for DWPose-driven SMPLify-X fitting.

## Joint-angle extraction reliability (elbow flexion, shoulder angles)

### Takeaway
No source was found that validates SMPL or SMPL-X-derived elbow flexion against a goniometer or motion capture. The nearest evidence (monocular 2D or BlazePose estimators) shows elbow flexion is the *weakest* upper-limb angle: underestimated at large flexion and sensitive to camera orientation. Treat mesh-derived elbow angles as needing your own validation.

### Cited Findings
- BlazePose (monocular 3D) vs optical markers: errors were non-constant, large elbow flexion angles were underestimated, and accuracy depended significantly on the participant's orientation to the camera — [ETH Research Collection, ICORR 2025](https://www.research-collection.ethz.ch/items/62b944dd-2f46-401c-acdc-b9d98ee4d441)
- In five 2D HPE models vs a universal goniometer (n=52), shoulder flexion and abduction performed better, while elbow flexion was "unsatisfactory". RMSE was under 10° in 8 of 10 movements — [Sensors 2024, PMC11679233](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC11679233/)
- The goniometer reference itself carries about 7° error per 8 mm arm shift — [Folia Morphologica](https://journals.viamedica.pl/folia_morphologica/article/download/16301/12938)

### Inferences
- SMPL-X elbow flexion should be computed from the angle between the 3D shoulder–elbow and elbow–wrist joint vectors, or from the elbow joint's axis-angle magnitude. The elbow in SMPL-X is a 3-DoF ball joint, so the rotation can contain anatomically implausible twist; vector-based angles are more robust.
- Typical whole-body MPJPE of about 50–60 mm means a few-cm forearm-direction error, which can produce errors of 10° or more when the forearm points toward the camera.
- The parametric prior enforces constant bone lengths and plausible poses, an advantage over raw 3D keypoint lifters for consistency.

### Gaps
- No peer-reviewed validation of SMPL-X, SMPLest-X, SAM 3D Body or GVHMR elbow or shoulder angles against goniometry or mocap was found.

## Licensing and commercial paths

### Takeaway
SMPL, SMPL-X and MANO model files are academic-research only. Commercial use requires a Meshcapade license (from about €2k/year for micro enterprises). Method weights add their own non-commercial terms: GVHMR is NC research, WiLoR is CC-BY-NC-ND, and SAM 3D Body uses the SAM License. HaMeR code is MIT.

### Cited Findings
- The SMPL-X license is for academic research. Commercial, military and surveillance use is prohibited, "including incorporation in a commercial product". Commercial licensing goes through Meshcapade — [SMPL-X model license](https://smpl-x.is.tue.mpg.de/modellicense.html)
- Meshcapade offers commercial, R&D and evaluation licenses: about €2,000/year (micro), €10,000/year (SME), enterprise on request. MANO may require a separate license — [Meshcapade Avatar Tech](https://meshcapade.com/assets/avatar-tech)
- Meshcapade is an MPI spin-off that licenses SMPL, SMPL-X, SMIL and SMPLify-X — [MPG press release](https://www.mpg.de/16840607/realistic-3d-models-for-fashion-film-and-healthcare)
- Method licenses
  - WiLoR: CC-BY-NC-ND, plus the Ultralytics and MANO licenses — [WiLoR GitHub](https://github.com/rolpotamias/WiLoR)
  - HaMeR: MIT — [HaMeR GitHub](https://github.com/geopavlakos/hamer)
  - GVHMR: non-commercial research — [GVHMR PyPI](https://pypi.org/project/gvhmr/)
  - SAM 3D Body: SAM License, gated HF checkpoints — [SAM 3D Body GitHub](https://github.com/facebookresearch/sam-3d-body)

### Inferences
- SAM 3D Body's MHR rig avoids SMPL-X licensing entirely. This is potentially a key advantage for a product, subject to the SAM License terms.

### Gaps
- The full SAM License text and MHR's license were not read.
- The licenses of SMPLest-X, Multi-HMR and AiOS were not verified.
- No MANO-specific commercial pricing was found.

## Install complexity and GPU requirements

### Takeaway
All the methods need an NVIDIA CUDA GPU in practice. A 24 GB card (RTX 3090/4090) is the common tested target. Older repos (SMPLer-X) pin PyTorch 1.12 with mmcv 1.7, which is painful to install on modern CUDA; newer repos (HaMeR, WiLoR) use PyTorch 2.x with CUDA 11.7. Apple Silicon (this project's Mac) is not a documented target for any of them.

### Cited Findings
- SMPLer-X: Python 3.8, PyTorch 1.12, CUDA 11.3, mmcv-full 1.7.1, mmpose. Speeds were measured on a V100; docker was tested on an RTX 3090 — [SMPLer-X GitHub](https://github.com/caizhongang/SMPLer-X)
- HaMeR: Python 3.10 with CUDA 11.7, a recursive clone including ViTPose; docker-compose is available — [HaMeR GitHub](https://github.com/geopavlakos/hamer)
- WiLoR: PyTorch 2.0 with CUDA 11.7, plus a pip-installable WiLoR-mini. Experiments ran on an RTX 4090 — [WiLoR GitHub](https://github.com/rolpotamias/WiLoR); [WiLoR paper](https://arxiv.org/html/2409.12259v1)
- SAM 3D Body: gated HF checkpoints of 631M–840M parameters, with ViTDet and MoGe2 dependencies — [SAM 3D Body GitHub](https://github.com/facebookresearch/sam-3d-body)
- SMPLest-X-H is 687M parameters — [arXiv 2501.09782](https://arxiv.org/html/2501.09782v1)

### Inferences
- On a Mac, plan for a cloud or Linux CUDA GPU for offline batch processing of sign videos. MPS support is unverified and likely blocked by detectron2/mmcv and custom CUDA ops.

### Gaps
- No minimum VRAM figures were stated for any repo.
