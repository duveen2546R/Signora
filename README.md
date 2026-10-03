# SignSure

SignSure turns English text into sign-language performances by a motion-captured avatar in the
browser.

```text
Rokoko Studio ──combined FBX──▶ FastAPI normalization ──motion JSON──▶ Unity WebGL ──▶ React
                                                                          ▲
                   SignoraNewAvatar.glb ─────single rendered avatar────────┘
```

Combined Rokoko FBX exports are sampled at 60 fps into MediaPipe-style body/hand landmarks and 52
named ARKit facial-expression coefficients. The FBX character is never rendered. React streams the
normalized motion to Unity, which retargets it onto the existing `SignoraNewAvatar.glb` avatar.

Annotate Start/Sign/End once per recording. The backend retains phases by sentence position and
automatically blends neighbouring signs into one quality-gated motion track. There are no
pair-specific settings or required pair approvals. Unsafe joins are rejected with diagnostics;
sentences never fall back through neutral or play degraded motion. Use **Preview automatic transitions** to inspect joins before sentence playback.

English sentence signing uses a versioned registry of reviewed ISL patterns. The bundled patterns
are candidates awaiting fluent ISL review; a unique candidate can play as an explicitly labelled
literal sign preview but is not presented as an approved translation. Missing signs, ambiguous
patterns, and unsupported sentences never play partially. Use individual recording previews,
**Edit timestamps**, and **Preview automatic transitions** to prepare recordings for review. Fluent ISL review is required before publishing these patterns as approved translations.

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

## YouTube subtitle signing

Open **Watch** and provide a YouTube URL plus the video's matching UTF-8 SRT or WebVTT subtitle
file. SignSure groups captions into complete units, resolves reviewed ISL patterns first, and then
uses a clearly labelled literal preview when the available vocabulary permits it. Articles are
omitted, while copulas are removed only in simple affirmative present-tense statements. Questions,
negation, and tense-bearing forms are not silently simplified. An unknown word is fingerspelled only
when the complete A–Z library is available; otherwise the entire unit is skipped.

The official YouTube iframe remains the timing master. Pausing or buffering freezes the avatar,
seeking resets it to neutral and starts at the next complete unit, and the video automatically pauses
when a sign needs more time. The uploaded subtitle bytes are parsed in memory and are not retained;
only normalized plan text and content-addressed compressed motion are stored locally. Set
`VITE_YOUTUBE_SIGNING=false` to hide the Watch page.

## Live microphone signing

The Studio defaults to free **local streaming recognition** (Sherpa-ONNX, English), not Chrome's
network speech service. This is a literal signing preview, not a reviewed ISL sentence translation.
Install and prepare once using the Python environment that actually runs your backend:

```bash
cd backend
./.venv/bin/python -m pip install -r requirements-live.txt
./.venv/bin/python tools/setup_live_speech.py
./.venv/bin/python tools/compile_live_library.py --streaming
```

If uvicorn uses the repository-root `.venv`, use `../.venv/bin/python` instead. The model download is
about 44 MB of extracted weights, licensed Apache-2.0; no API key or paid recognition service is used.
Microphone audio stays in memory on your local machine. The optional **Chrome fallback** uses `en-IN`
and may send audio to Chrome's recognition service; it has no sub-second timing guarantee.

After the avatar calibrates, click **Warm local recognizer**, then **Start listening**. AudioWorklet
resamples to 16 kHz and streams 20 ms PCM packets through `/api/v1/live/session`. Stable complete
words commit across successive decoder updates; multiword aliases have bounded lookahead. Late
recognition corrections are shown, not replayed. Stop flushes recognition and drains accepted signs;
Clear cancels the stream generation and playback. Losing the device/connection or hiding the tab
stops capture visibly. A 60-second pending-motion limit stops new capture rather than dropping signs.

Adaptive mode uses audio-token timing, not request arrival times. It selects normal or compiled 80%
variants only at neutral boundaries and keeps that variant through a continuous run. Protected Sign
frames are never accelerated just to catch speech. Optional neutral waiting is capped at 100 ms.
If the recordings cannot keep up, the UI shows buffered motion instead of hiding the backlog.

The UI separately labels transcript-to-queue, estimated audio-to-sign submission, and (with a rebuilt
Unity runtime) estimated audio-to-Unity-applied sign. Token timing is approximate; neither submission
nor a Unity acknowledgement proves visible onset. **Sub-second performance remains unverified** until
held-out audio and recorded browser output pass the release gate. The live readiness panel reports library and recognizer preparation status.

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
signs in the legacy compiler. The `--streaming` publisher instead uses dependency-addressed bodies,
neutral entries, retractions, and separate flowing/held-pose edges at both rates; `--limit` and
`--retry-failed` support resumable runs. A fixed skeleton snapshot prevents per-phrase proportion
changes. Rejected edges remain unavailable; verified neutral-rest fallbacks are explicitly labelled.
`GET /api/v1/live/readiness` reports the current library version, missing core/A–Z captures,
compiled transition count, and failures. The initial publication target is the documented 25 core
glosses plus A–Z; until those recordings exist, the panel truthfully reports an incomplete library
while known phrases remain available as previews. Set `VITE_LIVE_SIGNING=false` to hide live mode.

## Uploading motion captures

Open the **Capture** tab and select one or more combined Rokoko Studio **FBX** files containing body,
Smartglove, and all 52 ARKit facial channels. Choose the **Mixamo** skeleton and **60 fps** when
exporting; use one sign per file, up to 100 MB each. Keep **Use Clip start time as time zero** on,
and leave **Include reference pose** and **Extract root motion** off. Face capture must have been
recorded; selecting FBX cannot add missing facial animation.

The app inspects files sequentially and previews each recording. After entering both timestamps,
use **Upload capture** for one file or **Upload all ready captures** for the batch. Invalid or
incomplete drafts stay in the editor with a specific error. Files are saved in isolated upload
folders; replacing the same gloss/take keeps its library ID. Failed validation leaves no source
file or job behind.
For each selected file, enter the timestamps where the meaning-bearing sign starts and ends. The
Capture screen shows the derived `start`, `sign`, and `end` ranges before upload. Both boundaries
are required; captures without timestamps are rejected. These authored
boundaries let a first word play `start + sign`, a middle word play only `sign`, and a final word
play `sign + end`. A single sign plays all three phases. Boundaries snap to actual FBX animation
frames. Existing recordings can be inspected and edited through **Edit timestamps**; no re-upload
is needed unless the source FBX itself is wrong.
The filename determines the gloss and take number:

| Filename | Gloss | Take |
|---|---:|---:|
| `hello.fbx` | `HELLO` | 1 |
| `hello_01.fbx` | `HELLO` | 1 |
| `hello_02.fbx` | `HELLO` | 2 |
| `good_morning_03.fbx` | `GOOD_MORNING` | 3 |

The numeric suffix is optional. Use `_01`, `_02`, and so on only when keeping multiple takes of
the same sign. Uploading `hello.fbx` and `hello_01.fbx` targets the same take, so the later upload
replaces the earlier one.

Uploaded FBX sources, normalized motion JSON, and the local SQLite database live under
`backend/data/` and are
intentionally ignored by Git. The `.gitkeep` files preserve the required empty directories.

Captures are registered only through the Capture screen/API; copying an FBX directly into
`backend/data/uploads/` does not import it.

## Research validation

The separate [FBX/video validation toolkit](backend/VALIDATION.md) compares matched suit and
non-suit captures with an independent reference video. It checks pairing and provenance, produces
auditable 2D wrist-error scores, and runs the prespecified mixed-effects comparison. SPM1D,
functional agreement curves, and pilot power simulation are available as secondary research tools.
No superiority result is reported until real matched trials pass the documented quality checks.

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
| `backend/app/ingest/` | FBX parsing, normalized motion generation, segmentation, and blending |
| `backend/app/api/v1/` | Capture upload, sign library, clip serving, and text translation APIs |
| `frontend/` | Vite/React application and browser-side Unity frame player |
| `SignoraAvatarTracking/` | Active Unity avatar project and retargeting runtime |

## Retargeting paths

The active path is Rokoko combined FBX → normalized body/hand/face motion JSON → Signora Unity
runtime → the existing `SignoraNewAvatar.glb`.

The unused CSV-to-baked-rotation pipeline and its earlier Unity player have been removed.
Read-only compatibility remains for existing CSV-backed library recordings and their stored motion.
Your existing library and backups are retained until you replace those takes with FBX captures.

For offline sentence diagnostics, run `python tools/preview_sentence.py HELLO FATHER` from
`backend/`; it reads canonical recordings and their authored timestamps from the app library.
