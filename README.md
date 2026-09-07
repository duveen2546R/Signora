# SignSure

SignSure turns English text into sign-language performances by a motion-captured avatar in the
browser.

```text
Rokoko Studio ──CSV──▶ FastAPI ingest ──landmarks──▶ Unity WebGL ──▶ React
                          │                             ▲
                  avatar bind pose ───calibration───────┘
                  (from SignoraNewAvatar.glb)
```

Rokoko biomechanics CSV exports are converted into MediaPipe-style body and hand landmarks. The
React application streams those frames to the Unity runtime, which retargets them onto the avatar.
See [docs/signora-integration.md](docs/signora-integration.md) for the browser/Unity protocol.

Annotate Start/Sign/End once per recording. The backend retains phases by sentence position and
automatically blends neighbouring signs into one quality-gated motion track. There are no
pair-specific settings or required pair approvals. Unsafe joins are rejected with diagnostics;
sentences never fall back through neutral or play degraded motion. See [docs/sentence-blending.md](docs/sentence-blending.md) for the algorithm and preview
workflow.

English sentence signing uses a versioned registry of reviewed ISL patterns. The bundled patterns
are candidates awaiting fluent ISL review; a unique candidate can play as an explicitly labelled
literal sign preview but is not presented as an approved translation. Missing signs, ambiguous
patterns, and unsupported sentences never play partially. Use individual recording previews,
**Edit timestamps**, and **Preview automatic transitions** to prepare recordings for review. See
[ISL review and release workflow](docs/isl-review.md) for approval and validation steps.

## Requirements

- Python 3.11 or newer
- Node.js 20.19+ or 22.12+ and npm
- Unity 6000.5.9f1 with WebGL Build Support, only when rebuilding the avatar

## Quick start

Run the backend and frontend in separate terminals from the repository root.

### 1. Backend

Create the environment once:

```bash
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements-dev.txt
```

Start the API:

```bash
cd backend
./.venv/bin/uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Wait for the avatar badge to show
`calibrated:complete`, then choose a recorded sign or enter a sentence.

Vite proxies `/api` to the backend on port 8000. Override the API location with
`VITE_API_BASE` when the services are hosted separately.

## Live microphone signing

The Studio uses Chrome's Web Speech API for English (`en-IN`) microphone signing. Click **Start
listening**. Fast mode dispatches stable interim prefixes after 220 ms, or a trailing word after
350 ms, with up to 550 ms of lookahead for registered phrases such as “good morning”. Final results
only dispatch the remaining words. A revision to words already dispatched is reported; playback
cannot undo those signs. Clear stops recognition and discards late responses. This uses no project
API key, although Chrome may use an online recognition service.

Live playback adjusts its rate at chunk boundaries using observed word-arrival intervals and queued
motion. Speedup is capped at 1.5× and further restricted by measured wrist/limb speeds in each
artifact. This mechanical limit does not certify linguistic intelligibility. Slow speech uses the
original rate. Manual sign previews retain their original rate. The UI distinguishes transcript-to-queue
time from buffered motion; neither includes Chrome's audio-to-transcript latency. Under-one-second
audio-to-sign latency is a target, not a guarantee, especially when the recorded motion takes longer
than the speech or the browser delays recognition.

Live requests only read compiled artifacts and retain a bounded in-memory cache of decoded frames;
they never run the motion compiler while the microphone is active. Missing artifacts produce an
actionable preparation message instead of delaying subsequent speech by several seconds.
Live motion is persisted as content-addressed single-sign and directed-pair artifacts. Compile or
resume the local library after recording, changing timestamps, or selecting a new canonical take:

```bash
cd backend
./.venv/bin/python tools/compile_live_library.py
```

Use `--limit N` for a bounded batch or repeat `--gloss HELLO` to rebuild pairs touching selected
signs. `GET /api/v1/live/readiness` reports the current library version, missing core/A–Z captures,
compiled transition count, and failures. The initial publication target is the documented 25 core
glosses plus A–Z; until those recordings exist, the panel truthfully reports an incomplete library
while known phrases remain available as previews. Set `VITE_LIVE_SIGNING=false` to hide live mode.

## Uploading motion captures

Open the **Capture** tab and upload a Rokoko Studio **biomechanics CSV**. Use one sign per file.
For each selected file, enter the timestamps where the meaning-bearing sign starts and ends. The
Capture screen shows the derived `start`, `sign`, and `end` ranges before upload. Both boundaries
are required; captures without timestamps are rejected. These authored
boundaries let a first word play `start + sign`, a middle word play only `sign`, and a final word
play `sign + end`. A single sign plays all three phases. Boundaries must match actual CSV
Timestamp rows and, when present, the CSV Phase labels. Existing recordings can be inspected and
edited through **Edit timestamps**; no re-upload is needed unless the source CSV itself is wrong.
The filename determines the gloss and take number:

| Filename | Gloss | Take |
|---|---:|---:|
| `hello.csv` | `HELLO` | 1 |
| `hello_01.csv` | `HELLO` | 1 |
| `hello_02.csv` | `HELLO` | 2 |
| `good_morning_03.csv` | `GOOD_MORNING` | 3 |

The numeric suffix is optional. Use `_01`, `_02`, and so on only when keeping multiple takes of
the same sign. Uploading `hello.csv` and `hello_01.csv` targets the same take, so the later upload
replaces the earlier one.

On a new backend database, upload an avatar rig profile before uploading captures. The legacy
`.signclip` fallback still uses this profile during ingest; see [docs/unity-setup.md](docs/unity-setup.md)
for the exporter workflow.

Uploaded CSVs, generated clips, and the local SQLite database live under `backend/data/` and are
intentionally ignored by Git. The `.gitkeep` files preserve the required empty directories.

Captures are registered only through the Capture screen/API; copying a CSV directly into
`backend/data/uploads/` does not import it. Bulk workflows may add a `Phase` column whose every row
is labelled `start`, `sign`, or `end`; the three runs must be contiguous and ordered.

## Avatar calibration

The checked-in `backend/data/calibration.json` contains the avatar's bind pose. Regenerate it after
changing the avatar model:

```bash
cd backend
./.venv/bin/python tools/extract_bind_pose.py \
  ../SignoraAvatarTracking/Assets/Models/Avaturn/SignoraNewAvatar.glb \
  -o data/calibration.json
```

Playback remains disabled until Unity reports a terminal calibration result. The bind-pose input is
deterministic, so one accepted Unity sample is sufficient even in a throttled browser pane.

## Rebuilding Unity WebGL

Unity build output is intentionally ignored because it is about 73 MB. To create or refresh it:

1. Open `SignoraAvatarTracking/` in Unity 6000.5.9f1.
2. Choose **Signora → Build WebGL**.
3. Confirm that `SignoraAvatarTracking/WebBuild/Build/WebBuild.wasm` exists.

The tracked `frontend/public/unity` symlink points to that `WebBuild` directory, so no copy step is
required. Restart or reload the frontend after rebuilding. For a production bundle, run:

```bash
cd frontend
npm run build
```

## Tests

```bash
cd backend && ./.venv/bin/python -m pytest -q
cd frontend && npm test && npm run lint && npm run build
```

## Repository layout

| Path | Purpose |
|---|---|
| `backend/app/ingest/` | CSV parsing, landmark generation, reconstruction, and retargeting |
| `backend/app/api/v1/` | Capture upload, sign library, clip serving, and text translation APIs |
| `frontend/` | Vite/React application and browser-side Unity frame player |
| `SignoraAvatarTracking/` | Active Unity avatar project and retargeting runtime |
| `unity/SignSureAvatar/` | Earlier baked-rotation `.signclip` player retained as a fallback |
| `docs/` | Capture protocol, integration details, and clip format documentation |

## Retargeting paths

The active path is Rokoko CSV → landmark JSON → Signora Unity runtime.

`unity/SignSureAvatar/` and the `.signclip` format in `backend/app/ingest/` are an earlier fallback
that bakes bone rotations in Python. The browser application does not currently play that format.

Read [docs/capture-protocol.md](docs/capture-protocol.md) before recording vocabulary at scale.
