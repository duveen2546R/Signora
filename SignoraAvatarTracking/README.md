# Signora Avatar Tracking (Unity)

The Unity half of [Signora](../README.md): it receives canonical tracking frames from the
browser and drives an Avaturn avatar. The web studio and its backend live outside this project,
at the repository root.

Open with Unity `6000.5.9f1`.

## Runtime

- `Assets/Signora/Runtime/Tracking/` - canonical frame contract, validation, One Euro filtering,
  frame store, and a replay source for Editor work.
- `Assets/Signora/Runtime/Retargeting/` - rig binding, body/hand/face retargeting, calibration.
- `Assets/Signora/Runtime/WebGL/` - `SendMessage` receiver and bootstrap.
- `Assets/Plugins/WebGL/SignoraTrackingBridge.jslib` - calls back into the page.

`SignoraRuntimeBootstrap` runs on load, creates the `SignoraTrackingRuntime` GameObject, and
binds to the scene object named `SignoraNewAvatar`. No scene wiring is required.

## The contract

The browser sends `CanonicalTrackingFrameV1` as JSON to `SignoraTrackingRuntime.ReceiveFrame`.
`CanonicalTrackingFrameV1.IsStructurallyValid` rejects anything that does not match the schema,
and `TrackingFrameStore` additionally rejects out-of-order sequences. The frontend validates the
same five invariants before sending, in `frontend/src/tracking/canonical.js` - keep the two in
step.

## Running without a browser

Attach `CanonicalFrameReplaySource` and give it a `CanonicalTrackingRecording` JSON TextAsset.
It publishes through the same store, so filtering, calibration, and retargeting behave exactly
as they do live.

## WebGL build

Build for WebGL into `WebBuild/` in this folder. Nothing needs copying or renaming: the backend
discovers the build and its name, and the studio loads it on the next page refresh.

## Tests

EditMode tests covering the frame contract and the One Euro filter live in
`Assets/Signora/Tests/EditMode/`. Run them from the Unity Test Runner.
