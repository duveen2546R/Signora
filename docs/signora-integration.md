# Driving the existing WebGL build

`SignoraAvatarTracking/` already contains a complete retargeting runtime. It does **not** consume
baked bone rotations — it consumes MediaPipe-style landmarks and retargets in-engine. The backend
therefore emits that format, and the shipped `WebBuild/` runs **unmodified**.

## The protocol

| | |
|---|---|
| Target object | `SignoraTrackingRuntime` (created at runtime by `SignoraRuntimeBootstrap`) |
| Send a frame | `SendMessage("SignoraTrackingRuntime", "ReceiveFrame", json)` |
| Start calibration | `SendMessage("SignoraTrackingRuntime", "BeginCalibration")` |
| Unity → page | `window.SignoraUnityReady()`, `window.SignoraCalibrationState(state)` |

The JSON is `CanonicalTrackingFrameV1`. `TrackingFrameStore.TryPublish` rejects a frame outright
unless **all** of these hold:

- `schemaVersion == 1`
- exactly **33** pose landmarks, exactly **21** per hand
- `face.transform` is exactly **16** floats (even when no face is tracked)
- `inferenceEndTimeMs >= captureTimeMs`
- `sequence` is strictly greater than the last accepted one — it never resets except on reload

Landmark `confidence` must clear `MinimumLandmarkConfidence` (0.45). Motion capture is exact, so
everything is sent at 1.0.

## Landmark mapping

Rokoko's biomechanics export gives joint centres and so does MediaPipe, so the mapping is direct
(`backend/app/ingest/landmarks.py`). Rokoko positions are each segment's *proximal* end, which is
why `ProximalPhalangx` lands on the knuckle:

| MediaPipe | Rokoko segment |
|---|---|
| 11/12 shoulders | `Left/RightUpperArm` |
| 13/14 elbows | `Left/RightForeArm` |
| 15/16 wrists | `Left/RightHand` |
| 23/24 hips | `Left/RightUpperLeg` |
| hand 0 | `{side}Hand` |
| hand 5/9/13/17 (knuckles) | `{side}Digit2..5ProximalPhalangx` |
| hand 1/2/3 (thumb) | `{side}Digit1MetaCarpal / ProximalPhalangx / DistalPhalanx` |

**Fingertips are synthesised.** Rokoko's chain ends at the distal joint but MediaPipe carries a tip,
and the runtime drives each finger's last bone from *distal → tip*. Extrapolating straight would
leave that bone permanently uncurled, so the measured terminal flexion is applied about the finger's
own bend axis, recovered from the curl it already has.

## Calibration is the load-bearing detail

The runtime is calibration-relative: whatever pose arrives during its 2-second window is mapped onto
the avatar's **bind rotation**, and every later frame is applied as a delta from it.

This avatar's bind pose is a **T-pose**. The takes contain no T-pose — they start with the arms down.
Calibrating on a take's first frame would therefore map arms-down onto a T-pose and offset every
sign by roughly 90 degrees.

So the calibration reference is generated from the **avatar's own bind pose**
(`backend/tools/extract_bind_pose.py`, served at `GET /api/v1/rigs/calibration`). The reference then
maps to identity, and each bone points exactly where the suit says.

Regenerate it if the avatar changes:

```bash
cd backend && ./.venv/bin/python tools/extract_bind_pose.py \
  ../SignoraAvatarTracking/Assets/Models/Avaturn/SignoraNewAvatar.glb -o data/calibration.json
```

The extractor converts glTF's right-handed axes to Unity's by negating X, matching
`com.unity.cloud.gltfast` 6.20. That conversion is self-checked: the avatar's left shoulder must
land at negative X.

## Streaming

`frontend/src/unity/SignoraPlayer.js` drives the stream on `requestAnimationFrame`, which stays in
step with Unity's own loop.

Two behaviours matter:

- **Never pause mid-sentence.** The driver blends a channel back to its bind pose once frames are
  older than 0.2s, so the player keeps resending the current pose between signs.
- **Calibration is outcome-driven.** `calibrating` is a progress notification, not success; motion
  stays blocked until Unity reports `complete`, `partial-hand`, or `body-only`. The calibration
  reference is generated, immutable bind-pose data, so Unity requires one accepted sample instead
  of a camera-style multi-frame average. This remains reliable in throttled/background WebGL panes.
  If Unity still reports `failed-body`, the player retries rather than trusting `document.hidden`,
  which is unreliable in embedded panes.

## Bone names

The retargeters look bones up **by name** (Mixamo convention). All are present in
`SignoraNewAvatar.glb` — verified in `backend/tests/test_signora_integration.py`, which also asserts
that every landmark pair really corresponds to the bone it drives:

`LeftArm`, `LeftForeArm`, `RightArm`, `RightForeArm`, `Spine2`, `Neck`, `Head`,
`{side}Hand`, `{side}Hand{Thumb,Index,Middle,Ring,Pinky}{1,2,3}`.
