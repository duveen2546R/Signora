/**
 * Single source of configuration for the extension.
 *
 * Everything that points at a local service or toggles a feature lives here, so there is exactly
 * one place to change when the backend moves or the Unity avatar becomes available.
 */

export const DEFAULTS = {
  /** Signora backend API root. Must be covered by host_permissions in manifest.json. */
  apiBase: 'http://127.0.0.1:8000/api/v1',

  /**
   * Which avatar adapter to use.
   *   'unity' - the real Signora Unity WebGL runtime, hosted at `unityHostUrl` and driven through
   *             an iframe + postMessage (see avatar/unity-iframe.js and
   *             frontend/src/pages/AvatarHost.jsx). This is the default: the host page and relay
   *             exist and are tested, but require `cd frontend && npm run dev` to actually be
   *             running - see extension/README.md "Unity handoff" for exact verification status.
   *   'mock'  - visible in-overlay sign player driven by the real composed motion's frameCount/fps.
   *             Used automatically, with a clearly reported reason, if the Unity host page does
   *             not answer within readyTimeoutMs - never a silent fallback.
   */
  avatarAdapter: 'unity',

  /**
   * Origin + path that serves the Unity avatar host page (the Vite dev server's default), used
   * only when avatarAdapter === 'unity'. Keep in sync with host_permissions in manifest.json.
   */
  unityHostUrl: 'http://127.0.0.1:5173/signora-avatar',

  /** Preferred caption languages, in order. Auto-generated (ASR) tracks are accepted. */
  captionLanguages: ['en', 'en-US', 'en-GB'],

  /**
   * Poll interval while the backend prepares a video plan, and how long before the extension
   * slows its polling (it never stops: the backend has been measured taking minutes on a long
   * caption list, and the scheduler is already attached and playable well before this matters).
   */
  planPollMs: 700,
  planTimeoutMs: 45000,

  /** Keep video playing continuously; caption motion is time-scaled to its own cue window. */
  overrunPolicy: 'continue',

  /** How many upcoming caption units count as "the look-ahead buffer" for the overlay's status. */
  lookaheadUnits: 2,

  /**
   * How long to wait for YouTube's player to emit a timed-text response we can capture.
   * The page bridge escalates at ~0.6 s (re-select the track) and ~1.6 s (press the CC button),
   * so this must comfortably outlast both before giving up.
   */
  captionCaptureTimeoutMs: 15000,

  /** Show the overlay panel expanded on load. */
  overlayExpanded: true,

  /** Verbose console logging under the [signora] prefix. */
  debug: false,
}

let cache = { ...DEFAULTS }

/** Merge any user overrides saved in chrome.storage.sync over the defaults. */
export async function loadConfig() {
  try {
    const stored = await chrome.storage?.sync?.get('signora')
    if (stored && stored.signora && typeof stored.signora === 'object') {
      cache = { ...DEFAULTS, ...stored.signora }
    }
  } catch {
    // Storage unavailable (e.g. during tests); defaults are correct.
  }
  return cache
}

export function config() {
  return cache
}

export function log(...args) {
  if (cache.debug) console.log('[signora]', ...args)
}

export function warn(...args) {
  console.warn('[signora]', ...args)
}
