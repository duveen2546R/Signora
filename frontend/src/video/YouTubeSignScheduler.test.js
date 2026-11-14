import assert from 'node:assert/strict'
import test from 'node:test'
import YouTubeSignScheduler, { YT_STATE } from './YouTubeSignScheduler.js'

function setup() {
  let time = 0
  let playing = false
  const calls = []
  const media = {
    getCurrentTime: () => time / 1000,
    getPlaybackRate: () => 1,
    pauseVideo: () => calls.push('pause-video'),
    playVideo: () => calls.push('play-video'),
  }
  const avatar = {
    play: () => { playing = true; calls.push('play-sign') },
    pause: () => calls.push('pause-sign'),
    resume: () => calls.push('resume-sign'),
    resetToIdle: () => { playing = false; calls.push('reset') },
    isPlaying: () => playing,
  }
  const units = [{ id: 1, startMs: 1000, endMs: 2000, motionAvailable: true, motionUrl: '/one' }]
  const scheduler = new YouTubeSignScheduler({
    media, avatar, units, loadMotion: async () => ({ fps: 60 }), now: () => time,
  })
  return { scheduler, calls, setTime: (value) => { time = value }, finish: () => { playing = false } }
}

test('starts a prepared sign at its subtitle boundary', async () => {
  const value = setup()
  value.scheduler.setPlayerState(YT_STATE.PLAYING)
  value.setTime(1100)
  value.scheduler.tick()
  await Promise.resolve()
  assert.ok(value.calls.includes('play-sign'))
})

test('pauses video for catch-up and resumes only after the sign finishes', async () => {
  const value = setup()
  value.scheduler.setPlayerState(YT_STATE.PLAYING)
  value.setTime(1100)
  value.scheduler.tick()
  await Promise.resolve()
  value.setTime(2000)
  value.scheduler.tick()
  assert.ok(value.calls.includes('pause-video'))
  value.finish()
  value.scheduler.tick()
  assert.ok(value.calls.includes('play-video'))
})

test('continuous cue pacing never pauses the video for a sign overrun', async () => {
  const value = setup()
  value.scheduler.overrunPolicy = 'continue'
  value.scheduler.setPlayerState(YT_STATE.PLAYING)
  value.setTime(1100)
  value.scheduler.tick()
  await Promise.resolve()
  value.setTime(2500)
  value.scheduler.tick()
  assert.equal(value.calls.includes('pause-video'), false)
})

test('a seek clears motion and skips a partially elapsed unit', () => {
  const value = setup()
  value.scheduler.setPlayerState(YT_STATE.PAUSED)
  value.setTime(1500)
  value.scheduler.tick()
  assert.ok(value.calls.includes('reset'))
  assert.equal(value.scheduler.index, 1)
})

test('a user pause freezes the avatar and is never converted into auto-resume', async () => {
  const value = setup()
  value.scheduler.setPlayerState(YT_STATE.PLAYING)
  value.setTime(1100)
  value.scheduler.tick()
  await Promise.resolve()
  value.scheduler.setPlayerState(YT_STATE.PAUSED)
  value.setTime(2100)
  value.scheduler.tick()
  assert.ok(value.calls.includes('pause-sign'))
  assert.equal(value.calls.includes('pause-video'), false)
})

test('an advertisement freezes the current sign and never schedules lesson motion on the ad clock', async () => {
  const value = setup()
  value.scheduler.setPlayerState(YT_STATE.PLAYING)
  value.scheduler.setExternalPause(true)
  value.setTime(1100)
  value.scheduler.tick()
  await Promise.resolve()
  assert.ok(value.calls.includes('pause-sign'))
  assert.equal(value.calls.includes('play-sign'), false)

  value.scheduler.setExternalPause(false)
  assert.ok(value.calls.includes('resume-sign'))
  value.scheduler.tick()
  await Promise.resolve()
  assert.ok(value.calls.includes('play-sign'), 'the lesson resumes only after the ad ends')
})

async function startSign(value, policy) {
  value.scheduler.overrunPolicy = policy
  value.scheduler.setPlayerState(YT_STATE.PLAYING)
  value.setTime(1100)
  value.scheduler.tick()
  await Promise.resolve()
  await Promise.resolve()
}

test('sync-pause holds the video for the whole sign and resumes it when the avatar finishes', async () => {
  const value = setup()
  await startSign(value, 'sync-pause')
  assert.ok(value.calls.includes('pause-video'), 'paused as soon as the sign starts, not at overrun')
  assert.equal(value.scheduler.autoPaused, true)
  value.scheduler.setPlayerState(YT_STATE.PAUSED)
  assert.equal(value.calls.includes('pause-sign'), false, 'its own pause never freezes the avatar')
  value.finish()
  value.scheduler.tick()
  assert.equal(value.calls.filter((call) => call === 'play-video').length, 1)
  assert.equal(value.scheduler.autoPaused, false)
})

test('continue never pauses the video while the avatar signs', async () => {
  const value = setup()
  await startSign(value, 'continue')
  value.setTime(1900)
  value.scheduler.tick()
  assert.equal(value.calls.includes('pause-video'), false)
})

test('the overrun policy only changes at a unit boundary', async () => {
  const value = setup()
  await startSign(value, 'continue')
  value.scheduler.setOverrunPolicy('sync-pause')
  assert.equal(value.scheduler.overrunPolicy, 'continue', 'the sign in progress keeps its policy')
  value.setTime(1200)
  value.scheduler.tick()
  assert.equal(value.calls.includes('pause-video'), false)
  value.finish()
  value.scheduler.tick()
  assert.equal(value.scheduler.overrunPolicy, 'sync-pause')
  assert.throws(() => value.scheduler.setOverrunPolicy('bogus'))
})

test('switching to continue mid-hold still resumes the video when the sign ends', async () => {
  const value = setup()
  await startSign(value, 'sync-pause')
  value.scheduler.setOverrunPolicy('continue')
  value.finish()
  value.scheduler.tick()
  assert.ok(value.calls.includes('play-video'))
  assert.equal(value.scheduler.overrunPolicy, 'continue')
})

test('a viewer pressing play during a sync hold wins and is not paused again', async () => {
  const value = setup()
  await startSign(value, 'sync-pause')
  value.scheduler.setPlayerState(YT_STATE.PLAYING)
  assert.equal(value.scheduler.autoPaused, false)
  value.setTime(1300)
  value.scheduler.tick()
  assert.equal(value.calls.filter((call) => call === 'pause-video').length, 1)
})

test('a seek during a sync hold releases the video', async () => {
  const value = setup()
  await startSign(value, 'sync-pause')
  value.scheduler.setPlayerState(YT_STATE.PAUSED)
  value.setTime(5000)
  value.scheduler.tick()
  assert.ok(value.calls.includes('reset'))
  assert.ok(value.calls.includes('play-video'))
  assert.equal(value.scheduler.autoPaused, false)
})

test('buffering during a sync hold does not freeze the avatar', async () => {
  const value = setup()
  await startSign(value, 'sync-pause')
  value.scheduler.setPlayerState(YT_STATE.BUFFERING)
  assert.equal(value.calls.includes('pause-sign'), false)
})

test('a hold that never completes is released after maxHoldMs', async () => {
  const value = setup()
  value.scheduler.maxHoldMs = 5000
  await startSign(value, 'sync-pause')
  value.setTime(1200)
  value.scheduler.tick()
  assert.equal(value.calls.includes('play-video'), false)
  value.setTime(7000)
  value.scheduler.lastMediaMs = null // the clock jump is the test, not a seek
  value.scheduler.tick()
  assert.ok(value.calls.includes('play-video'))
})

test('stop releases a sync hold', async () => {
  const value = setup()
  await startSign(value, 'sync-pause')
  value.scheduler.stop()
  assert.ok(value.calls.includes('play-video'))
})
