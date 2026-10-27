/**
 * Proves the progressive-attachment technique end to end: the real scheduler, constructed with
 * zero units, fed units one at a time by mutating its own public `units` array - exactly what
 * `main.js::pollPlanProgress` does - actually plays the first one before a "plan" is complete,
 * keeps composing later ones in the background, and reports buffering honestly in between.
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import YouTubeSignScheduler, { YT_STATE } from '../vendor/YouTubeSignScheduler.js'
import { MockAvatarAdapter } from '../src/avatar/adapter.js'
import { createYouTubeMedia } from '../src/media/youtube-media.js'
import { describeReadiness, diffNewlyReady, progressSummary } from '../src/plan/progressive.js'

function harness() {
  const state = { t: 0 }
  const now = () => state.t
  const video = {
    currentTime: 0, playbackRate: 1, paused: true,
    pause() { this.paused = true }, play() { this.paused = false; return Promise.resolve() },
  }
  const media = createYouTubeMedia(video)
  const avatar = new MockAvatarAdapter({ now })
  const scheduler = new YouTubeSignScheduler({
    media, avatar, units: [], // <-- exactly how main.js attaches before any unit is ready
    loadMotion: async (unit) => ({
      fps: 60, frameCount: unit.frames ?? 120,
      segments: [{ kind: 'sign', gloss: unit.glosses[0], startFrame: 0, endFrame: unit.frames ?? 120 }],
    }),
    now,
  })

  async function run(ms, { step = 100 } = {}) {
    for (let elapsed = 0; elapsed < ms; elapsed += step) {
      state.t += step
      if (!video.paused) video.currentTime += step / 1000
      scheduler.tick()
      await Promise.resolve(); await Promise.resolve()
    }
  }

  /** What main.js::pollPlanProgress does with one poll's response. */
  function applyPoll(allUnits, readyIds) {
    const diff = diffNewlyReady(allUnits, readyIds)
    if (diff.newlyReady.length) {
      scheduler.units.push(...diff.newlyReady)
      scheduler.units.sort((a, b) => a.startMs - b.startMs)
    }
    return diff.readyIds
  }

  return { scheduler, avatar, media, video, state, run, applyPoll }
}

const UNIT = (id, startMs, endMs, glosses, status = 'pending', motionAvailable = false) => ({
  id, startMs, endMs, glosses, status, motionAvailable, motionUrl: `/m/${id}`, text: `unit ${id}`,
})

test('the first unit plays as soon as it alone becomes ready, before any later unit exists', async () => {
  const h = harness()
  let readyIds = new Set()
  const allUnits = [
    UNIT(1, 0, 3000, ['HELLO']),
    UNIT(2, 4000, 7000, ['FATHER']),
    UNIT(3, 8000, 11000, ['NAMASTE']),
  ]

  h.video.paused = false
  h.scheduler.setPlayerState(YT_STATE.PLAYING)

  // Only unit 1 has resolved so far - 2 and 3 are still in the backend's queue.
  allUnits[0].status = 'literal-preview'; allUnits[0].motionAvailable = true
  readyIds = h.applyPoll(allUnits, readyIds)
  assert.deepEqual([...readyIds], [1])

  await h.run(500)
  assert.equal(h.avatar.isPlaying(), true, 'unit 1 played without waiting for units 2 or 3')
  assert.equal(h.avatar.snapshot().activeGloss, 'HELLO')
})

test('a unit that becomes ready after its caption window has fully passed is not played', async () => {
  const h = harness()
  let readyIds = new Set()
  const allUnits = [UNIT(1, 1000, 2000, ['HELLO'])]

  h.video.paused = false
  h.scheduler.setPlayerState(YT_STATE.PLAYING)
  await h.run(3000) // play straight past the unit's window while it is still unresolved

  allUnits[0].status = 'literal-preview'; allUnits[0].motionAvailable = true
  h.applyPoll(allUnits, readyIds)
  await h.run(300)
  assert.equal(h.avatar.isPlaying(), false, 'too late - the viewer has already moved on')
})

test('a unit that becomes ready while still inside its own window still plays', async () => {
  const h = harness()
  let readyIds = new Set()
  const allUnits = [UNIT(1, 0, 5000, ['HELLO'])]

  h.video.paused = false
  h.scheduler.setPlayerState(YT_STATE.PLAYING)
  await h.run(2000) // 2s into a 5s window, still unresolved - nothing has happened yet
  assert.equal(h.avatar.isPlaying(), false)

  allUnits[0].status = 'literal-preview'; allUnits[0].motionAvailable = true
  readyIds = h.applyPoll(allUnits, readyIds)
  await h.run(300)
  assert.equal(h.avatar.isPlaying(), true, 'composed just in time - still inside its own window')
})

test('composing later units in the background does not block or interrupt an already-playing one', async () => {
  const h = harness()
  let readyIds = new Set()
  const allUnits = [
    UNIT(1, 0, 3000, ['HELLO'], 'literal-preview', true),
    UNIT(2, 4000, 7000, ['FATHER']), // still pending
  ]
  h.video.paused = false
  h.scheduler.setPlayerState(YT_STATE.PLAYING)
  readyIds = h.applyPoll(allUnits, readyIds)

  await h.run(500)
  assert.equal(h.avatar.isPlaying(), true, 'unit 1 is playing')

  // Unit 2 resolves in the background mid-way through unit 1's performance.
  allUnits[1].status = 'literal-preview'; allUnits[1].motionAvailable = true
  h.applyPoll(allUnits, readyIds)
  assert.equal(h.avatar.snapshot().activeGloss, 'HELLO', 'unit 1 was not interrupted by unit 2 arriving')

  await h.run(4000)
  assert.equal(h.avatar.snapshot().activeGloss, 'FATHER', 'unit 2 played in its own turn')
})

test('describeReadiness reports buffering for the exact gap between unit 1 finishing and unit 2 composing', async () => {
  const h = harness()
  let readyIds = new Set()
  const allUnits = [
    UNIT(1, 0, 1000, ['HELLO'], 'literal-preview', true),
    UNIT(2, 1000, 4000, ['FATHER']), // slow to compose
  ]
  readyIds = h.applyPoll(allUnits, readyIds)
  h.video.paused = false
  h.scheduler.setPlayerState(YT_STATE.PLAYING)
  await h.run(1500) // now inside unit 2's window, still unresolved

  const readiness = describeReadiness(h.video.currentTime * 1000, allUnits, readyIds, 'processing')
  assert.equal(readiness.state, 'buffering-current')
  assert.equal(readiness.unit.id, 2)
})

test('progress summary reflects partial completion without ever reporting a false 0/N', async () => {
  const allUnits = [
    UNIT(1, 0, 1000, ['HELLO'], 'literal-preview', true),
    UNIT(2, 1000, 2000, ['FATHER']),
    UNIT(3, 2000, 3000, ['NAMASTE']),
  ]
  const { readyIds } = diffNewlyReady(allUnits, new Set())
  const summary = progressSummary(allUnits, readyIds)
  assert.deepEqual(summary, { total: 3, settled: 1, ready: 1 })
  assert.notEqual(summary.ready, 0)
})

test('playback rate still applies correctly to a unit inserted after attachment', async () => {
  const h = harness()
  let readyIds = new Set()
  const allUnits = [UNIT(1, 0, 9000, ['HELLO'], 'literal-preview', true, 240)]
  allUnits[0].frames = 240 // 4s of motion
  readyIds = h.applyPoll(allUnits, readyIds)

  h.video.paused = false
  h.scheduler.setPlayerState(YT_STATE.PLAYING)
  h.video.playbackRate = 2
  h.avatar.setPlaybackRate(h.media.getPlaybackRate())
  await h.run(2200)
  assert.equal(h.avatar.isPlaying(), false, 'the progressively-inserted unit still honours playback rate')
})
