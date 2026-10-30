# SignSure — project context for Claude

SignSure turns English text into Indian Sign Language (ISL) performances by a motion-captured
avatar in the browser, and contains a research toolkit that validates the motion capture against
video. Repository: `git@github.com:duveen2546R/Signora.git` (default branch `main`).

## On a new machine: set everything up first

When this repository is freshly cloned or pulled on a machine without `.venv/` or
`frontend/node_modules/`, set it up before doing anything else:

1. Run `./scripts/setup.sh` from the repository root (idempotent; `--live` also installs local
   speech recognition, `--skip-tests` skips the test run). It creates `.venv/` at the repository
   root, installs all backend, validation and video requirements, pre-downloads the RTMW/YOLOX pose
   models, runs `npm ci` in `frontend/`, creates the git-ignored `backend/data/` folders, and runs
   both test suites.
2. Requirements: Python 3.11+ (tested on 3.12), Node 20.19+ or 22.12+. Install missing tools with
   the platform's package manager (e.g. `brew install python@3.12 node`) and re-run the script.
3. Read the script's warnings and tell the user about anything Git cannot carry:
   - `SignoraAvatarTracking/WebBuild/` (Unity WebGL build, ~73 MB) is git-ignored and served through
     the `frontend/public/unity` symlink. Without it the avatar does not render; everything else
     works. Copy it from another machine or rebuild with Unity 6000.5.9f1 + WebGL Build Support.
   - `videos/*.mp4`, `backend/data/` (SQLite library, uploads, analyses), `backend/study/` are local
     only. The sign library must be re-imported through the Capture page on each fresh setup.
4. Confirm it works: backend `pytest` and frontend `npm test` pass (about 300 and 58 tests; 11
   backend tests skip by design, the slow simulation test needs `SIGNSURE_SLOW=1`), then start the
   app (below) and check `GET http://localhost:8000/api/v1/analyses/readiness` returns `ready: true`.

## Run

```bash
cd backend && ../.venv/bin/uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev            # http://localhost:5173, proxies /api to :8000
```

Tests: `cd backend && ../.venv/bin/python -m pytest -q`; `cd frontend && npm test`; lint with
`npm run lint` and `../.venv/bin/ruff check .`. Use the repository-root `.venv` everywhere (the
analysis worker subprocess inherits the interpreter that runs uvicorn, so that interpreter needs the
video requirements). `README.md` still mentions `backend/.venv`; either works if used consistently.

## Layout

- `backend/` — FastAPI (`app/main.py`), routers in `app/api/v1/` (`analysis`, `captures`, `live`,
  `rigs`, `signs`, `speech`, `translate`, `video`), services in `app/services/`, FBX/Rokoko ingest
  in `app/ingest/`, research validation in `app/validation/`, CLI tools in `tools/`, tests in
  `tests/`. Settings in `app/core/config.py` (env prefix `SIGNSURE_`).
- `frontend/` — React 19 + Vite + `react-unity-webgl`. Pages in `src/pages/` (Analysis, Capture,
  SignPage, Watch, Landing); API client `src/api/client.js`; tests `tests/*.test.js` (`node --test`).
- `SignoraAvatarTracking/` — Unity project for the avatar (`SignoraNewAvatar.glb`).
- `MotionCaptureFbx/` — source Rokoko captures (Mixamo skeleton, 60 fps); not auto-imported.
- `study/`, `reports/`, `research_notes/` — validation studies and research reports (markdown).
- `docs/architecture.md` — system architecture. `backend/VALIDATION.md` — validation protocols.

## Motion capture conventions

Rokoko Studio export: FBX, **Skeleton options = Mixamo**, **60 fps**, **Characters = 0** (export the
actor's own skeleton; never retarget onto a character), Use Clip start time as time zero **on**,
Include reference pose **off**, Extract root motion **off**, Use constant key reducer **off** for
validation exports. Mixamo naming on the actor skeleton was verified to give elbow angles identical
(0.000°) to Rokoko's Default naming; only naming differs. FBX loading (`app/validation/fbx_motion.py`)
runs ufbx 0.0.5 in a subprocess because of native lifetime crashes — keep that isolation. Supported
profiles: `mixamo_30`, `rokoko_mixamo_60`, `newton_30`, `blender_25`.

## Statistical validation (the active research work)

Goal: show that the suit FBX and a two-phone video measurement of **one** performance agree.
Entry points: Analysis page → *Statistical Equivalence — two views of one take*, or
`backend/tools/single_take_equivalence.py --front F.mp4 --oblique S.mp4 --fbx X.fbx --output DIR`.

Pipeline (`app/validation/`):
- `video_replicates.py` — RTMW whole-body keypoints (rtmlib, the DWPose-family model
  `rtmw-dw-x-l`) with 5 test-time augmentations; results cached per video hash.
- `multiview.py` — coarse sync by wrist-speed cross-correlation then geometric refinement
  (`refine_lag`, minimises moving-frame reprojection error), board-free self-calibration from body
  keypoints (multi-start over 20–90° yaw, bone-length constancy, 15% focal prior), DLT
  triangulation, 6 Hz zero-lag Butterworth, FBX-defined sign window (sustained ≥0.2 s above 5% of
  peak wrist speed), `rest_window` for the pre-sign hold, and `trim_glitches` (Rokoko exports can
  start/end on a frame snapping to a reference pose; impossible >8 m/s jumps at the ends are
  trimmed, inside the take they are refused).
- `angles3d.py` — nine upper-body angles (elbow flexion, shoulder elevation, shoulder abduction
  proxy and wrist deviation per side, plus trunk twist), each an unsigned angle between two segment
  vectors so it is frame-, scale- and handedness-invariant; computed identically for FBX and video.
  The hand point (`*_index` joint) is the centre of the index-to-pinky knuckles on both sides
  (`fbx_motion.knuckle_centre`, `video_replicates.KNUCKLES`; pose cache version 2). Head, neck and
  individual fingers are not tracked.
- `conditional_equivalence.py` — noise model from still frames (95% upper bound, adaptive
  stillness threshold) and TTA spread; parametric-bootstrap Monte Carlo of the whole chain incl.
  calibration refits; TOST decisions for RMS (primary), mean and whole-curve; replicate spm1d check.
- `single_take_job.py` — shared orchestration for CLI and worker (`single_take_report.json` + PNG).
- `equivalence_margins.json` — **pre-registered** ±15° RMS margin for all nine angles, the RMS
  primary claim, the fixed-sequence `testing_order` (trunk → shoulders → elbows → left wrist →
  right wrist; stop at the first group that fails; confirmed angles keep familywise error ≤ 5%;
  overall EQUIVALENT / PARTIALLY EQUIVALENT / first group's decision), and the `pre_sign_hold` offset rule (per-angle definition offset measured in the
  still hold before the sign, re-estimated in every Monte Carlo draw; raw RMS always reported).
  Change it only in a commit made before analysing a take, never after seeing results.
- `single_take_simulation.py` + `tools/simulate_conditional_equivalence.py` — synthetic two-view
  takes with known truth for type I error / power checks. Run long simulations as background jobs
  with at most ~5 parallel processes and `OMP_NUM_THREADS=1` (8 cores; oversubscription made runs
  3–4× slower).

Real data: `validationDataset/After/` (front 480p 30 fps, side 1080p 60 fps, FBX 60 fps; not
synchronised — the pipeline syncs them). Results go to `validationDataset/After/results*/`.
`validationDataset/Action/` (front 1080p 60 fps, side 480p 30 fps) has no still hold before the
sign, so the pre-registered protocol refuses it; its results (`results-exploratory-*`, script
`exploratory_variant.py`: offsets from the post-sign hold, fixed focal) are exploratory only.
The testing order and knuckle centre were chosen after both takes were seen, so applying them to
After and Action is exploratory too; they are confirmatory for later takes.
Without the offset rule its elbows failed purely on a ~11–13° rest offset (carrying angle vs. rigid
suit skeleton); that elbow result is therefore exploratory.

Findings to respect (details in `reports/Single take equivalence at 15 degrees.md` and
`reports/Single take equivalence method validity.md`):
- Frames within one take are autocorrelated (effective n ≈ 2–7); frame-level bootstrap/HAC tests
  gave 11–34% false equivalence. Inference is conditional on the performance with an externally
  estimated error model.
- RMS is the primary claim. It is computed after removing the Monte Carlo's systematic bias but
  keeps the noise-variance inflation, so its upper bound is conservative in both directions. The
  mean claim passes cancelling errors and under-covers; the whole-curve band needs ~1 px noise.
- At ±15°, a pass needs a true suit–video RMS of about 9° or less at ~3 px keypoint noise.
  Recording protocol matters most: second phone 70–90° to the side, measured intrinsics,
  stabilisation off, 60 fps, fast shutter, 1–2 s still holds before/after the sign, static pose
  and slow elbow bend for the definition offset.
- A pass means agreement with the video reference for that take only — not suit accuracy and not
  generalisation. Never word results as "proven" beyond that; the old forced-pass fTOST code was
  removed for this reason.

## Working conventions

- Match the surrounding code style: concise docstrings that explain *why*, `from __future__ import
  annotations`, `ValidationError` (from `app.validation.mixed_effects`) for user-facing failures.
- Add a regression test with every bug fix (see `tests/test_conditional_equivalence.py`).
- Keep research notes and reports as markdown in `research_notes/<title>/` and `reports/<title>.md`.
- Large or identifiable media (videos, Unity builds, runtime data) stay out of Git.
