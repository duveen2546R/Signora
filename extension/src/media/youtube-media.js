/**
 * Adapt a real YouTube `<video>` element to the media interface
 * `frontend/src/video/YouTubeSignScheduler.js` already expects.
 *
 * The scheduler was written against the YouTube IFrame API surface
 * (`getCurrentTime`, `getPlaybackRate`, `pauseVideo`, `playVideo`) and against the
 * `YT_STATE` enum. Keeping that contract intact is what lets the extension reuse the
 * tested scheduler verbatim instead of forking it.
 *
 * DOM-free except for the element handed in, so both functions here are unit testable with a
 * plain stub object.
 */

import { YT_STATE } from '../../vendor/YouTubeSignScheduler.js'

/**
 * Map a `<video>` DOM event name to the `YT_STATE` the scheduler understands.
 *
 * `null` means "this event carries no state transition" and must not be forwarded:
 *   - `play` fires before playback actually resumes; `playing` is the real transition, and
 *     reporting PLAYING too early would let the scheduler measure drift against a clock that
 *     has not started moving.
 *   - `seeked` is intentionally not a state change. The scheduler already detects a seek inside
 *     `tick()` by comparing media-time movement against wall-clock movement, and that path is
 *     covered by the existing scheduler tests. Forwarding a state here would refresh the
 *     scheduler's drift baseline and suppress the resync it is supposed to trigger.
 */
export function videoEventToPlayerState(eventName) {
  switch (eventName) {
    case 'playing': return YT_STATE.PLAYING
    case 'pause': return YT_STATE.PAUSED
    case 'waiting': return YT_STATE.BUFFERING
    case 'ended': return YT_STATE.ENDED
    default: return null
  }
}

/** Events worth subscribing to on the page's video element. */
export const WATCHED_EVENTS = ['playing', 'pause', 'waiting', 'ended', 'seeked', 'ratechange']

/**
 * Wrap a video element.
 *
 * `pauseVideo`/`playVideo` additionally record whether the extension was the caller. The
 * scheduler owns the authoritative `autoPaused` flag that decides whether a video may be
 * auto-resumed; this local flag exists so the overlay can honestly label a pause as
 * "catch-up" versus "paused by you" without second-guessing the scheduler.
 */
export function createYouTubeMedia(video) {
  let pausedByExtension = false

  return {
    // --- scheduler contract ---
    getCurrentTime: () => Number(video.currentTime) || 0,
    getPlaybackRate: () => Number(video.playbackRate) || 1,
    pauseVideo: () => {
      pausedByExtension = true
      try { video.pause() } catch { /* a detached element is not an error worth raising */ }
    },
    playVideo: () => {
      pausedByExtension = false
      try {
        const result = video.play()
        // Autoplay policy can reject; the user can always press play themselves.
        if (result && typeof result.catch === 'function') result.catch(() => {})
      } catch { /* ignore */ }
    },

    // --- extension extras ---
    getDuration: () => Number(video.duration) || 0,
    isPaused: () => Boolean(video.paused),
    /** True when the most recent pause came from the scheduler's catch-up logic. */
    isPausedByExtension: () => pausedByExtension && Boolean(video.paused),
    /** Called when a pause is observed that the extension did not initiate. */
    noteExternalPause: () => { pausedByExtension = false },
    element: video,
  }
}
