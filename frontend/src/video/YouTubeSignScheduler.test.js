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
