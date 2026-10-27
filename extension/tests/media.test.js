import assert from 'node:assert/strict'
import test from 'node:test'
import { WATCHED_EVENTS, createYouTubeMedia, videoEventToPlayerState } from '../src/media/youtube-media.js'
import { YT_STATE } from '../vendor/YouTubeSignScheduler.js'

function fakeVideo(overrides = {}) {
  return {
    currentTime: 0,
    playbackRate: 1,
    duration: 58,
    paused: true,
    calls: [],
    pause() { this.paused = true; this.calls.push('pause') },
    play() { this.paused = false; this.calls.push('play'); return Promise.resolve() },
    ...overrides,
  }
}

test('maps video events onto the scheduler player states', () => {
  assert.equal(videoEventToPlayerState('playing'), YT_STATE.PLAYING)
  assert.equal(videoEventToPlayerState('pause'), YT_STATE.PAUSED)
  assert.equal(videoEventToPlayerState('waiting'), YT_STATE.BUFFERING)
  assert.equal(videoEventToPlayerState('ended'), YT_STATE.ENDED)
})

test('play and seeked carry no state transition', () => {
  // `play` fires before playback starts, and `seeked` must stay unmapped so the scheduler's
  // own drift detection in tick() still fires the resync it is responsible for.
  assert.equal(videoEventToPlayerState('play'), null)
  assert.equal(videoEventToPlayerState('seeked'), null)
  assert.equal(videoEventToPlayerState('ratechange'), null)
  assert.equal(videoEventToPlayerState('timeupdate'), null)
})

test('watched events cover every behaviour the task requires', () => {
  for (const name of ['playing', 'pause', 'waiting', 'seeked', 'ratechange', 'ended']) {
    assert.ok(WATCHED_EVENTS.includes(name), `missing ${name}`)
  }
})

test('exposes the scheduler media contract', () => {
  const media = createYouTubeMedia(fakeVideo({ currentTime: 12.5, playbackRate: 1.75 }))
  assert.equal(media.getCurrentTime(), 12.5)
  assert.equal(media.getPlaybackRate(), 1.75)
  assert.equal(typeof media.pauseVideo, 'function')
  assert.equal(typeof media.playVideo, 'function')
})

test('getCurrentTime and getPlaybackRate coerce unusable values to safe numbers', () => {
  const media = createYouTubeMedia(fakeVideo({ currentTime: NaN, playbackRate: 0 }))
  assert.equal(media.getCurrentTime(), 0)
  assert.equal(media.getPlaybackRate(), 1)
})

test('pauseVideo pauses the element and is attributed to the extension', () => {
  const video = fakeVideo({ paused: false })
  const media = createYouTubeMedia(video)
  media.pauseVideo()
  assert.deepEqual(video.calls, ['pause'])
  assert.equal(media.isPausedByExtension(), true)
})

test('playVideo resumes and clears extension attribution', () => {
  const video = fakeVideo({ paused: false })
  const media = createYouTubeMedia(video)
  media.pauseVideo()
  media.playVideo()
  assert.equal(video.paused, false)
  assert.equal(media.isPausedByExtension(), false)
})

test('a pause the extension did not cause is never attributed to it', () => {
  // This is the guard behind "never auto-resume a video paused by the user".
  const video = fakeVideo({ paused: false })
  const media = createYouTubeMedia(video)
  video.pause() // the user clicking pause
  assert.equal(media.isPausedByExtension(), false)
  media.noteExternalPause()
  assert.equal(media.isPausedByExtension(), false)
})

test('extension attribution does not survive the video being played again', () => {
  const video = fakeVideo({ paused: false })
  const media = createYouTubeMedia(video)
  media.pauseVideo()
  assert.equal(media.isPausedByExtension(), true)
  video.play() // the user pressing play while we were caught up
  assert.equal(media.isPausedByExtension(), false, 'a playing video is not extension-paused')
})

test('a rejected play() promise does not throw', () => {
  const video = fakeVideo({ play() { this.calls.push('play'); return Promise.reject(new Error('autoplay')) } })
  const media = createYouTubeMedia(video)
  assert.doesNotThrow(() => media.playVideo())
})

test('a detached element does not throw on pause', () => {
  const media = createYouTubeMedia({
    currentTime: 0, playbackRate: 1, paused: false,
    pause() { throw new Error('detached') },
    play() { throw new Error('detached') },
  })
  assert.doesNotThrow(() => media.pauseVideo())
  assert.doesNotThrow(() => media.playVideo())
})
