/**
 * Pure message-relay logic for the Unity avatar host page (`frontend/src/pages/AvatarHost.jsx`).
 *
 * This page is embedded as an iframe by the Signora Chrome extension
 * (`extension/src/avatar/unity-iframe.js`) so the Unity WebGL runtime can run on its own origin
 * rather than inside youtube.com's CSP. The extension and this page speak a small protocol:
 *
 *   extension -> host: { signora: 'cmd', id, method, args }
 *   host -> extension: { signora: 'ack', id, value }             (reply to one command)
 *                       { signora: 'ready' }                      (once the avatar is calibrated)
 *                       { signora: 'event', name: 'finished' }     (SignoraPlayer.onFinished)
 *                       { signora: 'event', name: 'sign', gloss, occurrenceIndex }
 *
 * Kept framework-free and DOM-free so it is testable in plain Node: `handleCommand` takes a
 * message and a `window.signsure`-shaped object and returns the reply to send, with no side
 * effects of its own.
 */

/**
 * `window.signsure` (installed by `SignoraStage.jsx`) exposes exactly: calibrate, play, enqueue,
 * cancelQueued, queuedDurationMs, clear, pause, resume, resetToIdle, isCalibrated, isPlaying.
 * `setPlaybackRate` and `seek` are not among them - `SignoraPlayer` derives its rate internally
 * from `payload.liveTiming.targetDurationMs` and has no intra-track seek. Rather than fabricate
 * new avatar behaviour here, those two commands are acknowledged as a harmless no-op: playback
 * itself stays correct, only YouTube's speed control and seek-synced trimming go unhonoured by
 * the real avatar until SignoraPlayer grows them.
 */
export function handleCommand(message, signsure) {
  if (!message || message.signora !== 'cmd') return null
  const { id, method, args = [] } = message

  if (!signsure || typeof signsure[method] !== 'function') {
    // Unknown or unavailable method: acknowledge with no effect rather than throwing across the
    // frame boundary, so one unsupported command can never wedge the whole relay.
    return { signora: 'ack', id, value: undefined }
  }
  let value
  try {
    value = signsure[method](...args)
  } catch (error) {
    return { signora: 'ack', id, value: undefined, error: String((error && error.message) || error) }
  }
  return { signora: 'ack', id, value }
}

/** `SignoraStage`'s `onSignStart` -> the `sign` event the extension's adapter expects. */
export function signEvent(gloss, occurrenceIndex) {
  return { signora: 'event', name: 'sign', gloss, occurrenceIndex }
}

/** `SignoraStage`'s `onIdle` -> the `finished` event. */
export function finishedEvent() {
  return { signora: 'event', name: 'finished' }
}

export function readyEvent() {
  return { signora: 'ready' }
}

/**
 * Which origin this page's parent frame actually is, so replies are never broadcast with `'*'`.
 * `location.ancestorOrigins` (Chromium-only, which is exactly what matters here: this page only
 * ever needs to work inside the Signora Chrome extension) gives the real embedding origin without
 * guessing. Falls back to the one origin this page is ever expected to run under.
 */
export function resolveParentOrigin(win = window, fallback = 'https://www.youtube.com') {
  try {
    const ancestors = win.location && win.location.ancestorOrigins
    if (ancestors && ancestors.length > 0) return ancestors[0]
  } catch {
    // Not available in this browser or context; use the fallback.
  }
  return fallback
}

/** Only accept commands from the origin we resolved as the parent - never '*'. */
export function isTrustedMessageEvent(event, trustedOrigin) {
  return Boolean(event) && event.origin === trustedOrigin
}
