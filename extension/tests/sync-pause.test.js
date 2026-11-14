/**
 * Sync and pause, end to end: the real vendored scheduler, the real MockAvatarAdapter, the real
 * `createYouTubeMedia` wrapper around a fake <video>, and plan units mapped exactly as main.js
 * maps them (`toScheduleUnits`), including units the backend is still composing. The avatar's
 * rate is set the way main.js sets it (`avatarRateFor`), and the fake <video> dispatches its own
 * pause/playing events, routed as main.js routes them.
 */
import assert from 'node:assert/strict'
import test, { mock } from 'node:test'
import YouTubeSignScheduler from '../vendor/YouTubeSignScheduler.js'
import { MockAvatarAdapter } from '../src/avatar/adapter.js'
import { createYouTubeMedia, videoEventToPlayerState } from '../src/media/youtube-media.js'
import { DEFAULTS, avatarRateFor, overrunPolicyFor } from '../src/config.js'
import { toScheduleUnits } from '../src/plan/progressive.js'

const FPS = 60

/** A plan unit as GET /video-plans returns it. `frames` sets its natural motion length. */
const READY = (id, startMs, endMs, frames = 120) => ({
  id, startMs, endMs, status: 'ready', motionAvailable: true, motionUrl: `/m/${id}`,
  text: `unit ${id}`, glosses: [`SIGN${id}`], frames,
})
const COMPOSING = (id, startMs, endMs, frames = 120) => ({
  ...READY(id, startMs, endMs, frames), status: 'pending', motionAvailable: false, motionUrl: null,
})

function harness(planUnits, { mode = 'sync-pause', rate = 1, planStatus = 'processing', avatar: custom } = {}) {
  const state = { t: 0 }
  const now = () => state.t
  const queued = []
  const video = {
    currentTime: 0,
    playbackRate: rate,
    paused: true,
    pause() { if (!this.paused) { this.paused = true; queued.push('pause') } },
    play() { if (this.paused) { this.paused = false; queued.push('playing') } return Promise.resolve() },
  }
  const media = createYouTubeMedia(video)
  const avatar = custom ?? new MockAvatarAdapter({ now })
  const launched = []
  const scheduler = new YouTubeSignScheduler({
    media,
    avatar,
    units: toScheduleUnits(planUnits, planStatus),
    now,
    overrunPolicy: overrunPolicyFor({ ...DEFAULTS, playbackMode: mode }),
    loadMotion: async (unit) => ({
      fps: FPS,
      frameCount: unit.frames,
      segments: [{ kind: 'sign', gloss: unit.glosses[0], startFrame: 0, endFrame: unit.frames, occurrenceIndex: 0 }],
    }),
    prepareMotion: (motion, unit, policy) => {
      avatar.setPlaybackRate(avatarRateFor(policy, media.getPlaybackRate()))
      launched.push({ id: unit.id, atMediaMs: Math.round(video.currentTime * 1000), wallMs: state.t, policy })
      return policy === 'sync-pause' ? motion
        : { ...motion, playbackTiming: { targetDurationMs: Math.max(250, unit.endMs - unit.startMs) } }
    },
  })

  function emit(name) {
    if (name === 'pause' && !media.isPausedByExtension()) media.noteExternalPause()
    const mapped = videoEventToPlayerState(name)
    if (mapped !== null) scheduler.setPlayerState(mapped)
  }
  const flush = () => { while (queued.length) emit(queued.shift()) }

  /** Advance wall and media clocks in 100 ms ticks, as the scheduler's interval would. */
  async function run(ms, step = 100) {
    for (let elapsed = 0; elapsed < ms; elapsed += step) {
      state.t += step
      if (!video.paused) video.currentTime += (step * video.playbackRate) / 1000
      scheduler.tick()
      await Promise.resolve()
      await Promise.resolve()
      flush()
    }
  }

  /** Run until `predicate()` holds, returning the wall time it took (fails after `limit`). */
  async function until(predicate, limit = 120000) {
    const started = state.t
    while (!predicate()) {
      if (state.t - started > limit) throw new Error('condition never became true')
      await run(100)
    }
    return state.t - started
  }

  /** The backend finished composing these units; main.js forwards each poll like this. */
  function compose(...ids) {
    for (const unit of planUnits) {
      if (ids.includes(unit.id)) Object.assign(unit, { status: 'ready', motionAvailable: true, motionUrl: `/m/${unit.id}` })
    }
    scheduler.updateUnits(toScheduleUnits(planUnits, planStatus))
  }

  function settle(id, status) {
    Object.assign(planUnits.find((unit) => unit.id === id), { status })
    scheduler.updateUnits(toScheduleUnits(planUnits, planStatus))
  }

  const user = {
    play() { video.play(); flush() },
    pause() { video.pause(); flush() },
    seek(seconds) { video.currentTime = seconds },
    rate(value) {
      video.playbackRate = value
      avatar.setPlaybackRate(avatarRateFor(scheduler.overrunPolicy, value))
    },
  }

  video.paused = false
  emit('playing')
  return { scheduler, avatar, media, video, launched, state, run, until, compose, settle, user }
}

const mediaMs = (h) => Math.round(h.video.currentTime * 1000)

test('1. pauses exactly at a caption boundary, even when a tick lands past it', async () => {
  // Ticks see 1000 ms and then 1100 ms; the boundary at 1050 ms lies between them.
  const h = harness([READY(1, 1050, 3000)])
  await h.until(() => h.video.paused)
  assert.equal(mediaMs(h), 1050, 'the video is put back on the boundary, never left beyond it')
  assert.equal(h.media.isPausedByExtension(), true, 'a Signora pause, not the viewer’s')
  assert.equal(h.scheduler.autoPaused, true)
  assert.equal(h.avatar.isPlaying(), true)
  await h.run(1000)
  assert.equal(mediaMs(h), 1050, 'the video does not move while the avatar signs')
})

test('1b. with the scheduler running, the pause is timed to the boundary itself', async () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout'] })
  try {
    const h = harness([READY(1, 1050, 3000)])
    h.scheduler.start()
    // Real clocks: media time advances continuously, timers fire when it is due.
    for (let ms = 0; ms < 1200 && !h.video.paused; ms += 5) {
      h.state.t += 5
      h.video.currentTime += 0.005
      mock.timers.tick(5)
    }
    assert.equal(h.video.paused, true)
    assert.ok(Math.abs(mediaMs(h) - 1050) <= 5, `paused at ${mediaMs(h)} ms, not up to a tick late`)
    h.scheduler.stop()
  } finally {
    mock.timers.reset()
  }
})

test('2. waits at the boundary for a unit that is still composing, showing buffering', async () => {
  const units = [COMPOSING(1, 1000, 2000)]
  const h = harness(units)
  await h.until(() => h.video.paused)
  assert.equal(mediaMs(h), 1000)
  assert.equal(h.scheduler.bufferingUnit?.id, 1, 'the overlay can say "Buffering next sign…"')
  assert.equal(h.avatar.isPlaying(), false)

  await h.run(8000) // composition takes far longer than the caption lasts
  assert.equal(h.video.paused, true, 'still held: the video never runs past the sign')
  assert.equal(mediaMs(h), 1000)
  assert.deepEqual(h.launched, [])

  h.compose(1)
  await h.run(100)
  assert.equal(h.scheduler.bufferingUnit, null)
  assert.equal(h.avatar.isPlaying(), true, 'signed as soon as it is composed')
  assert.equal(h.video.paused, true, 'and the video stays held while it is signed')
  await h.until(() => !h.video.paused)
  assert.equal(h.launched.length, 1)
})

test('3. plays the full sign at natural speed, not fitted to the caption', async () => {
  // 300 frames at 60 fps = 5 s of motion for a 1 s caption.
  const h = harness([READY(1, 1000, 2000, 300)])
  await h.until(() => h.avatar.isPlaying())
  assert.equal(h.avatar.snapshot().durationMs, 5000)
  assert.equal(h.avatar.snapshot().rate, 1, 'not time-scaled to the 1 s cue')
  const held = await h.until(() => !h.video.paused)
  assert.ok(held >= 5000 && held <= 5200, `video held ${held} ms for a 5000 ms sign`)
  assert.equal(h.avatar.isPlaying(), false)
  assert.equal(h.launched[0].policy, 'sync-pause')
})

test('4. resumes only after the avatar reports that it finished', async () => {
  // A Unity-like adapter: it is playing until the host page sends `finished`, however long.
  let playing = false
  const unity = {
    play: () => { playing = true },
    pause() {}, resume() {}, setPlaybackRate() {},
    resetToIdle: () => { playing = false },
    isPlaying: () => playing,
    finished: () => { playing = false },
  }
  const h = harness([READY(1, 1000, 2000), READY(2, 2500, 3500)], { avatar: unity })
  await h.until(() => h.video.paused)
  await h.run(30000)
  assert.equal(h.video.paused, true, 'no finished event yet: the video stays held')
  assert.equal(mediaMs(h), 1000)

  unity.finished()
  await h.run(100)
  assert.equal(h.video.paused, false, 'resumed on the finished event')
  assert.equal(h.scheduler.autoPaused, false)

  await h.until(() => h.video.paused)
  assert.equal(mediaMs(h), 2500, 'and the next unit is held at its own boundary')
})

test('5. at 2× the pause is decided on media time and the sign still plays at 1×', async () => {
  const h = harness([READY(1, 1050, 3000, 120), READY(2, 4000, 5000, 120)], { rate: 2 })
  await h.until(() => h.video.paused)
  assert.equal(mediaMs(h), 1050, 'reached sooner in wall time, paused on the same media time')
  assert.equal(h.launched[0].wallMs, 600, 'media reaches 1050 ms after ~525 ms of wall time')
  assert.equal(h.avatar.snapshot().rate, 1, 'natural motion speed during the hold')

  const held = await h.until(() => !h.video.paused)
  assert.ok(held >= 2000 && held <= 2200, `a 2000 ms sign held the video ${held} ms`)
  assert.equal(h.video.playbackRate, 2, 'resumed at the viewer’s speed')

  const before = mediaMs(h)
  await h.run(500)
  assert.equal(mediaMs(h) - before, 1000, 'and plays on at 2×')

  // A speed change during a hold never speeds the avatar up.
  await h.until(() => h.video.paused)
  h.user.rate(1.5)
  assert.equal(h.avatar.snapshot().rate, 1)
  assert.equal(mediaMs(h), 4000)
})

test('6. never skips a late unit, however short its caption', async () => {
  // At 2× one 100 ms tick moves media time 200 ms - more than this whole 150 ms caption.
  const units = [COMPOSING(1, 1000, 1150, 60), READY(2, 1150, 2000, 60)]
  const h = harness(units, { rate: 2 })
  await h.until(() => h.video.paused)
  assert.equal(mediaMs(h), 1000)
  await h.run(5000)
  assert.deepEqual(h.launched, [], 'unit 2 does not jump the queue while unit 1 is composing')

  h.compose(1)
  await h.until(() => h.launched.length === 1)
  assert.equal(h.launched[0].id, 1, 'the late unit is signed, not skipped')
  await h.until(() => h.launched.length === 2)
  assert.deepEqual(h.launched.map((l) => [l.id, l.atMediaMs]), [[1, 1000], [2, 1150]])
})

test('a unit that settles without motion releases the hold and playback continues', async () => {
  const units = [COMPOSING(1, 1000, 2000), READY(2, 3000, 4000, 60)]
  const h = harness(units)
  await h.until(() => h.video.paused)
  h.settle(1, 'unsupported')
  await h.run(100)
  assert.equal(h.video.paused, false, 'an unsignable caption does not hold the video')
  await h.until(() => h.launched.length === 1)
  assert.equal(h.launched[0].id, 2)
})

test('a plan that ends with units still pending stops waiting for them', async () => {
  const units = [COMPOSING(1, 1000, 2000)]
  const h = harness(units)
  await h.until(() => h.video.paused)
  h.scheduler.updateUnits(toScheduleUnits(units, 'failed'))
  await h.run(100)
  assert.equal(h.video.paused, false)
})

test('a viewer pressing play while a sign is buffering wins, and the sign plays if it arrives in time', async () => {
  const units = [COMPOSING(1, 1000, 4000, 60), READY(2, 6000, 7000, 60)]
  const h = harness(units)
  await h.until(() => h.video.paused)
  h.user.play()
  assert.equal(h.media.isPausedByExtension(), false)
  await h.run(1000)
  assert.equal(h.video.paused, false, 'not paused again for the same unit')
  h.compose(1)
  await h.run(100)
  assert.equal(h.avatar.isPlaying(), true, 'still signed inside its caption')
  assert.equal(h.video.paused, false)
  await h.until(() => h.video.paused)
  assert.equal(mediaMs(h), 6000, 'the next unit is held normally')
})

test('a viewer pause before a boundary is never turned into a Signora hold or auto-resumed', async () => {
  const h = harness([READY(1, 3000, 4000)])
  await h.run(1000)
  h.user.pause()
  await h.run(5000)
  assert.equal(h.video.paused, true)
  assert.equal(h.media.isPausedByExtension(), false)
  assert.equal(h.scheduler.autoPaused, false)
  assert.deepEqual(h.launched, [])
})

test('seeking while buffering releases the hold and waits at the next boundary instead', async () => {
  const units = [COMPOSING(1, 1000, 2000), READY(2, 10000, 11000, 60)]
  const h = harness(units)
  await h.until(() => h.video.paused)
  h.user.seek(8)
  await h.run(200)
  assert.equal(h.scheduler.autoPaused, false)
  assert.equal(h.video.paused, false)
  await h.until(() => h.video.paused)
  assert.equal(mediaMs(h), 10000)
  assert.equal(h.launched[0].id, 2)
})

test('buffering of the video itself before a boundary freezes nothing and skips nothing', async () => {
  const h = harness([READY(1, 2000, 3000)])
  await h.run(1000)
  h.video.paused = true // the network stalls; YouTube reports `waiting`
  h.scheduler.setPlayerState(videoEventToPlayerState('waiting'))
  await h.run(3000)
  h.video.paused = false
  h.scheduler.setPlayerState(videoEventToPlayerState('playing'))
  await h.until(() => h.launched.length === 1)
  assert.equal(h.launched[0].atMediaMs, 2000)
})

test('stop() (navigation, reload) never leaves the video held', async () => {
  const h = harness([COMPOSING(1, 1000, 2000)])
  await h.until(() => h.video.paused)
  h.scheduler.stop()
  assert.equal(h.video.paused, false)
})

test('play together is unchanged: never paused, a late unit plays only inside its own caption', async () => {
  const units = [COMPOSING(1, 1000, 3000, 240), COMPOSING(2, 4000, 5000, 60)]
  const h = harness(units, { mode: 'play-together', rate: 1 })
  await h.run(1500)
  h.compose(1)
  await h.run(100)
  assert.equal(h.avatar.isPlaying(), true, 'composed during its caption: signed, fitted to the cue')
  assert.equal(h.launched[0].policy, 'continue')
  await h.run(4000) // unit 2's caption passes while it is still composing
  h.compose(2)
  await h.run(1000)
  assert.equal(h.launched.length, 1, 'too late for its caption: skipped, as before')
  assert.equal(h.video.paused, false)
  assert.equal(h.scheduler.autoPaused, false)
})
