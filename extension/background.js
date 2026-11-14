/**
 * MV3 service worker. Owns every request to the Signora backend.
 *
 * This is the reason the backend needs no CORS change at all. A fetch issued from an extension
 * service worker whose host is listed in `host_permissions` is not subject to the page's CORS
 * rules - the extension origin is granted access directly. Had these requests been made from the
 * content script instead, they would have carried `Origin: https://www.youtube.com` and required
 * `http://127.0.0.1:8000` to allow that origin, which would mean weakening
 * `backend/app/core/config.py::cors_origins` for every website. So the content script never talks
 * to the backend; it asks this worker to.
 *
 * Multipart note: `FormData`/`File` cannot cross `chrome.runtime.sendMessage`, which is why the
 * subtitle arrives here as a plain string and the `Blob` is constructed on this side.
 */

import { DEFAULTS, loadConfig } from './src/config.js'
import { loadBundledSubtitle } from './src/captions/bundled.js'

async function apiBase() {
  const config = await loadConfig()
  return config.apiBase || DEFAULTS.apiBase
}

/** Shared error shaping so the overlay can show the backend's own `detail` message. */
async function readError(response) {
  let detail = response.statusText || `HTTP ${response.status}`
  try {
    const body = await response.json()
    if (body && body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
  } catch {
    // Non-JSON error body; the status text is the best available.
  }
  return detail
}

async function health() {
  const base = await apiBase()
  const response = await fetch(`${base}/health`, { method: 'GET' })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

/**
 * POST the generated subtitle plus the real watch URL to the existing video-plan endpoint.
 * Mirrors `frontend/src/api/client.js::createVideoPlan`.
 */
async function createVideoPlan({ youtubeUrl, vtt, filename = 'captions.vtt' }) {
  const base = await apiBase()
  const form = new FormData()
  form.append('youtube_url', youtubeUrl)
  // The backend picks its SRT or WebVTT parser from the filename's extension.
  const type = filename.toLowerCase().endsWith('.srt') ? 'application/x-subrip' : 'text/vtt'
  form.append('subtitle', new Blob([vtt], { type }), filename)
  const response = await fetch(`${base}/video-plans`, { method: 'POST', body: form })
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

async function getVideoPlan(planId) {
  const base = await apiBase()
  const response = await fetch(`${base}/video-plans/${encodeURIComponent(planId)}`)
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

/**
 * Fetch one unit's composed motion.
 *
 * `motionUrl` comes back from the backend already prefixed with `/api/v1`, and the endpoint
 * replies with gzip-encoded JSON plus an explicit `Content-Encoding: gzip` header. `fetch`
 * transparently inflates that, so `response.json()` is correct here.
 */
async function getUnitMotion(motionUrl) {
  const base = await apiBase()
  const root = base.replace(/\/api\/v1\/?$/, '')
  const url = /^https?:\/\//i.test(motionUrl) ? motionUrl : `${root}${motionUrl}`
  const response = await fetch(url)
  if (!response.ok) throw new Error(await readError(response))
  return response.json()
}

/**
 * The bundled lesson SRT for a known playlist video, or null. Read through the extension's own
 * URLs, which the service worker may fetch without web_accessible_resources; the content script
 * running on youtube.com has no access to these files or to the user's filesystem.
 */
async function readExtensionText(path) {
  let response
  try {
    response = await fetch(chrome.runtime.getURL(path))
  } catch (error) {
    throw new Error(`file not found in the extension (${error.message})`)
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}`)
  return response.text()
}

function getBundledSubtitle({ videoId }) {
  return loadBundledSubtitle(videoId, readExtensionText)
}

const HANDLERS = { health, createVideoPlan, getVideoPlan, getUnitMotion, getBundledSubtitle }

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const handler = message && HANDLERS[message.type]
  if (!handler) {
    sendResponse({ ok: false, error: `Unknown message type: ${message && message.type}` })
    return false
  }
  Promise.resolve(handler(message.payload))
    .then((value) => sendResponse({ ok: true, value }))
    .catch((error) => sendResponse({
      ok: false,
      error: String((error && error.message) || error),
      // A failed fetch to localhost is almost always "the backend is not running".
      offline: error instanceof TypeError,
    }))
  return true // keep the message channel open for the async reply
})
