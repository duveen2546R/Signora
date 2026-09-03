# `.signclip` format v1

A retargeted sign, ready for Unity to play with no per-frame maths. Little-endian throughout.

| Field | Type | Notes |
|---|---|---|
| `magic` | `char[4]` | `SGNC` |
| `version` | `u16` | `1` |
| `flags` | `u16` | bit0 = has root motion |
| `fps` | `f32` | 60.0 |
| `frameCount` | `u32` | |
| `boneCount` | `u16` | |
| `rigDigest` | `u64` | first 16 hex chars of the rig profile's SHA-256 |
| `boneTable` | `boneCount x (u8 len + utf8)` | Unity `HumanBodyBones` names |
| `rootPositions` | `f32[3] x frameCount` | hips only, present when bit0 is set |
| `rotations` | `i16[4] x boneCount x frameCount` | local quaternions `x,y,z,w`, scaled by 32767 |

Rotations are **local** — already expressed in each bone's parent space — so playback is
`bone.localRotation = clip.rot[frame][i]` and nothing more.

## Why int16 quaternions

One int16 step is about 0.006° of rotation, well below anything visible, and it halves the file
against float32. A two-second sign at 60 fps across 46 bones is about 58 KB, which streams instantly
and caches forever (clip URLs are content-addressed and served `immutable`).

Encoder canonicalises sign (`w >= 0`) before quantising, so `q` and `-q` never round differently
between adjacent frames.

## Rig digest

Clips are only valid for the avatar they were retargeted onto. The digest is checked at load time and
a mismatch is a hard error rather than a silently wrong pose. If the rig changes, re-export the
profile and re-ingest — which is why every source CSV is kept.

Implementations: `backend/app/ingest/clipfmt.py` and `unity/SignSureAvatar/Assets/Scripts/SignClip.cs`.
Change both together.
