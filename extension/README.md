# Signora ISL Signing for YouTube — Chrome extension (MV3)

Plays Signora's recorded sign motion in sync with a YouTube video's English captions, using the
Signora backend that already exists in this repository.

This is an MVP toward the final goal. Read **[What actually works today](#what-actually-works-today)**
and **[Known limitations](#known-limitations)** before demoing it. The scheduling, caption, and
progressive-planning layers are complete, tested, and (per the latest round) confirmed working in
a real browser against the real backend. The Unity avatar connection is now fully implemented —
host page, message relay, origin-scoped protocol, all tested in Node — but has **not** been
click-tested by me in a live Chrome session; see [Unity handoff](#unity-handoff--implemented-needs-live-verification).

---

## Architecture and what is reused

Nothing in the caption→gloss pipeline was rebuilt. The extension is a thin host around the
existing backend and the existing scheduler.

| Concern | Where it lives | Status |
|---|---|---|
| Subtitle → timed units | `backend/app/services/subtitle_service.py` | reused unchanged |
| Phrase/word/fingerspell resolution, motion composition | `backend/app/services/video_plan_service.py` | reused unchanged |
| Plan + unit-motion HTTP API | `backend/app/api/v1/video.py` | reused unchanged |
| Play/pause/seek/prefetch/overrun scheduling | `frontend/src/video/YouTubeSignScheduler.js` | **reused byte-for-byte** |
| Caption discovery + JSON3/XML → VTT | `extension/src/captions/` | new |
| Progressive readiness (buffering, look-ahead) | `extension/src/plan/progressive.js` | new |
| `<video>` → scheduler media contract | `extension/src/media/youtube-media.js` | new |
| Avatar abstraction, mock, real Unity adapter | `extension/src/avatar/` | new |
| Unity avatar host page + message relay | `frontend/src/pages/AvatarHost.jsx`, `frontend/src/unity/avatarHostBridge.js` | new |
| Overlay UI | `extension/src/overlay/` | new |

### The scheduler is shared, not forked

An MV3 package cannot import from `frontend/src` at runtime, so the scheduler is physically copied
to `extension/vendor/YouTubeSignScheduler.js` by `extension/tools/sync-vendor.mjs`.
`extension/tests/vendor-sync.test.js` asserts the copy is **byte-identical** to the frontend
original, so "reuse" cannot silently decay into a second divergent implementation.

```bash
node extension/tools/sync-vendor.mjs          # resynchronise after editing the frontend file
node extension/tools/sync-vendor.mjs --check  # CI: fail on drift
```

The scheduler is used exactly as `Watch.jsx` uses it. Only `loadMotion` differs, because the
extension routes backend calls through its service worker.

### Why there is a build step

The sources under `src/` and `vendor/` are ES modules, but a manifest content script is a
**classic** script. The first version bootstrapped with
`import(chrome.runtime.getURL('src/main.js'))`; Chrome rejected that on a real YouTube page with:

```
Unsafe attempt to load URL chrome-extension://…/src/main.js
from frame with URL https://www.youtube.com/watch?v=…
Domains, protocols and ports must match.
```

A content script's module specifiers resolve against the **page** origin, and
`web_accessible_resources` does not change that. So `tools/build.mjs` concatenates the module
graph into one classic IIFE at `dist/content.bundle.js`, which is what the manifest loads.

The ES modules stay the single source of truth — `node --test` runs against them directly, and
`tests/bundle.test.js` evaluates the generated bundle the way Chrome does (in a `vm` context with
a page-like global) to prove it boots. **Re-run the builder after editing anything under `src/`
or `vendor/`:**

```bash
node extension/tools/build.mjs            # rebuild
node extension/tools/build.mjs --check    # CI: fail if the committed bundle is stale
```

`dist/content.bundle.js` is generated but **committed**, because Chrome loads it straight from the
unpacked folder. The repo's global `dist/` ignore rule is negated for exactly this one file.

### Why captions are *captured*, not fetched

Holding a caption track's published `baseUrl` is no longer enough. Verified from this repository:
a direct request for that URL — with session cookies and correct `Referer`/`Origin` — returns
**HTTP 200 with a zero-byte body** for all of `fmt=json3`, `fmt=srv3`, and the legacy XML form.
YouTube requires a proof-of-origin token that only its own player runtime mints.

So the extension does not try to out-argue YouTube for the bytes:

1. A `world: "MAIN"` content script (`src/page/bridge.js`) observes `fetch`/`XMLHttpRequest` at
   `document_start` and watches for `/api/timedtext`.
2. The extension asks the page's own player to select the English track, escalating because
   `setOption` alone is not reliable on a paused video that has never shown captions:
   `loadModule('captions')` + `setOption` immediately, the same again at ~0.6 s once the module
   has initialised, then an actual click on the player's CC button at ~1.6 s. Each step is
   skipped if a response has already been captured.
3. The player fetches its captions legitimately; the bridge reads that response and hands it to
   the isolated world over a narrow `postMessage` protocol.
4. A plain `baseUrl&fmt=json3` GET is still attempted as a cheap fallback, because it does work on
   some videos.
5. If all of that fails, the panel reports it **and keeps listening**. The moment the player does
   fetch timed text — most often because you press CC yourself — the extension picks it up and
   continues to the sign plan automatically, with no reload or Retry needed.

This reads only data YouTube is already rendering. Nothing is scraped from third parties and no
caption text is ever synthesised. If all paths fail, the overlay says so and offers a manual
subtitle file — see [Fallback](#fallback-when-youtube-will-not-release-captions).

### Why the overlay used to get stuck at "0/10" — the diagnosis

The overlay previously waited for `plan.status === 'ready'` before doing anything. On a real run
against the test video, that meant waiting for **all ten** caption units to finish composing
before the first one could play. Diagnosed directly against the live backend:

- Polling `GET /video-plans/{id}` **while `prepare_plan` ran in the background** showed unit 0
  reaching `motionAvailable: true` within 3 s, while `plan.status` stayed `"processing"` for
  minutes — the backend was already exposing partial progress; nothing needed to change there.
- Timing `compose_clips` directly for one of the ten units
  (`GOOD_MORNING → FATHER → THANKYOU → HELLO`, which gets rejected) measured **31.3 seconds** for
  that single unit. The backend's seam-search retries a grid of candidate transition frames when a
  direct blend is rejected, and that grid search is what's slow — not a hang, not a crash.
- A full synchronous replay of the exact 10-unit plan from your screenshot took **91.9 s** and
  reached `30% coverage` (3/10 playable). The two plan rows stuck at *"9/10 processed"* for 300+ s
  in your database most plausibly died mid-task because the backend process restarted — the
  project's own quick-start command (`uvicorn … --reload`) kills in-flight `BackgroundTasks` on
  any watched-file change, and `prepare_plan` writes its terminal `status` (`ready`/`failed`) only
  once at the very end, so an interrupted run is left reading `"processing"` forever with no error.
  **Start the backend without `--reload` while testing this extension** (the command in
  [Prerequisites](#prerequisites) already omits it).

So there were two separate problems, both fixed:

1. **Client-side (fixed below): stop waiting.** The backend's own per-unit commits were already
   there to use.
2. **Operational: don't run a ~90 s CPU-bound background job under an auto-reloading dev server.**
   Not an extension bug; documented as a prerequisite.

Optimising `compose.py`'s seam search itself is a separate, out-of-scope performance project — see
[Known limitations](#known-limitations).

### Progressive plan consumption

`extension/src/plan/progressive.js` is pure, dependency-free decision logic (no DOM, no scheduler,
no backend) that turns a sequence of polled plan snapshots into "what just became playable" and
"what should the overlay say right now." `extension/src/main.js` wires it to the real scheduler:

1. **POST** the VTT. The response already carries the *full* unit list — every `startMs`/`endMs`/
   `text`, for all units — before any composing has happened. That's enough to attach the
   scheduler immediately, constructed with `units: []`.
2. **Poll** `GET /video-plans/{id}` on an interval. Each response is diffed
   (`diffNewlyReady`) against the ids already known ready; anything newly `motionAvailable: true`
   is pushed into `scheduler.units` — a plain, public field, not the constructor argument the
   scheduler copied at construction — and the array is re-sorted by `startMs`.
3. **Playback never waits.** The moment the video's current time falls inside a unit that is in
   `scheduler.units`, the scheduler's own unchanged logic plays it — which can happen while 9 of
   10 units are still being composed in the background.
4. **Buffering is reported honestly, not silently.** `describeReadiness(mediaMs, allUnits,
   readyIds, planStatus)` compares the *current* video time against the *full* known unit list
   (not just the scheduler's ready-only view) and returns `'buffering-current'` when the viewer is
   already inside a caption window whose unit the backend hasn't finished composing, or
   `'buffering-lookahead'` when an upcoming unit (within `lookaheadUnits`, default 2) is still
   pending. A unit the backend has *already* rejected or declared unsupported is reported as
   `'unsignable'`, never `'buffering'` — that distinction matters: one is "it's coming," the other
   is "it already has a final, honest answer."
5. **Polling never gives up.** After `planTimeoutMs` (45 s) it slows to a 5 s cadence rather than
   stopping, because the backend has been measured legitimately taking longer than that.

One consequence worth knowing: because units are only ever inserted into `scheduler.units` once
they are *actually* ready, a unit that finishes composing only after its own caption window has
fully passed will not play — there is nothing left to deliver it on-time to. This was a deliberate
design choice (verified in `tests/progressive-integration.test.js`) over the alternative of
inserting not-yet-ready placeholder units up front, which would have made the scheduler's own
forward-skip logic permanently discard a unit the instant its window opened, even if composing
finished a moment later.

### Why the backend needed no CORS change

All backend requests are made from the **MV3 service worker** (`background.js`). A fetch from an
extension service worker whose host is in `host_permissions` is not subject to page CORS — the
extension origin is granted access directly.

Had the content script called the backend instead, requests would have carried
`Origin: https://www.youtube.com`, which would require adding that origin to
`backend/app/core/config.py::cors_origins` — weakening it for *every* website. So the content
script never talks to the backend; it asks the worker to. **`cors_origins` is unchanged.**

If you ever do need a different backend address, it is one field:
`DEFAULTS.apiBase` in `extension/src/config.js` (plus a matching `host_permissions` entry).
The backend side is already env-configurable without a code edit:
`SIGNSURE_CORS_ORIGINS='["http://localhost:5173"]'`.

---

## Prerequisites

1. **Backend running on port 8000 — without `--reload`:**

   ```bash
   cd backend
   python -m uvicorn app.main:app --port 8000
   ```

   **Do not add `--reload`** while testing this extension. See
   [Why the overlay used to get stuck at "0/10"](#why-the-overlay-used-to-get-stuck-at-010--the-diagnosis):
   a single caption unit's motion composition has been measured taking 30+ seconds, and `--reload`
   kills any in-flight background task on the next file-save, abandoning the plan at whatever
   point it had reached.

   Confirm: <http://127.0.0.1:8000/api/v1/health> returns `{"status":"ok", …}`.

2. **A populated sign library.** The 27 demo recordings and their reviewed Start→Sign→End
   timestamps must already be in `backend/data/signsure.db`. Check with:

   ```bash
   curl "http://127.0.0.1:8000/api/v1/signs?limit=50"
   ```

3. **Chrome 111+** (the manifest uses `content_scripts[].world`, added in 111).

4. **Frontend dev server on port 5173 — required for the default `'unity'` adapter:**

   ```bash
   cd frontend
   npm run dev
   ```

   This serves the real Signora avatar host page at `/signora-avatar`. If it is not running, or
   Unity fails to calibrate for any reason, the extension **automatically falls back to the mock
   adapter** and says so visibly in the overlay (`adapterName` changes to `mock (unity failed)`,
   and `detail` names the actual error) — it is never a silent fallback. To skip the frontend
   entirely and always use the mock avatar, set `avatarAdapter: 'mock'` in
   `extension/src/config.js` and rebuild.

---

## Load the unpacked extension

0. **Build the content-script bundle** (required; see [Why there is a build step](#why-there-is-a-build-step)):

   ```bash
   node extension/tools/build.mjs
   ```

   The repository ships an up-to-date `dist/content.bundle.js`, so this is only strictly necessary
   after you edit `src/` or `vendor/`. Running it is harmless and tells you if it was stale.

1. Open `chrome://extensions`.
2. Turn on **Developer mode** (top-right).
3. Click **Load unpacked**.
4. Select this folder:

   ```
   C:\Users\HP\OneDrive - SSN-Institute\Desktop\Signora-main\Signora-main\extension
   ```

5. Confirm "Signora ISL Signing for YouTube" appears with no errors.
6. Open a YouTube watch page. A **Signora** panel appears at the bottom-right.

To pick up code changes: `node extension/tools/build.mjs`, then press **Reload** (↻) on the
extension card, then reload the YouTube tab. Skipping the rebuild means Chrome keeps running the
previous bundle.

Useful logs: the extension card's **service worker** link (backend calls), and the YouTube tab's
DevTools console (filter `[signora]`). Set `debug: true` in `src/config.js` for verbose output.

---

## Test with the acceptance video

<https://www.youtube.com/watch?v=oK6LGQY_7A4>

This video (*"signora testing"*, 58 s) **does** expose an English caption track —
`languageCode: "en"`, `kind: "asr"` (auto-generated) — confirmed against the live page.

### Click-by-click

1. Confirm both servers are up: `curl http://127.0.0.1:8000/api/v1/health` and (for the real
   avatar) a browser tab open to `http://127.0.0.1:5173/signora-avatar` loads without a blank
   white screen.
2. Open <https://www.youtube.com/watch?v=oK6LGQY_7A4>. The **Signora** panel appears bottom-right
   within a second or two.
3. Watch the status line progress automatically — no clicks needed:
   - `Checking Signora backend…`
   - `Preparing captions…` — reports the cue count, format, and auto-generated/manual.
   - `Preparing sign plan…` — brief; this is only the POST itself now.
   - `Buffering next signs…` — the scheduler is already attached; this is normal while the
     backend composes in the background. **This should never sit at a literal "0/N" indefinitely**
     — if the current or next caption's unit is still pending, the panel names it.
4. Press **play** on the YouTube video. As soon as the *first* unit with composed motion is
   reached, status flips to `Signing`, with the current caption, ordered glosses, and the active
   sign highlighted — **even if later units are still composing** (watch the **Coverage** figures
   climb in the background as you keep watching).
5. If the real Unity avatar loaded, the panel shows the actual Signora avatar performing the
   sign. If it shows a black box with a bold gloss name instead, Unity did not load — the `detail`
   line explains why, and `Avatar mock` appears next to **Speed**.

### Behaviour to verify

| Action | Expected |
|---|---|
| **Play** | Avatar starts signing at the first caption unit that has composed motion, without waiting for the rest. |
| **Pause** (user) | Avatar freezes immediately. Status `Paused`. The video is **never** auto-resumed. |
| **Resume** | Avatar continues from exactly where it froze. |
| **Seek / scrub** | Status `Resynced after seek`; stale motion is dropped; a part-elapsed unit is skipped rather than restarted; a backwards scrub replays that unit; polling keeps feeding newly-ready units in afterwards. |
| **Speed change** (0.5×–2×) | Overlay's **Speed** updates and the avatar consumes motion at the new rate. |
| **Sign longer than its cue** | Status `Video paused while the sign finishes`; YouTube pauses; when the sign ends YouTube resumes **only because the extension paused it**. |
| **Mid-video, waiting on a slow unit** | Status `Buffering next signs…` with the actual upcoming caption text shown — never a frozen "0/10". |
| **Unsupported word** | Listed under **No sign for: …**. No substitute sign is ever played. |
| **Backend stopped** | Status `Signora backend unavailable` with the exact uvicorn command to start it. |
| **Download captions** | Click it any time after captions are found; saves the exact VTT sent to the backend. Never required for playback. |

The overrun path is easy to trigger here: composed motion routinely runs 2–4× its cue length
(measured: a 5 600 ms cue against 10 933 ms of motion), so YouTube pausing to let the avatar catch
up is the normal case with this library, not an edge case. Composing is also slow enough on this
hardware (one unit alone measured 31 s) that **buffering is the expected steady state** for at
least the first viewing of a video — watch the coverage figures climb as the background polling
keeps working.

### Fallback when YouTube will not release captions

Observed on this very video: with the video paused and CC off, the player never requested timed
text, so the panel showed `No English captions available`. Two things now handle that.

**Just press the CC button on the player.** The extension keeps listening after the failure, so
the moment YouTube fetches its captions the panel continues to the sign plan on its own. (The
bridge also tries to press that button for you at ~1.6 s.)

Otherwise, **Load subtitle file…** accepts a local `.srt`/`.vtt` — or a raw JSON3/XML dump, which
is converted first. Everything downstream is identical, so planning, scheduling, pause, seek,
speed, and overrun stay fully testable.

A ready-made file for the acceptance video is not checked in, because fabricating captions for a
real video is exactly what the task forbids. To make one from the real audio, use any local
transcription tool and save it as `.srt`.

---

## What actually works today

Verified by the commands in [Tests](#tests):

- **Caption conversion** — JSON3 and srv3/legacy XML → valid WebVTT. Rolling `aAppend` ASR
  duplicates dropped, missing/zero/overlapping durations repaired (the backend rejects an entire
  subtitle file on one non-positive cue), entities decoded, blank cues removed.
- **Backend reuse** — the converter's VTT is accepted by the real `POST /api/v1/video-plans`, the
  plan reaches `ready`, and unit motion is fetched over gzip.
- **Arbitrary unit length** — units of 4 and 5 glosses composed and played; nothing is capped at 3.
- **Repeated occurrences preserved** — `"again all age again"` composed to sign segments
  `AGAIN(occurrenceIndex 0) → ALL(1) → AGE(2) → AGAIN(3)`, as four separately timed performances.
- **Phrase-before-word matching** — `"hello father good morning"` resolved `GOOD_MORNING` as one
  two-word phrase rather than two words or fingerspelling.
- **Fingerspelling only when complete** — `"bend"` resolved to `B → E → N → D` because all four
  letters exist; a word needing any missing letter causes its unit to be reported, not guessed.
- **Honest unsupported reporting** — `"zebra quixotic"` produced `unsupported-unit`; no motion.
- **Scheduling** — the real scheduler driving the real mock adapter through a fake `<video>`:
  start-on-play, user-pause freeze with no auto-resume, catch-up pause + resume, forward and
  backward seek resync, speed change, buffering, 9 sequential units, skipped unavailable units,
  and recovery from a motion-load failure.
- **Mock avatar fidelity** — duration comes from the composed motion's real `frameCount / fps`
  (not a guess or a timeout), honours playback rate including mid-sign changes, and reports the
  active gloss from the backend's own `segments`. This is what makes every timing behaviour above
  testable without Unity.
- **Progressive plan consumption** — proven with the real scheduler, constructed with zero units
  and fed them one at a time: the first unit plays before a second one even exists; a unit that
  finishes composing while still inside its own caption window still plays; a unit that resolves
  only after its window has passed is correctly skipped (nothing left to deliver on time); a slow
  unit composing in the background never interrupts one already playing; and `progressSummary`
  never reports a false `0/N` once at least one unit is ready.
- **The real-browser capture/loader bugs found during manual testing are fixed and now guarded by
  tests** — `tests/bundle.test.js` evaluates the generated `dist/content.bundle.js` exactly as
  Chrome loads it (not just the ES module sources) specifically because the first loader passed
  every unit test and still did nothing on a real YouTube page.
- **Unity host page message relay** — `handleCommand` dispatches all six real `window.signsure`
  methods correctly, acknowledges the two commands `window.signsure` has no counterpart for
  (`setPlaybackRate`, `seek`) as a harmless no-op instead of throwing across the frame boundary,
  catches a method that throws and reports it on the ack, and the origin-scoping functions
  (`resolveParentOrigin`, `isTrustedMessageEvent`) reject anything but the real parent frame — no
  message is ever broadcast with a wildcard target.

---

## Known limitations

These are properties of the current recording library and backend policy, not extension bugs.

1. **Only 27 signs exist.** 23 words + the letters `B`, `E`, `N`, `D`. Any other word is
   unsupported.
2. **The A–Z alphabet is incomplete (4 of 26).** The backend's caption policy skips a *whole*
   caption unit if any word lacks a sign and fingerspelling is unavailable. One unknown word
   therefore discards the signable words grouped with it. Observed: a unit containing six
   signable words plus `"zebra quixotic"` was dropped entirely.
3. **12 of 27 recordings fail blend validation standalone.** Even with reviewed timestamps,
   `ADD, ADJECTIVE, ADVISE, ALWAYS, APPLY, APPOINTMENT, ASSUME, AWAY, B, E, N, THANKYOU` are
   rejected on their own with *"wrist speed exceeds the avatar limit"* — the reviewed Sign
   boundary marks where meaning starts, which need not be a posture the avatar can be delivered
   to from rest. They often **do** compose inside a longer sequence, where the seam is
   sign-to-sign rather than rest-to-sign (`THANKYOU B E N D` composed fine at 80% speed). Expect
   partial coverage, and expect it to vary with phrasing. Fixing this means re-reviewing those
   boundaries or re-recording — explicitly out of scope here.
4. **Motion is much longer than caption timing.** Sequences commonly run 2–4× their cue, so the
   video spends real time paused for catch-up.
5. **Composing a single unit can take 30+ seconds.** Measured directly: a 4-gloss sequence that
   gets rejected (`GOOD_MORNING → FATHER → THANKYOU → HELLO`) took 31.3 s to decide, because a
   rejected transition triggers a grid search over candidate seam frames. A 10-unit plan has been
   measured taking 92 s end-to-end. This is why plan consumption had to become progressive rather
   than fixed by polling faster — no polling interval makes a 92 s job finish in less than 92 s.
   Optimising `compose.py`'s seam search is a separate, out-of-scope performance project.
6. **Run the backend without `--reload` while testing.** A ~90 s background task dies silently if
   the dev server auto-restarts mid-run, leaving a plan permanently stuck in `"processing"` with
   no error — this is what produced the two orphaned rows diagnosed above, not an extension bug.
7. **`ADVICE` → `ADVISE`** is a registry alias (`isl_patterns.json`), not a separate recording.
   It inherits `ADVISE`'s standalone blend failure.
8. **Translations are literal previews, not reviewed ISL.** Every pattern is still
   `reviewStatus: "candidate"`; the backend labels output `literal-preview`.
9. **Enabling captions is visible.** Asking the player for its timed text turns YouTube's own CC
   on, so captions may appear on the video.
10. **Live streams are not supported** (no fixed caption timeline).
11. **No options page yet.** Settings live in `src/config.js`; `chrome.storage.sync` overrides are
   read but nothing writes them.
12. **The Unity relay's unsolicited pushes (`ready`, `sign`, `finished`) are origin-scoped to the
   *resolved* parent origin** (`location.ancestorOrigins[0]`, falling back to
   `https://www.youtube.com`), not to a wildcard — but this has not been confirmed inside an
   actual embedded iframe in a live browser; see
   [Unity handoff](#unity-handoff--implemented-needs-live-verification).

---

## Unity handoff — implemented, needs live verification

**`avatarAdapter: 'unity'` is now the default.** Everything described as "the smallest remaining
change" in the previous version of this document has been built:

| Piece | File | Status |
|---|---|---|
| Host page rendering the real avatar | `frontend/src/pages/AvatarHost.jsx` | built |
| Message relay (`cmd`/`ack`/`ready`/`event`) | `frontend/src/unity/avatarHostBridge.js` | built, **13 Node tests** |
| Route | `frontend/src/App.jsx` → `/signora-avatar` (no `Layout`, bare full-bleed canvas) | built |
| Extension-side adapter | `extension/src/avatar/unity-iframe.js` | unchanged, already matched the protocol |
| Non-silent fallback to mock | `extension/src/main.js::attachScheduler` catch block | unchanged, already correct |

Start it with `cd frontend && npm run dev` (see [Prerequisites](#prerequisites)). With that
running, loading the extension should show the real Signora avatar in the overlay's avatar panel
instead of the black mock box — `adapterName` in the overlay reads `unity`, not `mock`.

### What is verified, and how

- **The message relay logic** (`avatarHostBridge.js`) — dispatches all six real `window.signsure`
  methods, acks the two commands (`setPlaybackRate`, `seek`) that have no counterpart as a no-op
  instead of throwing, catches a throwing method and reports it on the ack rather than crashing
  the relay, and never responds to or receives from anything but the resolved parent origin.
  13 tests in `frontend/tests/avatarHostBridge.test.js`, run with plain `node --test` — no browser,
  no React, no Unity required.
- **The extension-side adapter's protocol** (`unity-iframe.js`) already targets `this.origin`
  (the host page's own resolved origin) for every outbound command and validates `event.origin`
  on every inbound message — this did not need to change; the host page's `avatarHostBridge.js`
  mirrors the same discipline for its side of the channel.
- **The CSP risk that broke the first content-script loader was specifically re-checked here.**
  Fetched youtube.com's actual response headers: none of its three `Content-Security-Policy`
  values declare `frame-src`, `child-src`, or `default-src`, so there is no CSP restriction on the
  page embedding an iframe pointing at `http://127.0.0.1:5173`. (`X-Frame-Options: SAMEORIGIN`
  governs who may frame *youtube.com*, not what youtube.com may frame — irrelevant here.)
  `127.0.0.1`/`localhost` are also Chrome's standard "potentially trustworthy" exception to
  mixed-content blocking on an `https://` page, which is already proven in practice: the
  extension's existing `https://www.youtube.com` → `http://127.0.0.1:8000` backend calls work in
  your own screenshots.
- **The Unity WebGL build itself exists and is complete** in this working tree
  (`SignoraAvatarTracking/WebBuild/Build/WebBuild.wasm`, 42 MB; `WebBuild.data`, 17 MB), linked via
  `frontend/public/unity`.

### What is *not* verified — honestly

I cannot drive a real Chrome browser from this environment. I have not personally:

- loaded the extension and watched the iframe actually request and render
  `http://127.0.0.1:5173/signora-avatar` inside a live youtube.com tab,
- watched Unity's WebGL build load and `SignoraAvatarDriver` reach a `complete`/`body-only`
  calibration state inside that iframe,
- measured the e2e postMessage round trip for an incoming `play` command or an outgoing
  `finished` event against real Unity frame timing.

That last point matters specifically for the overrun behaviour this whole task is about:
`isPlaying()` must flip to `false` exactly when composed motion ends, because that is what the
scheduler's catch-up pause/resume is timed against. Across a frame boundary that transition
arrives asynchronously, as the host page's `finished` event — and until that round trip is
measured against real Unity playback, its timing is unproven in a way no amount of Node testing
can close. The mock adapter has no such gap, which is why `attachScheduler`'s fallback to it,
on any Unity failure, is unconditional and visible rather than silent.

**If you run it and Unity does not calibrate:** open DevTools on the extension's service worker
and on the YouTube tab (filter `[signora]`); also open
`http://127.0.0.1:5173/signora-avatar` directly in a normal tab — if the avatar does not calibrate
there either, the fault is in the Unity build/calibration path itself, not the extension's relay.

---

## Tests

```bash
# Extension: caption conversion, media/event mapping, mock avatar, progressive plan logic,
# progressive attachment proven against the real scheduler end-to-end through a fake <video>,
# and the generated bundle evaluated as Chrome loads it.
cd extension && node --test            # 78 tests

# Frontend: original component/scheduler suite (unchanged) plus the Unity host's message relay.
cd frontend && node --test             # 75 tests

# Generated bundle matches the sources; scheduler copy has not drifted from the frontend.
node extension/tools/build.mjs --check
node extension/tools/sync-vendor.mjs --check
```

| File | What it proves |
|---|---|
| `extension/tests/convert.test.js` | JSON3/XML → VTT, including the rolling-duplicate and bad-duration repairs |
| `extension/tests/media.test.js` | `<video>` event → `YT_STATE` mapping, pause attribution |
| `extension/tests/avatar.test.js` | `MockAvatarAdapter` timing fidelity against an injected clock |
| `extension/tests/progressive.test.js` | the pure readiness/buffering/diff logic in `src/plan/progressive.js` |
| `extension/tests/progressive-integration.test.js` | the real scheduler + mock adapter, fed units one at a time exactly as `main.js` does — first unit plays before the rest exist, a late unit is correctly skipped or correctly still played depending on timing, background composition never interrupts an active sign |
| `extension/tests/integration.test.js` | the original full scheduler behaviour: pause/resume/seek/speed/overrun/skip/recovery |
| `extension/tests/bundle.test.js` | the **generated bundle**, evaluated in a `vm` context the way Chrome loads it — exists because the first loader passed every ES-module test and still did nothing in a real browser |
| `extension/tests/vendor-sync.test.js` | the vendored scheduler has not drifted from the frontend original |
| `frontend/tests/avatarHostBridge.test.js` | the Unity host page's message relay: command dispatch, no-op handling of unsupported commands, error containment, origin resolution and validation |

Backend tests are unaffected by this work; `backend/app/services/isl_patterns.json` remains the
only backend file touched across this whole feature, and it was not changed by this round.
`trainer/` and every reviewed Start/Sign/End timestamp are untouched — confirmed by re-reading the
database before and after this round of changes.

---

## File map

```
extension/
  manifest.json                      MV3; two content scripts (MAIN bridge + ISOLATED bundle)
  background.js                      service worker; ALL backend I/O (this is what avoids CORS changes)
  dist/content.bundle.js             GENERATED by tools/build.mjs; what Chrome actually runs
  package.json                       build / test / sync-vendor scripts
  src/
    config.js                        single config module (apiBase, avatarAdapter default 'unity', flags)
    main.js                          orchestrator: captions -> progressive plan -> scheduler -> overlay
    plan/progressive.js              pure readiness/buffering/diff logic (no DOM, no scheduler)
    captions/
      convert.js                     JSON3 + srv3/XML -> WebVTT (pure, heavily tested)
      discover.js                    page bridge client + 3-strategy caption discovery
    page/bridge.js                   MAIN world: observes the player's own timedtext request
    media/youtube-media.js           <video> -> scheduler media contract; event -> YT_STATE
    avatar/
      adapter.js                     AvatarAdapter interface + MockAvatarAdapter
      unity-iframe.js                real Unity adapter; falls back to mock visibly on failure
    overlay/overlay.js               shadow-DOM bottom-right panel (+ download-captions button)
  vendor/YouTubeSignScheduler.js     byte-identical copy of the frontend scheduler
  tools/
    build.mjs                        ESM graph -> one classic IIFE (+ --check staleness guard)
    sync-vendor.mjs                  copy + --check drift guard
  tests/                             convert, media, avatar, progressive, progressive-integration,
                                      integration, bundle, vendor-sync

frontend/src/
  pages/AvatarHost.jsx               Unity avatar host page, embedded as an iframe by the extension
  unity/avatarHostBridge.js          pure message-relay logic the host page delegates to
frontend/tests/avatarHostBridge.test.js
```
