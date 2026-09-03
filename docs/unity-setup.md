# Unity setup

The Unity project lives in `unity/SignSureAvatar/`. This repo carries the scripts; create the Unity
project around them (Unity 2022 LTS or newer, **3D (URP or Built-in)** template) and copy
`Assets/Editor`, `Assets/Scripts` and `Assets/Plugins` into it.

## 1. Import the avatar as a Humanoid

In the model's import settings:

- **Rig > Animation Type: Humanoid**, Avatar Definition: *Create From This Model*.
- Open **Configure** and confirm every bone is mapped — especially all 30 finger bones
  (5 fingers x 3 joints x 2 hands). Unmapped fingers mean unreadable handshapes, and the exporter
  will warn you about exactly which ones are missing.
- Apply.

## 2. Scene

Create a scene with the avatar, a camera framing it from mid-thigh up (signing space is chest to
head — a full-body shot wastes most of the frame), and neutral lighting.

On the avatar GameObject add: `SignPlayer`, `SignSequencer`, `SignBridge`.

- `SignBridge.apiBaseUrl` → `http://localhost:8000` for local development.
- Name the GameObject **`SignBridge`** — React addresses it by name via `SendMessage`.
- `SignPlayer` disables the `Animator` on Awake: it writes bone rotations directly, and anything
  else posing the rig at the same time would fight it.

## 3. Export the rig profile

Select the avatar, then **SignSure > Export Rig Profile**, and save `rig_profile.json`.

The exporter first forces the rig into Unity's canonical neutral pose (all muscles zero) so the
export is identical no matter how the model happens to be posed in the scene. Upload the file on the
app's Capture tab. **Nothing can be ingested until this exists** — it is the only thing the backend
cannot derive from the motion data itself.

Re-export and re-ingest whenever the rig changes. Clips carry the profile's digest, and a mismatch is
a hard error at load time rather than a silently wrong pose.

## 4. WebGL build

**File > Build Settings > WebGL**, then in Player Settings:

| Setting | Value | Why |
|---|---|---|
| Compression Format | Brotli | Smallest payload |
| Decompression Fallback | On | Unless the host sets `Content-Encoding: br` itself |
| Enable Exceptions | None | Explicit only while debugging |
| Managed Stripping Level | High | Cuts build size |
| Data Caching | On | Avoids re-downloading the build |
| Color Space | Gamma | Cheaper on low-end GPUs |

Build with output name `SignSureAvatar`, then copy the build into the frontend:

```bash
cp -r <build-output>/Build frontend/public/unity/
```

`AvatarStage.jsx` expects `frontend/public/unity/Build/SignSureAvatar.{loader.js,data,framework.js,wasm}`.
The directory is gitignored — it is build output, not source.

## Troubleshooting

**The avatar T-poses and never moves.** The clip loaded but no bones resolved. Check the console for
the SignPlayer warning listing unmapped bones; it usually means the rig is not Humanoid, or the
GameObject with the Animator is not the one carrying `SignPlayer`.

**Fingers do not move.** The avatar's finger bones are unmapped in the Humanoid configuration. Re-open
Configure and map them, then re-export the rig profile.

**Clip refuses to load.** Digest mismatch — the clip was retargeted against a different rig profile.
Re-export and re-ingest.
