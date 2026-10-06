# Action-shape audit — Father and Addition

Current reports:
- Addition: http://127.0.0.1:5173/analysis?job=4977835b0be44d8b899934d92e116531
- Father: http://127.0.0.1:5173/analysis?job=9145dca0a2af4fdf80a45dc0c13cefa8

The per-case `_job.json` files identify output directories. All earlier reports
remain historical artifacts. Source, model and code hashes and all alignment
annotations are in each report. The video was DeepMotion's input, not a held-out
independent reference view.

## Verified finding: effectively fixed DeepMotion finger bends

Maximum change among 15 native finger-bend angles per hand, in degrees:

| Case | Hand | Rokoko | Supplied DeepMotion export |
|---|---|---:|---:|
| Addition | Left | 71.783897 | 0.00003624 |
| Addition | Right | 85.204067 | 0.00003243 |
| Father | Left | 4.821751 | 0.00003052 |
| Father | Right | 31.666889 | 0.00003243 |

These are articulation ranges in FBX files, not reference errors. They use
native frames inside previously reviewed action windows, without camera fitting,
time warping or interpolation. All 40 finger-node parent relationships in each
file were checked against Mixamo chain naming. Independent atan2(norm(cross(u,v)),
dot(u,v)) calculations agree with report acos calculations within 1e-6 degrees.
See `independent_finger_verification.json`. Reproduce from the project root with
`PYTHONPATH=backend .venv/bin/python study/action_shape_audit/verify_fingers.py`.

Video hand crops show changing finger configurations during Addition. Rokoko
contains finger articulation; these DeepMotion exports retain effectively fixed
bends. The origin is unconfirmed: the user has not checked the original DeepMotion
preview or raw download. Tracking settings, failed tracking, and loss during
export/retargeting are possible causes, not established facts.

## Body results and limits

The new mode uses one constrained DTW path per method, shared by all parts, with
a 10% phase band. Direction and bend scores reduce segment-length effects;
original position and timing scores remain available. Cameras use torso-only
calibration and show sensitivity to alternative fits. Addition's primary fit
favors Rokoko on right-arm angles and DeepMotion on left-arm angles. Several
rankings change with camera calibration. Torso/shoulder metrics overlap the
calibration features and are not independent validation.

The hand tracker at 0.70 thresholds, including enlarged wrist crops, produced
sparse observations: Addition 1.5% left / 6.1% right; Father 0.9% each. After
window and projected-segment quality checks, no finger reference score meets
80% coverage. `*_hand_review.png` shows sampled crops: gloves, overlapping hands
and blur are visible, but their individual effects were not isolated. Head/neck
and individual spinal joints remain unassessed because their anatomical video/FBX
correspondence is not validated. No full upper-body accuracy, linguistic accuracy,
statistical equivalence or universal method superiority is established.

References:
- https://www.audiolabs-erlangen.de/resources/MIR/FMP/C3/C3S2_DTWbasic.html
- https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker
