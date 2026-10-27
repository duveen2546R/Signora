/**
 * The real, unmodified YouTubeSignScheduler driving the real MockAvatarAdapter through a fake
 * <video>. This is the test that proves the extension's reuse is sound: if the scheduler and the
 * adapter disagree about when motion finishes, the catch-up pause and resume break here.
 *
 * `createYouTubeMedia` is given a plain object with the same surface as an HTMLVideoElement, so
 * no DOM is required.
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import YouTubeSignScheduler, { YT_STATE } from '../vendor/YouTubeSignScheduler.js'
import { MockAvatarAdapter } from '../src/avatar/adapter.js'
import { createYouTubeMedia, videoEventToPlayerState } from '../src/media/youtube-media.js'

/** One unit per entry; `frames` sets how long its composed motion runs (60 fps). */
function harness(units, { frames = 120 } = {}) {
  const state = { t: 0 }
  const now = () => state.t

  const video = {
    currentTime: 0,
    playbackRate: 1,
    paused: true,
    ended: false,
    events: [],
    pause() { this.paused = true; this.events.push('pause') },
    play() { this.paused = false; this.events.push('play'); return Promise.resolve() },
  }
  const media = createYouTubeMedia(video)
  const avatar = new MockAvatarAdapter({ now })
  const sync = []

  const scheduler = new YouTubeSignScheduler({
    media,
    avatar,
    units,
    loadMotion: async (unit) => ({
      fps: 60,
      frameCount: unit.frames ?? frames,
      segments: [{ kind: 'sign', gloss: unit.glosses?.[0] ?? 'X', startFrame: 0, endFrame: unit.frames ?? frames, occurrenceIndex: 0 }],
    }),
    onSync: (message) => sync.push(message),
    now,
  })

  /** Advance wall clock and media clock together, ticking as the scheduler's interval would. */
  async function run(ms, { playing = true, step = 100 } = {}) {
    for (let elapsed = 0; elapsed < ms; elapsed += step) {
      state.t += step
      if (playing && !video.paused) video.currentTime += (step * video.playbackRate) / 1000
      scheduler.tick()
      await Promise.resolve()
      await Promise.resolve()
    }
  }

  /** Mirror main.js's event wiring. */
  function emit(name) {
    const mapped = videoEventToPlayerState(name)
    if (name === 'pause' && !media.isPausedByExtension()) media.noteExternalPause()
    if (mapped !== null) scheduler.setPlayerState(mapped)
  }

  function seekTo(seconds) {
    video.currentTime = seconds
    // `seeked` is intentionally not forwarded; the scheduler detects the jump itself.
  }

  return { scheduler, avatar, media, video, sync, state, run, emit, seekTo }
}

const UNIT = (id, startMs, endMs, extra = {}) => ({
  id, startMs, endMs, motionAvailable: true, motionUrl: `/m/${id}`,
  text: `unit ${id}`, glosses: ['HELLO'], ...extra,
})

test('starts the avatar when the video reaches a unit', async () => {
  const h = harness([UNIT(1, 1000, 4000)])
  h.video.paused = false
  h.emit('playing')
  await h.run(1200)
  assert.equal(h.avatar.isPlaying(), true)
  assert.equal(h.avatar.snapshot().activeGloss, 'HELLO')
})

test('a user pause freezes the avatar and never pauses or resumes the video', async () => {
  const h = harness([UNIT(1, 1000, 4000)])
  h.video.paused = false
  h.emit('playing')
  await h.run(1200)
  assert.equal(h.avatar.isPlaying(), true)

  h.video.pause()
  h.emit('pause')
  assert.equal(h.avatar.snapshot().paused, true, 'avatar freezes with the video')

  const before = h.avatar.snapshot().elapsedMs
  await h.run(3000, { playing: false })
  assert.equal(h.avatar.snapshot().elapsedMs, before, 'no avatar progress while the user is paused')
  assert.equal(h.video.events.filter((e) => e === 'play').length, 0, 'never auto-resumed')

  h.video.play()
  h.emit('playing')
  assert.equal(h.avatar.snapshot().paused, false, 'avatar resumes with the video')
})

test('pauses YouTube when a sign overruns its cue, then resumes only because it paused it', async () => {
  // 4 s of motion inside a 1 s cue.
  const h = harness([UNIT(1, 1000, 2000, { frames: 240 })])
  h.video.paused = false
  h.emit('playing')
  await h.run(1200)
  assert.equal(h.avatar.isPlaying(), true)

  await h.run(1200)              // run past the cue's end
  assert.equal(h.scheduler.autoPaused, true, 'scheduler took the catch-up pause')
  assert.equal(h.video.paused, true)
  assert.equal(h.media.isPausedByExtension(), true, 'attributed to the extension, not the user')

  // The avatar keeps performing while the video waits.
  await h.run(4000, { playing: false })
  assert.equal(h.avatar.isPlaying(), false, 'sign finished')
  assert.ok(h.video.events.includes('play'), 'video resumed once the sign finished')
  assert.equal(h.scheduler.autoPaused, false)
})

test('a seek resyncs, clears motion and skips a part-elapsed unit', async () => {
  const h = harness([UNIT(1, 1000, 4000), UNIT(2, 6000, 9000)])
  h.video.paused = false
  h.emit('playing')
  await h.run(1200)
  assert.equal(h.avatar.isPlaying(), true)

  h.seekTo(7.5)                  // jump into the middle of unit 2
  h.scheduler.tick()
  await Promise.resolve()

  assert.ok(h.sync.some((m) => m.includes('Resynced')), 'resync reported')
  assert.equal(h.avatar.isPlaying(), false, 'stale motion cleared')
  assert.equal(h.scheduler.index, 2, 'the part-elapsed unit is skipped, not restarted')
})

test('a backwards seek replays a unit from its start', async () => {
  const h = harness([UNIT(1, 1000, 4000), UNIT(2, 6000, 9000)])
  h.video.paused = false
  h.emit('playing')
  await h.run(6200)              // past unit 1, into unit 2

  h.seekTo(1.0)                  // scrub back to unit 1
  h.scheduler.tick()
  await Promise.resolve()
  assert.equal(h.scheduler.index, 0, 'rewound to unit 1')

  await h.run(400)
  assert.equal(h.avatar.isPlaying(), true, 'unit 1 plays again after the rewind')
})

test('a playback-speed change is applied to the avatar', async () => {
  const h = harness([UNIT(1, 1000, 9000, { frames: 240 })])   // 4 s of motion
  h.video.paused = false
  h.emit('playing')
  await h.run(1200)

  h.video.playbackRate = 2
  h.avatar.setPlaybackRate(h.media.getPlaybackRate())          // what main.js does on ratechange
  assert.equal(h.avatar.snapshot().rate, 2)

  await h.run(2200)                                            // ~2 s wall at 2x drains ~4 s
  assert.equal(h.avatar.isPlaying(), false, 'the sign finished early at double speed')
})

test('buffering freezes the avatar without pausing the video', async () => {
  const h = harness([UNIT(1, 1000, 9000, { frames: 240 })])
  h.video.paused = false
  h.emit('playing')
  await h.run(1200)
  h.emit('waiting')
  assert.equal(h.avatar.snapshot().paused, true)
  assert.equal(h.video.events.filter((e) => e === 'pause').length, 0)
})

test('plays an arbitrary number of units in order, not just three', async () => {
  const units = Array.from({ length: 9 }, (_, i) => UNIT(i + 1, 1000 + i * 2000, 2800 + i * 2000, {
    glosses: [`G${i + 1}`], frames: 60,
  }))
  const h = harness(units)
  h.video.paused = false
  h.emit('playing')

  const seen = []
  for (let i = 0; i < 9; i += 1) {
    await h.run(2000)
    const gloss = h.avatar.snapshot().activeGloss
    if (gloss && !seen.includes(gloss)) seen.push(gloss)
  }
  assert.ok(seen.length >= 7, `expected most of 9 units to play, saw ${seen.length}: ${seen}`)
  assert.deepEqual(seen, [...seen].sort((a, b) => Number(a.slice(1)) - Number(b.slice(1))), 'in order')
})

test('a unit with no composed motion is skipped without stalling the queue', async () => {
  const h = harness([
    { id: 1, startMs: 1000, endMs: 2000, motionAvailable: false, text: 'skip', glosses: ['B'] },
    UNIT(2, 3000, 6000, { glosses: ['FATHER'], frames: 60 }),
  ])
  h.video.paused = false
  h.emit('playing')
  await h.run(1500)
  assert.equal(h.avatar.isPlaying(), false, 'nothing played for the unavailable unit')
  await h.run(2000)
  assert.equal(h.avatar.snapshot().activeGloss, 'FATHER', 'the next playable unit still runs')
})

test('a motion load failure is reported and does not wedge the scheduler', async () => {
  const h = harness([UNIT(1, 1000, 4000), UNIT(2, 5000, 8000, { glosses: ['FATHER'], frames: 60 })])
  h.scheduler.loadMotion = async (unit) => {
    if (unit.id === 1) throw new Error('backend down')
    return { fps: 60, frameCount: 60, segments: [{ kind: 'sign', gloss: 'FATHER', startFrame: 0, endFrame: 60 }] }
  }
  h.video.paused = false
  h.emit('playing')
  await h.run(1400)
  assert.ok(h.sync.some((m) => m.includes('Motion unavailable')), 'failure surfaced')
  await h.run(4000)
  assert.equal(h.avatar.snapshot().activeGloss, 'FATHER', 'recovered on the next unit')
})

test('reaching the end of the video leaves the avatar idle', async () => {
  const h = harness([UNIT(1, 1000, 2000, { frames: 60 })])
  h.video.paused = false
  h.emit('playing')
  await h.run(2500)
  h.video.ended = true
  h.emit('ended')
  await h.run(300, { playing: false })
  assert.equal(h.avatar.isPlaying(), false)
})
