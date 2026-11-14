/**
 * The two viewer-selectable playback modes, end to end through the real vendored scheduler, the
 * real MockAvatarAdapter and the real `createYouTubeMedia` wrapper. The fake <video> dispatches
 * its own pause/playing events the way a browser does, and they are routed exactly as main.js
 * routes them, so a pause the scheduler takes is observed the same way a viewer's pause is.
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import YouTubeSignScheduler, { YT_STATE } from '../vendor/YouTubeSignScheduler.js'
import { MockAvatarAdapter } from '../src/avatar/adapter.js'
import { createYouTubeMedia, videoEventToPlayerState } from '../src/media/youtube-media.js'
import { DEFAULTS, overrunPolicyFor, saveConfig, loadConfig, config } from '../src/config.js'
import { unitNotice } from '../src/overlay/overlay.js'

const UNIT = (id, startMs, endMs, extra = {}) => ({
  id, startMs, endMs, motionAvailable: true, motionUrl: `/m/${id}`,
  text: `unit ${id}`, glosses: ['HELLO'], ...extra,
})

/** `mode` is the overlay choice; the scheduler is configured the way main.js configures it. */
function harness(units, mode, { frames = 120 } = {}) {
  const state = { t: 0 }
  const now = () => state.t
  const queued = []
  const video = {
    currentTime: 0,
    playbackRate: 1,
    paused: true,
    pause() { if (!this.paused) { this.paused = true; queued.push('pause') } },
    play() { if (this.paused) { this.paused = false; queued.push('playing') } return Promise.resolve() },
  }
  const media = createYouTubeMedia(video)
  const avatar = new MockAvatarAdapter({ now })
  const prepared = []
  const scheduler = new YouTubeSignScheduler({
    media,
    avatar,
    units,
    now,
    overrunPolicy: overrunPolicyFor({ ...DEFAULTS, playbackMode: mode }),
    loadMotion: async (unit) => ({
      fps: 60,
      frameCount: unit.frames ?? frames,
      segments: [{ kind: 'sign', gloss: unit.glosses[0], startFrame: 0, endFrame: unit.frames ?? frames, occurrenceIndex: 0 }],
    }),
    prepareMotion: (motion, unit, policy) => {
      const value = policy === 'sync-pause' ? motion
        : { ...motion, playbackTiming: { targetDurationMs: Math.max(250, unit.endMs - unit.startMs) } }
      prepared.push({ policy, timed: Boolean(value.playbackTiming) })
      return value
    },
  })

  function emit(name) {
    if (name === 'pause' && !media.isPausedByExtension()) media.noteExternalPause()
    const mapped = videoEventToPlayerState(name)
    if (mapped !== null) scheduler.setPlayerState(mapped)
  }
  const flush = () => { while (queued.length) emit(queued.shift()) }

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

  /** The viewer's own controls. */
  const user = {
    play() { video.play(); flush() },
    pause() { video.pause(); flush() },
    seek(seconds) { video.currentTime = seconds },
    rate(value) { video.playbackRate = value; avatar.setPlaybackRate(value) },
  }

  video.paused = false
  emit('playing')
  return { scheduler, avatar, media, video, prepared, run, emit, user }
}

test('play together never pauses the video while the avatar signs', async () => {
  const h = harness([UNIT(1, 1000, 2000, { frames: 240 })], 'play-together')
  await h.run(1200)
  assert.equal(h.avatar.isPlaying(), true)
  await h.run(1500)
  assert.equal(h.video.paused, false)
  assert.equal(h.scheduler.autoPaused, false)
  assert.deepEqual(h.prepared, [{ policy: 'continue', timed: true }], 'motion fitted to its cue')
})

test('sync and pause holds the video for the whole sign and resumes after it', async () => {
  const h = harness([UNIT(1, 1000, 4000, { frames: 120 })], 'sync-pause')
  await h.run(1100)
  assert.equal(h.avatar.isPlaying(), true)
  assert.equal(h.video.paused, true, 'paused at the start of the sign, not at an overrun')
  assert.equal(h.media.isPausedByExtension(), true, 'attributed to Signora, not the viewer')
  assert.equal(h.avatar.snapshot().paused, false, 'the avatar keeps signing during its own hold')
  assert.deepEqual(h.prepared, [{ policy: 'sync-pause', timed: false }], 'natural motion pace')
  const heldAt = h.video.currentTime

  await h.run(1800)
  assert.equal(h.video.currentTime, heldAt, 'the video does not advance while held')
  await h.run(600)
  assert.equal(h.avatar.isPlaying(), false)
  assert.equal(h.video.paused, false, 'resumed after the sign')
  assert.equal(h.scheduler.autoPaused, false)
})

test('sync and pause also holds for a fingerspelled fallback unit', async () => {
  const unit = UNIT(1, 1000, 2000, { glosses: ['C', 'A', 'T'], fingerspelledWords: ['cat'], frames: 180 })
  const h = harness([unit], 'sync-pause')
  await h.run(1100)
  assert.equal(h.video.paused, true)
  await h.run(3200)
  assert.equal(h.video.paused, false)
})

test('switching mode during a sign applies at the next unit boundary', async () => {
  const units = [UNIT(1, 1000, 3000, { frames: 60 }), UNIT(2, 3000, 6000, { frames: 60 })]
  const h = harness(units, 'play-together')
  await h.run(1100)
  assert.equal(h.avatar.isPlaying(), true)
  h.scheduler.setOverrunPolicy(overrunPolicyFor({ ...DEFAULTS, playbackMode: 'sync-pause' }))
  await h.run(500)
  assert.equal(h.video.paused, false, 'the sign in progress is not held')
  await h.run(2000)
  assert.equal(h.scheduler.overrunPolicy, 'sync-pause')
  assert.equal(h.video.paused, true, 'the next sign is held')
  assert.equal(h.prepared.at(-1).policy, 'sync-pause')
  await h.run(1200)
  assert.equal(h.video.paused, false)
})

test('switching to play together mid-hold still releases the video', async () => {
  const h = harness([UNIT(1, 1000, 4000, { frames: 120 })], 'sync-pause')
  await h.run(1100)
  assert.equal(h.video.paused, true)
  h.scheduler.setOverrunPolicy(overrunPolicyFor({ ...DEFAULTS, playbackMode: 'play-together' }))
  await h.run(2500)
  assert.equal(h.video.paused, false)
  assert.equal(h.scheduler.overrunPolicy, 'continue')
})

for (const mode of ['play-together', 'sync-pause']) {
  test(`${mode}: a viewer pause before a sign is never auto-resumed`, async () => {
    const h = harness([UNIT(1, 3000, 6000)], mode)
    await h.run(500)
    h.user.pause()
    assert.equal(h.media.isPausedByExtension(), false)
    await h.run(4000)
    assert.equal(h.video.paused, true, 'stays paused by the viewer')
    assert.equal(h.avatar.isPlaying(), false)
  })

  test(`${mode}: a viewer pause mid-sign freezes the avatar and is never auto-resumed`, async () => {
    const h = harness([UNIT(1, 1000, 4000, { frames: 240 })], mode)
    await h.run(1100)
    if (mode === 'sync-pause') {
      // The viewer presses play to override the hold, then pauses themselves.
      h.user.play()
      assert.equal(h.scheduler.autoPaused, false)
    }
    h.user.pause()
    assert.equal(h.avatar.snapshot().paused, true)
    const before = h.avatar.snapshot().elapsedMs
    await h.run(6000)
    assert.equal(h.avatar.snapshot().elapsedMs, before)
    assert.equal(h.video.paused, true, 'never resumed by Signora')
    h.user.play()
    assert.equal(h.avatar.snapshot().paused, false)
  })

  test(`${mode}: seeking clears the sign and never leaves the video paused by Signora`, async () => {
    const h = harness([UNIT(1, 1000, 4000, { frames: 240 }), UNIT(2, 20000, 22000)], mode)
    await h.run(1100)
    h.user.seek(15)
    await h.run(200)
    assert.equal(h.avatar.isPlaying(), false, 'motion cleared')
    assert.equal(h.scheduler.autoPaused, false)
    assert.equal(h.video.paused, false)
    await h.run(5200)
    assert.equal(h.avatar.isPlaying(), true, 'the next unit after the seek still plays')
  })

  test(`${mode}: buffering freezes the avatar only outside a Signora hold`, async () => {
    const h = harness([UNIT(1, 1000, 4000, { frames: 240 })], mode)
    await h.run(1100)
    h.emit('waiting')
    assert.equal(h.avatar.snapshot().paused, mode === 'play-together')
    h.emit('playing')
    assert.equal(h.avatar.snapshot().paused, false)
  })

  test(`${mode}: a playback-rate change is not mistaken for a seek`, async () => {
    const h = harness([UNIT(1, 1000, 8000, { frames: 240 })], mode)
    await h.run(1100)
    h.user.rate(2)
    await h.run(500)
    assert.equal(h.avatar.isPlaying(), true, 'no resync')
  })
}

test('the mode is persisted in chrome.storage.sync and play together is the default', async () => {
  const store = {}
  globalThis.chrome = {
    storage: { sync: {
      get: async (key) => ({ [key]: store[key] }),
      set: async (value) => Object.assign(store, value),
    } },
  }
  try {
    assert.equal(DEFAULTS.playbackMode, 'play-together')
    assert.equal(overrunPolicyFor(DEFAULTS), 'continue', 'default preserves the existing behaviour')
    store.signora = { debug: true }
    await saveConfig({ playbackMode: 'sync-pause' })
    assert.deepEqual(store.signora, { debug: true, playbackMode: 'sync-pause' })
    await loadConfig()
    assert.equal(config().playbackMode, 'sync-pause')
    assert.equal(overrunPolicyFor(config()), 'sync-pause')
    assert.equal(overrunPolicyFor({ ...DEFAULTS, playbackMode: 'bogus' }), 'continue')
  } finally {
    await saveConfig({ playbackMode: 'play-together', debug: false })
    delete globalThis.chrome
  }
})

test('fallback and literal output are labelled honestly', () => {
  assert.match(unitNotice({ fingerspelledWords: ['cat'], unitStatus: 'literal-preview' }),
    /^Fingerspelling \(alphabet fallback, not a reviewed ISL sign\): cat$/)
  assert.match(unitNotice({ unitStatus: 'literal-preview' }), /not a reviewed ISL translation/)
  assert.equal(unitNotice({ unitStatus: 'ready' }), '')
})
