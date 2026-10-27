/**
 * Convert YouTube timed-text payloads into a WebVTT file the Signora backend already accepts.
 *
 * Pure functions only: no DOM, no network, no extension APIs, so this module is directly unit
 * testable under `node --test`. The output has to satisfy
 * `backend/app/services/subtitle_service.py::parse_subtitles`, which means:
 *   - the file must parse as UTF-8 and end up with at least one spoken cue;
 *   - every cue needs `end_ms > start_ms`, otherwise the whole file is rejected;
 *   - timestamps must match `(?:(\d+):)?(\d{2}):(\d{2})[,.](\d{3})` with minutes/seconds <= 59.
 *
 * YouTube serves two shapes we care about. JSON3 (`&fmt=json3`) is preferred because it carries
 * explicit per-event durations. The srv3/legacy XML form is handled as a fallback because the
 * player sometimes requests it instead.
 */

/** A cue with absolute millisecond bounds and cleaned single-line text. */

// Auto-generated tracks emit "rolling" events that re-send the previous words so the on-screen
// caption can grow word by word. Those carry `aAppend: 1`. Keeping them would duplicate text and
// produce hundreds of overlapping 10 ms cues, so only the settled events are used.
const ROLLING_APPEND = 1

const MIN_CUE_MS = 400
const MAX_IMPLIED_CUE_MS = 8000
const FALLBACK_CUE_MS = 2000

function cleanText(value) {
  return String(value)
    .replace(/\r/g, '')
    // A caption line break is not a sentence boundary; the backend groups by timing and
    // punctuation, so collapse to a single spaced line.
    .replace(/\s*\n\s*/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * Give every cue a strictly positive duration and stop it running into its successor.
 *
 * JSON3 events can arrive with `dDurationMs` absent or zero, and ASR events frequently overlap.
 * The backend rejects the entire subtitle file on a single non-positive cue, so this is repaired
 * here rather than discovered as a 422 later.
 */
function normaliseCues(cues) {
  const sorted = cues
    .filter((cue) => Number.isFinite(cue.startMs) && cue.startMs >= 0 && cue.text)
    .sort((a, b) => a.startMs - b.startMs || a.endMs - b.endMs)

  for (let i = 0; i < sorted.length; i += 1) {
    const cue = sorted[i]
    const next = sorted[i + 1]

    if (!Number.isFinite(cue.endMs) || cue.endMs <= cue.startMs) {
      const implied = next ? next.startMs - cue.startMs : FALLBACK_CUE_MS
      cue.endMs = cue.startMs + Math.min(Math.max(implied, MIN_CUE_MS), MAX_IMPLIED_CUE_MS)
    }
    // Trim an overlap, but never below the floor that keeps the cue valid.
    if (next && cue.endMs > next.startMs) {
      cue.endMs = Math.max(next.startMs, cue.startMs + MIN_CUE_MS)
    }
    if (cue.endMs <= cue.startMs) cue.endMs = cue.startMs + MIN_CUE_MS
  }
  return sorted
}

/** Parse a JSON3 timed-text payload (string or already-parsed object) into cues. */
export function parseJson3(raw) {
  const data = typeof raw === 'string' ? JSON.parse(raw) : raw
  const events = Array.isArray(data?.events) ? data.events : []
  const cues = []

  for (const event of events) {
    if (!event || event.aAppend === ROLLING_APPEND) continue
    if (!Array.isArray(event.segs)) continue

    const text = cleanText(
      event.segs.map((seg) => (seg && typeof seg.utf8 === 'string' ? seg.utf8 : '')).join(''),
    )
    if (!text) continue

    const startMs = Math.round(Number(event.tStartMs))
    const duration = Number(event.dDurationMs)
    cues.push({
      startMs,
      endMs: Number.isFinite(duration) && duration > 0 ? Math.round(startMs + duration) : NaN,
      text,
    })
  }
  return normaliseCues(cues)
}

const ENTITIES = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", '#39': "'", nbsp: ' ',
}

function decodeEntities(value) {
  return String(value).replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (match, name) => {
    if (Object.prototype.hasOwnProperty.call(ENTITIES, name)) return ENTITIES[name]
    if (name[0] === '#') {
      const code = name[1] === 'x' || name[1] === 'X'
        ? Number.parseInt(name.slice(2), 16)
        : Number.parseInt(name.slice(1), 10)
      if (Number.isFinite(code) && code > 0 && code <= 0x10ffff) {
        try { return String.fromCodePoint(code) } catch { return match }
      }
    }
    return match
  })
}

/**
 * Parse srv3 (`<p t= d=>`) and legacy (`<text start= dur=>`) timed-text XML into cues.
 *
 * Deliberately regex-based: YouTube's timed-text XML is a flat, machine-generated document with no
 * namespaces or nesting beyond `<s>` spans, and a regex keeps this module DOM-free and testable in
 * Node. It is not a general-purpose XML parser and is not used for anything else.
 */
export function parseTimedTextXml(raw) {
  const xml = String(raw)
  const cues = []

  // srv3: <p t="1000" d="3000"><s>word</s><s> next</s></p>
  const paragraph = /<p\b([^>]*)>([\s\S]*?)<\/p>/g
  let match = paragraph.exec(xml)
  while (match !== null) {
    const attributes = match[1]
    const start = Number((/\bt="(-?\d+)"/.exec(attributes) || [])[1])
    const duration = Number((/\bd="(-?\d+)"/.exec(attributes) || [])[1])
    const text = cleanText(decodeEntities(match[2].replace(/<[^>]*>/g, '')))
    if (Number.isFinite(start) && text) {
      cues.push({
        startMs: Math.round(start),
        endMs: Number.isFinite(duration) && duration > 0 ? Math.round(start + duration) : NaN,
        text,
      })
    }
    match = paragraph.exec(xml)
  }
  if (cues.length) return normaliseCues(cues)

  // Legacy: <text start="1.0" dur="3.0">word</text> (seconds, not milliseconds)
  const legacy = /<text\b([^>]*)>([\s\S]*?)<\/text>/g
  match = legacy.exec(xml)
  while (match !== null) {
    const attributes = match[1]
    const start = Number((/\bstart="([\d.]+)"/.exec(attributes) || [])[1])
    const duration = Number((/\bdur="([\d.]+)"/.exec(attributes) || [])[1])
    const text = cleanText(decodeEntities(match[2].replace(/<[^>]*>/g, '')))
    if (Number.isFinite(start) && text) {
      cues.push({
        startMs: Math.round(start * 1000),
        endMs: Number.isFinite(duration) && duration > 0
          ? Math.round((start + duration) * 1000)
          : NaN,
        text,
      })
    }
    match = legacy.exec(xml)
  }
  return normaliseCues(cues)
}

/** `HH:MM:SS.mmm`, the WebVTT form the backend's timestamp regex accepts. */
export function formatVttTimestamp(ms) {
  const total = Math.max(0, Math.round(Number(ms) || 0))
  const hours = Math.floor(total / 3600000)
  const minutes = Math.floor((total % 3600000) / 60000)
  const seconds = Math.floor((total % 60000) / 1000)
  const millis = total % 1000
  const pad = (value, width = 2) => String(value).padStart(width, '0')
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}.${pad(millis, 3)}`
}

/** Render cues as a WebVTT document. */
export function cuesToVtt(cues) {
  const lines = ['WEBVTT', '']
  cues.forEach((cue, index) => {
    lines.push(String(index + 1))
    lines.push(`${formatVttTimestamp(cue.startMs)} --> ${formatVttTimestamp(cue.endMs)}`)
    lines.push(cue.text)
    lines.push('')
  })
  return lines.join('\n')
}

/**
 * Detect the payload shape and return `{ cues, vtt, format }`.
 * Throws when nothing usable is present, so callers can surface an honest "no captions" state
 * instead of sending an empty file to the backend.
 */
export function timedTextToVtt(raw) {
  const text = typeof raw === 'string' ? raw.trim() : raw
  let cues = []
  let format = 'unknown'

  if (text && typeof text === 'object') {
    cues = parseJson3(text)
    format = 'json3'
  } else if (typeof text === 'string' && text.length) {
    if (text.startsWith('{')) {
      cues = parseJson3(text)
      format = 'json3'
    } else if (text.startsWith('<')) {
      cues = parseTimedTextXml(text)
      format = 'xml'
    }
  }

  if (!cues.length) {
    throw new Error('The caption payload contained no usable spoken cues.')
  }
  return { cues, vtt: cuesToVtt(cues), format }
}
