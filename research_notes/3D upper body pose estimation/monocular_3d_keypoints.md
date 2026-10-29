# Monocular 3D Keypoint Methods for Upper Body + Hands (as of Oct 2026)

Scope: methods that take one RGB camera and output 3D keypoints (not meshes), for a Python sign-language app that already uses DWPose / MediaPipe 2D. Mesh methods (SMPL-X etc.) are out of scope here.

## 1. MediaPipe Pose / Holistic world landmarks: how are they produced, how accurate is z, and where do they fail?

### Takeaway
MediaPipe's BlazePose GHUM 3D outputs 33 body landmarks twice: as image-normalised x/y plus a relative z, and as "world landmarks" in metres with the origin at the hip centre. The 3D training labels came from fitting the GHUM body model to 2D-annotated images plus human depth-order labels, not from motion capture. Google reports about 36 to 45 mm body 3D error and about 18 mm hand 3D error, but only on a narrow test set (yoga, single person 2-4 m away). Independent studies against optical mocap show joint-angle biases, especially at the elbow. Depth is the weakest axis.

### Cited Findings
- **Outputs.** Each Pose Landmarker bundle (Lite / Full / Heavy, float16) is a detector plus a landmarker. The landmarker outputs 33 3D landmarks, and the task returns both normalised `Landmarks` and `WorldLandmarks`. The detector input is 224x224 and the landmarker input is 256x256. — [MediaPipe Pose Landmarker docs](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker)
- **World landmarks.** `pose_world_landmarks` are "real-world 3D coordinates in meters" with the origin at the centre between the hips. Each landmark carries the same visibility value as the image landmarks. — [MediaPipe legacy pose.md](https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/pose.md)
- **Image-space z.** In `pose_landmarks`, z is depth with the origin at the hip midpoint, and smaller values mean closer to the camera. Its magnitude uses "roughly the same scale as x". x and y are normalised to [0, 1]. — [MediaPipe legacy pose.md](https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/pose.md)
- **Possible z-sign conflict.** The TF.js blog on BlazePose GHUM reportedly states z is positive when moving closer to the camera. That would contradict the MediaPipe docs ("smaller = closer"), possibly because of runtime differences. Verify the sign empirically before using it. — [TensorFlow blog, 3D pose detection with BlazePose GHUM](https://blog.tensorflow.org/2021/08/3d-pose-detection-with-mediapipe-blazepose-ghum-tfjs.html?hl=es_419), as quoted in a search summary (not fetched directly)
- **Architecture.** BlazePose is a MobileNetV2-like CNN aimed at on-device, real-time fitness applications. It uses GHUM, a 3D human shape model, to estimate full 3D body pose. — [MediaPipe Pose Landmarker docs](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker)
- **How the 3D labels were made.** The authors fitted the GHUM statistical body model to their existing 2D pose dataset, optimising against 2D keypoints and silhouettes. Annotators then labelled depth order between skeleton edges, which cut depth-ordering errors in the fits from 25% to 3%. — [BlazePose GHUM Holistic paper, arXiv 2206.11678](https://ar5iv.labs.arxiv.org/html/2206.11678)
- **Coordinate frame.** Body 3D is in "relative coordinates of a metric space with origin in the subject's hips center", so it is root-relative with no absolute camera distance. — [arXiv 2206.11678](https://ar5iv.labs.arxiv.org/html/2206.11678)
- **Body 3D accuracy (Google's own numbers).** Mean absolute error is 36 mm for Heavy, 39 mm for Full and 45 mm for Lite. These are measured on yoga images, single person at 2-4 m, 17 COCO keypoints only. — [arXiv 2206.11678, Table 1](https://ar5iv.labs.arxiv.org/html/2206.11678)
- **Hand 3D accuracy.** The holistic pipeline with high-resolution hand re-crops reaches 18 mm 3D mean absolute error. The tracking baseline is 20 mm, and without re-crops it is 27 mm. — [arXiv 2206.11678, Table 3](https://ar5iv.labs.arxiv.org/html/2206.11678)
- **2D quality (PCK@0.2 / mAP).** Heavy scores 96.4-97.5 PCK and 68-74 mAP. Lite scores 90-93.5 PCK and 45-54 mAP. These evaluations use 17 COCO keypoints only. — [MediaPipe legacy pose.md](https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/pose.md)
- **Speed.**
  - On a desktop (i9-10900K + GTX 1070): 7 ms Lite, 8 ms Full, 10 ms Heavy.
  - On a Pixel 4 single-core CPU: 25 / 40 / 147 ms.
  - The full holistic pipeline runs at about 15 FPS on most modern phones and browsers.
  - Source: [arXiv 2206.11678, Table 2](https://ar5iv.labs.arxiv.org/html/2206.11678)
- **Holistic paper limitations.** The paper itself notes these limits:
  - Depth stays ambiguous from a single image.
  - Evaluation is mainly yoga images with 17 keypoints.
  - Hands need a separate high-resolution re-crop stage.
  - Facial expressions are left as future work.
  - Source: [arXiv 2206.11678](https://ar5iv.labs.arxiv.org/html/2206.11678)
- **Hand Landmarker.** It outputs 21 hand-knuckle keypoints in image coordinates and in "world coordinates". It is trained on about 30K real images plus synthetic rendered hands. Latency on a Pixel 6 is 17.12 ms on CPU and 12.27 ms on GPU. The docs page does not state the world units or origin. — [MediaPipe Hand Landmarker docs](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker)
- **Legacy status.** As of 10 May 2023 the legacy Pose solution "was upgraded to a new MediaPipe Solution". The new Tasks API (Pose Landmarker) is the supported path. "Holistic landmark detection" still appears as a separate task in the docs navigation. — [MediaPipe legacy pose.md](https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/pose.md); [Pose Landmarker docs](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker)
- **License.** Docs content is CC BY 4.0 and code samples are Apache 2.0. The Pose Landmarker page does not state a separate license for the model bundles. — [MediaPipe Pose Landmarker docs](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker)
- **Independent validation against OptiTrack (smartphone, BlazePose).** Elbow angle showed a systematic bias of +18.9°. Shoulder abduction was the best joint, at 8.3° mean absolute error. The authors list occlusion and depth ambiguity as the main limits. — search-result summary of [Sensors / MDPI study](https://www.mdpi.com/1424-8220/23/1/3) (not fetched directly; treat the exact numbers as unverified)
- **Lafayette et al. (Sensors 2022).** MediaPipe's angle error fell within the range of short- and long-arm goniometers when compared with a reflective-marker system. — [PMC9824231](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9824231/) (search summary)
- **Wagh et al. (JMIR Formative Research 2024).** The authors state that MediaPipe's 3D accuracy for fine upper-limb movements "still needs validation". — [JMIR Formative 2024](https://formative.jmir.org/2024/1/e56682/PDF) (search summary)

### Inferences
- **The z value is learned, not measured.** World-landmark z is a learned prior from GHUM fits on in-the-wild 2D data. Expect plausible but smoothed depth that can be biased for unusual poses. Arms crossing in front of the torso, which is very common in signing, combine self-occlusion with depth ambiguity. The elbow bias in the OptiTrack study fits this pattern.
- **Body and hand world landmarks use different frames.** Body world landmarks are hip-centred. In Holistic, the hand world landmarks are a separate per-hand frame. To place fingers in the body frame you have to attach each hand to the pose wrist, for example by translating the hand so its wrist sits on the pose wrist. Scale consistency between the two is not guaranteed.
- **Accuracy figures do not transfer to signing.** Google's 36-45 mm body error comes from full-body yoga at 2-4 m. Seated or waist-up signing framing, with the hips out of view, is out of distribution. A hip-centred origin is poorly defined when the hips are not visible.

### Gaps
- **Hand world-landmark units and origin.** The current Hand Landmarker docs page did not state them. The legacy MediaPipe Hands docs, which I did not fetch, are commonly cited as metres with the origin at the hand's approximate geometric centre. Verify this.
- **No mocap validation of world-landmark depth.** I found no peer-reviewed study that measures MediaPipe world-landmark z error in mm per axis against mocap, especially for arms in front of the body.
- **Holistic Landmarker in Python.** I did not confirm whether the Tasks-API Holistic Landmarker is fully supported in the Python package as of 2026.
- **Model-bundle licenses.** I did not find explicit license terms or model cards for the model weights.

## 2. 2D-to-3D lifting models (VideoPose3D, MotionBERT, MotionAGFormer, PoseFormerV2, D3DP): can they take DWPose / COCO-WholeBody input, and do any lift hands or whole body?

### Takeaway
The mainstream body lifters all take 17 Human3.6M-format body joints, usually from a temporal window of 27-243 frames. They reach about 38-47 mm MPJPE on Human3.6M with detected 2D input. You can feed them DWPose body keypoints only after remapping the 17 COCO joints to the H36M layout. None of them lift hands or fingers. Whole-body (133-keypoint) lifting exists only around the H3WB benchmark, and the best published lifter there (Jointformer) has 125 mm pelvis-aligned hand error. That is far worse than the body.

### Cited Findings

**Human3.6M body lifters**

| Model | Human3.6M MPJPE (mm) | Window | License | Status / notes |
|---|---|---|---|---|
| VideoPose3D | 46.8 (P1), 36.5 P-MPJPE (P2), with CPN 2D | 243 frames | CC BY-NC | Archived Oct 31, 2023 |
| PoseFormerV2 | 45.2 (48.7 at 27 frames) | 243 frames | MIT | Last news Jun 2024 |
| MotionBERT | 39.2 scratch / 37.2 fine-tuned, on H36M-SH | up to 243 frames | Apache-2.0 | 43 open issues |
| MotionAGFormer-L | 38.4 MPJPE / 32.5 P-MPJPE | 243 frames | Apache-2.0 | WACV'24 |
| D3DP | not stated in README | multi-hypothesis | MIT | in-the-wild demo exists |

- **VideoPose3D.**
  - Other settings: 37.2 mm with ground-truth 2D input, and 48.8 mm at 27 frames.
  - In-the-wild inference is described as "experimental".
  - The non-commercial license blocks commercial use.
  - Source: [facebookresearch/VideoPose3D](https://github.com/facebookresearch/VideoPose3D)
- **MotionBERT.**
  - Input is "17 body keypoints" in H36M format: "If you are using other formats, please convert them before feeding to MotionBERT."
  - The in-the-wild path is: 2D extraction, then format conversion (`lib/data/dataset_wild.py`), then `infer_wild.py`.
  - Source: [Walter0807/MotionBERT](https://github.com/Walter0807/MotionBERT)
- **MotionAGFormer.**
  - Variants: XS (27 frames, 2.2M params), S (81 frames, 4.8M), B (243 frames, 11.7M) and L (243 frames, 19.0M, 78.3 GMACs). — [TaatiTeam/MotionAGFormer](https://github.com/TaatiTeam/MotionAGFormer)
  - Its in-the-wild demo uses YOLOv3 + HRNet and is adapted from MHFormer. — [TaatiTeam/MotionAGFormer](https://github.com/TaatiTeam/MotionAGFormer)
  - The MPJPE figures come from the [MotionAGFormer paper, arXiv 2310.16288](https://arxiv.org/pdf/2310.16288).
- **PoseFormerV2.** The 243-frame model uses about 1055 MFLOPs. The YOLOv3 + HRNet demo runs via `demo/vis.py`. — [QitaoZhao/PoseFormerV2](https://github.com/QitaoZhao/PoseFormerV2)
- **D3DP (diffusion, multi-hypothesis).**
  - `-num_proposals` sets the number of hypotheses and trades speed against accuracy.
  - The in-the-wild setup uses COCO-format keypoints from detectors such as AlphaPose, and the model must be retrained for them. A `main_in_the_wild.py` script and checkpoint are provided.
  - Source: [paTRICK-swk/D3DP](https://github.com/paTRICK-swk/D3DP)
- **Newer body lifters (2024-2026).** These sit around 37.9 mm MPJPE on Human3.6M:
  - TCPFormer is listed at 37.9 mm.
  - HSTGFormer (2026) reports 37.9 mm MPJPE and 31.5 mm P-MPJPE.
  - Mamba variants (PoseMamba, HGMamba) are in the same range.
  - The field is saturating at about 38 mm, and newer papers bring only small gains.
  - Sources: [HSTGFormer, arXiv 2608.12187](https://arxiv.org/pdf/2608.12187); [PoseMamba, arXiv 2408.03540](https://arxiv.org/pdf/2408.03540); [HGMamba, arXiv 2504.06638](https://arxiv.org/pdf/2504.06638)

**Whole-body lifting (H3WB)**
- **The dataset.** H3WB provides 133 whole-body keypoints in the COCO-WholeBody layout: 17 body, 6 feet, 68 face and 42 hand. It covers 100K Human3.6M images. Code is MIT-licensed, and image use follows the Human3.6M license. — [wholebody3d/wholebody3d](https://github.com/wholebody3d/wholebody3d)
- **Three tasks.**
  - 2D→3D: complete 2D lifted to 3D, with 80k training samples.
  - I2D→3D: incomplete or masked 2D lifted to 3D, which is relevant when hands are missed.
  - RGB→3D: image to 3D.
  - Source: [wholebody3d/wholebody3d](https://github.com/wholebody3d/wholebody3d)
- **2D→3D results (mm, pelvis-aligned).**
  - Jointformer: 88.3 all, 84.9 body, 66.5 face, 125.3 hands. Wrist-aligned hand error is 43.7 and nose-aligned face error is 17.8.
  - Large SimpleBaseline: 112.3 all and 114.8 hands, but the best wrist-aligned hand error at 31.7.
  - Source: [H3WB benchmark.md](https://github.com/wholebody3d/wholebody3d/blob/main/benchmark.md)
- **I2D→3D results.** Jointformer scores 109.2 all and 155.9 hands. — [H3WB benchmark.md](https://github.com/wholebody3d/wholebody3d/blob/main/benchmark.md)
- **fhswf/rtm133lifting.** This is a pip-installable 133-keypoint lifter.
  - It uses a SimpleBaseline architecture trained from scratch on H3WB (+T3WB). Input is 133 2D keypoints in H3WB / COCO-WholeBody format, and output is 133 3D keypoints.
  - License is MIT. Install with `pip install pose-estimation-recognition-utils-rtmlib`, then use `RTMLifting(num_keypoints=133)`.
  - The README reports no MPJPE, only raw loss values, so its quality is unverified.
  - Source: [HF fhswf/rtm133lifting](https://huggingface.co/fhswf/rtm133lifting/blob/main/README.md)

### Inferences
- **Body lifting from DWPose is straightforward.** DWPose emits COCO-WholeBody 133, whose first 17 points are COCO body. Map COCO-17 to H36M-17 by synthesising pelvis (mid-hip), spine and thorax (mid-shoulder), and head points. This is what MotionBERT's `dataset_wild.py` does.
- **Hips must be visible for H36M lifters.** These lifters were trained on full-body Human3.6M sequences. Waist-up signing video with no visible hips is out of distribution. Root-relative output then depends on hallucinated hip and pelvis positions.
- **Hands need a separate stage.** Pelvis-aligned hand error of more than 100 mm on H3WB is too coarse for handshape. For fingers, a better route is a dedicated 3D hand model (MediaPipe Hand world landmarks, or a hand-specific lifter) attached at the wrist. Wrist-aligned hand errors on H3WB are 31-44 mm.
- **Sequence windows add latency.** Temporal lifters with 81-243 frame windows reduce jitter but add latency, or need offline processing. For offline analysis of recorded clips (SignSure's likely use) this is acceptable.

### Gaps
- **D3DP numbers.** I could not confirm D3DP's Human3.6M MPJPE from the README.
- **No pip packages for the main lifters.** I found no official pip package for MotionBERT, MotionAGFormer or PoseFormerV2. They are research repos with custom scripts.
- **No whole-body temporal lifter.** I found no maintained temporal (video) lifter trained for 133 keypoints. All H3WB lifters appear to be single-frame.

## 3. Direct 3D whole-body models: RTMW3D / RTMPose3D in MMPose, and other 133-keypoint 3D models

### Takeaway
RTMW3D (OpenMMLab, 2024) is the only maintained, openly licensed single-image model I found that outputs all 133 COCO-WholeBody keypoints in 3D. It shares the RTMW 2D architecture, the same model family behind DWPose's successors. Its z is root-relative, it reports 0.056 MPJPE on H3WB in unclear units, and it can be run through MMPose, a PyTorch pip package or community ONNX weights.

### Cited Findings
- **Architecture.**
  - RTMW3D extends RTMW with a z-axis prediction branch in the decoder head.
  - x and y are predicted with SimCC coordinate classification, as in 2D.
  - z is predicted as an offset relative to a root point, to standardise depth across datasets.
  - 2D-only data gets a z-mask so 2D and 3D data can be trained together.
  - Source: [RTMW paper, arXiv 2407.08634](https://arxiv.org/html/2407.08634)
- **Training data.** 14 2D datasets plus 3 3D datasets: H3WB, UBody and DNA-Rendering. — [arXiv 2407.08634](https://arxiv.org/html/2407.08634)
- **Keypoints.** 133, using the COCO-WholeBody definition. This is the same layout as DWPose output. — [arXiv 2407.08634](https://arxiv.org/html/2407.08634)
- **H3WB test results.**
  - RTMW3D-l (384x288): 0.056. RTMW3D-x: 0.057.
  - Comparison rows: JointFormer 0.088, Large SimpleBaseline 0.112, CanonPose (3D-supervised) 0.117.
  - The paper does not state units. The baseline values match H3WB's 2D→3D mm table divided by 1000 (88.3 mm becomes 0.088), so 0.056 most likely means 56 mm whole-body MPJPE in metres. That would put the comparison against lifters with ground-truth 2D input, not against RGB→3D baselines.
  - Source: [arXiv 2407.08634](https://arxiv.org/html/2407.08634); [H3WB benchmark.md](https://github.com/wholebody3d/wholebody3d/blob/main/benchmark.md)
- **MMPose model zoo.**
  - RTMW3D-L: 0.678 COCO-WholeBody AP, 0.056 H3WB MPJPE.
  - RTMW3D-X: 0.680 AP, 0.057 MPJPE.
  - Both use 384x288 input and the "cocktail14" training mix.
  - Demo: `body3d_img2pose_demo.py`, which needs a person detector plus the pose config and checkpoint.
  - The demo's checkpoint filename (20240422) differs from the zoo link (20240626).
  - Source: [mmpose/projects/rtmpose3d](https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose3d)
- **Speed.**
  - CPU ONNXRuntime numbers exist only for 2D RTMW: RTMW-l is 35.3 ms at 256x192 and 47.6 ms at 384x288 (17.7 GFLOPs).
  - The paper gives no separate RTMW3D latency.
  - Source: [arXiv 2407.08634](https://arxiv.org/html/2407.08634)
- **Stated limitations.**
  - Monocular 3D is "ill-posed".
  - Scarce 3D whole-body data "severely hamper[s] the model's performance and generalization ability".
  - Evaluation covers H3WB only, which is the only open 3D whole-body test set.
  - Source: [arXiv 2407.08634](https://arxiv.org/html/2407.08634)
- **Community packaging.**
  - **rbarac/rtmpose3d**: Apache-2.0 PyTorch package for 133 keypoints. Install with `pip install git+https://github.com/b-arac/rtmpose3d.git`. Requires Python ≥3.8 and PyTorch ≥2.0. — [HF rbarac/rtmpose3d](https://huggingface.co/rbarac/rtmpose3d/blob/main/README.md)
  - **Conflicting metric**: that HF page reportedly lists RTMW3D-L at 0.045 MPJPE, which conflicts with the official 0.056. Trust the official README. — [HF rbarac/rtmpose3d](https://huggingface.co/rbarac/rtmpose3d/blob/main/README.md) vs [mmpose README](https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose3d)
  - **ONNX weights**: Soykaf/RTMW3D-x (about 369 MB) are used by a Harvard MMLA browser tool that runs on ONNX Runtime Web (WebGPU, falling back to WASM).
    - It outputs image-pixel x/y plus `x3d, y3d, z3d` in "root-relative metres, Y-up".
    - It tracks up to 4 people.
    - It reports no accuracy metrics.
    - Source: [Harvard MMLA RTMW3D tool](https://mmla.gse.harvard.edu/tools/rtmw3d)
  - **rtmlib** (pip, depends only on onnxruntime and opencv) ships 2D RTMW / DWPose models. I found no evidence of an official RTMW3D model in rtmlib. — [Tau-J/rtmlib](https://github.com/Tau-J/rtmlib) (search summary)

### Inferences
- **Easiest upgrade for SignSure.** RTMW3D is the most natural "3D DWPose". It has the same 133-keypoint layout and the same model family, so the existing keypoint indexing and visualisation code carries over. The 2D x/y channel should be comparable in quality to RTMW 2D (0.678 AP).
- **Expected hand and finger accuracy is weak.** The only open 3D whole-body training data is H3WB, which has studio Human3.6M actors and few varied hand shapes. Expect finger depth to be weak, likely similar in scale to the H3WB hand errors above (tens of mm wrist-aligned, more than 100 mm pelvis-aligned for lifters). No per-part RTMW3D breakdown was found.
- **Frame-to-frame jitter.** Single-image inference has no temporal model, so 3D output will jitter. Use a One-Euro or Savitzky-Golay filter or a temporal lifter.

### Gaps
- **No per-part RTMW3D errors.** I found no published body / face / hand breakdown for RTMW3D on H3WB.
- **No RTMW3D speed figures.** I found no GPU or CPU FPS numbers for RTMW3D.
- **MMPose maintenance.** I did not verify release activity in 2025-2026. The project's activity reportedly slowed after v1.3, but this is unconfirmed.
- **Other 3D whole-body keypoint models.** I found no other maintained 133-keypoint 3D (non-mesh) model. Mesh methods (SMPL-X family) are excluded by scope.

## 4. Typical accuracy and failure modes: depth ambiguity, scale, camera- vs root-relative coordinates, jitter

### Takeaway
Root-relative body MPJPE ranges from about 37-47 mm (Human3.6M lifters, in-domain) to about 36-45 mm (MediaPipe's own yoga test) to about 56 mm whole-body (RTMW3D on H3WB). Hands are much worse once expressed relative to the pelvis. Every method here is root-relative with no absolute depth. Scale is a learned average-human prior, and in-domain benchmark numbers overstate real-world accuracy.

### Cited Findings
- **Monocular 3D is ill-posed.** z is ambiguous from one RGB view, and scarce 3D data limits generalisation. — [arXiv 2407.08634](https://arxiv.org/html/2407.08634)
- **Several 3D poses can explain the same 2D image.** BlazePose needed human depth-order annotations, which cut depth-order errors from 25% to 3%. — [arXiv 2206.11678](https://ar5iv.labs.arxiv.org/html/2206.11678)
- **Root-relative outputs.**
  - MediaPipe world landmarks are hip-centred metres. — [MediaPipe pose.md](https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/pose.md)
  - RTMW3D gives root-relative z in metres. — [Harvard MMLA tool](https://mmla.gse.harvard.edu/tools/rtmw3d); [arXiv 2407.08634](https://arxiv.org/html/2407.08634)
  - H3WB metrics are pelvis-aligned, with extra wrist- and nose-aligned scores for hands and face. — [H3WB benchmark.md](https://github.com/wholebody3d/wholebody3d/blob/main/benchmark.md)
- **Detected vs ground-truth 2D input.** The gap is large: VideoPose3D goes from 37.2 mm with ground-truth 2D to 46.8 mm with CPN-detected 2D. Errors in 2D input propagate into 3D. — [VideoPose3D](https://github.com/facebookresearch/VideoPose3D)
- **Missing 2D keypoints make lifting much worse.** On H3WB, Jointformer goes from 88.3 to 109.2 mm whole-body, and hands from 125.3 to 155.9 mm. — [H3WB benchmark.md](https://github.com/wholebody3d/wholebody3d/blob/main/benchmark.md)
- **The BlazePose lifter generalises poorly.** It reports 121 MPJPE and 78 PA-MPJPE (units not stated) versus 138-156 for compared methods. That illustrates cross-domain error far above in-domain Human3.6M numbers. — [arXiv 2206.11678, Table 4](https://ar5iv.labs.arxiv.org/html/2206.11678)
- **Joint-angle bias in practice.** BlazePose against OptiTrack showed +18.9° elbow bias. — [MDPI Sensors](https://www.mdpi.com/1424-8220/23/1/3) (search summary). Klein et al. (2023) reported MediaPipe Holistic angle mean absolute error up to about 17°, with a wall-mounted compass as reference (search summary, source list in [VTT CRIS](https://cris.vtt.fi/en/publications/markerless-upper-limb-motion-tracking-a-comparative-evaluation-of/)). Both are lower-confidence.

### Inferences
- **What these errors mean for joint angles.** For a forearm of about 25 cm, a 3-5 cm depth error at the wrist relative to the elbow implies roughly 7-12° of angle error. This matches the reported elbow biases. 3D elbow flexion from a monocular model should therefore be treated as about ±10-20° unless it is validated. SignSure's git history mentions elbow-flexion validation, so this is directly relevant.
- **Distance between signers is not recoverable.** Because outputs are root-relative, absolute distance to the camera and inter-person distances are not available. Limb length is normalised to an average body, so per-signer anthropometrics are lost.
- **Jitter.** Single-frame models (MediaPipe, RTMW3D) jitter. Temporal lifters (MotionBERT, MotionAGFormer) are smoother but need multi-frame windows.

### Gaps
- **No sign-language benchmark.** I found no benchmark measuring 3D arm and hand accuracy specifically for sign-language motion, such as arms in front of the torso or hand-face contact.
- **No head-to-head comparison.** I found no comparison of MediaPipe world landmarks against RTMW3D on the same data.

## 5. Practical pipeline: code, repos, pip packages, GPU vs CPU, real-time feasibility

### Takeaway
Four practical routes, from easiest to most involved:
- **MediaPipe** (`pip install mediapipe`): CPU real-time, body and hand world landmarks in separate frames.
- **RTMW3D**: MMPose project, community PyTorch pip, or ONNX weights. Gives 133-keypoint 3D, GPU recommended.
- **DWPose / RTMW 2D plus a lifter**: MotionAGFormer or MotionBERT for the body, rtm133lifting for whole-body.
- **A hybrid**: an RTMW3D or lifted body plus MediaPipe hand world landmarks attached at the wrists.

Everything listed except VideoPose3D (CC BY-NC) is permissively licensed (Apache-2.0 or MIT). Dataset licenses (Human3.6M) may still constrain trained weights.

### Cited Findings
- **MediaPipe.**
  - Latency is 7-10 ms per frame on a desktop GPU, and about 15 FPS for the holistic pipeline on phones and browsers. — [arXiv 2206.11678](https://ar5iv.labs.arxiv.org/html/2206.11678)
  - Hand landmarker latency is 17 ms on Pixel 6 CPU. — [Hand Landmarker docs](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker)
- **RTMW3D via MMPose.** Requires the MMPose + MMCV + MMDet stack and a person detector. Run `projects/rtmpose3d/demo/body3d_img2pose_demo.py` with `PYTHONPATH` set. — [mmpose rtmpose3d](https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose3d)
- **RTMW3D via pip.** `pip install git+https://github.com/b-arac/rtmpose3d.git` (PyTorch ≥2.0, Apache-2.0). — [HF rbarac/rtmpose3d](https://huggingface.co/rbarac/rtmpose3d/blob/main/README.md)
- **RTMW3D via ONNX.** Soykaf/RTMW3D-x (about 369 MB) runs in ONNX Runtime Web with WebGPU or WASM. — [Harvard MMLA](https://mmla.gse.harvard.edu/tools/rtmw3d)
- **rtmlib.** pip package with onnxruntime-only dependencies for 2D RTMW / DWPose. — [Tau-J/rtmlib](https://github.com/Tau-J/rtmlib)
- **Whole-body lifting via pip.** `pip install pose-estimation-recognition-utils-rtmlib` gives 2D RTM estimation plus 133-keypoint lifting (MIT). Accuracy is unreported. — [HF fhswf/rtm133lifting](https://huggingface.co/fhswf/rtm133lifting/blob/main/README.md)
- **Temporal body lifters.**
  - MotionBERT (Apache-2.0, `infer_wild.py`). — [MotionBERT](https://github.com/Walter0807/MotionBERT)
  - MotionAGFormer (Apache-2.0; the XS variant has 2.2M params and 27 frames, suited to fast inference). — [MotionAGFormer](https://github.com/TaatiTeam/MotionAGFormer)
  - PoseFormerV2 (MIT). — [PoseFormerV2](https://github.com/QitaoZhao/PoseFormerV2)
  - D3DP (MIT, in-the-wild retrained on COCO keypoints). — [D3DP](https://github.com/paTRICK-swk/D3DP)
- **Avoid VideoPose3D** for commercial or maintained use: CC BY-NC and archived in 2023. — [VideoPose3D](https://github.com/facebookresearch/VideoPose3D)

### Inferences
- **Lowest-effort first step.** Switch MediaPipe calls to read `pose_world_landmarks` and the hand world landmarks. This adds metric 3D without new models and runs in real time on CPU.
- **Best match to the existing DWPose pipeline.** RTMW3D-L, run offline on GPU (or CPU via ONNX at reduced speed), keeps the 133-keypoint indexing. Add temporal smoothing.
- **Body accuracy and smoothness on recorded video.** Run DWPose 2D, map to H36M-17, then MotionAGFormer or MotionBERT (243 frames). Hands still need MediaPipe hand world landmarks or another dedicated hand model.
- **Validate before trusting 3D angles.** Check 3D joint angles against a reference (mocap, or a second camera) before using them for clinical- or grading-style decisions.

### Gaps
- **No measured FPS for RTMW3D or the lifters.** I did not find FPS figures for RTMW3D or the temporal lifters on consumer GPU or CPU, or on Apple Silicon (the user's platform is macOS).
- **Weight licensing.** Licensing of weights trained on Human3.6M / H3WB (research-only dataset terms) was not examined. This may matter for commercial deployment regardless of code license.
