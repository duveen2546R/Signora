/**
 * Bundled lesson subtitles for the target grammar playlist, and the order in which a caption
 * source is chosen for a video.
 *
 * subtitles/lessons.json maps each known YouTube video ID to a byte-identical copy of its SRT
 * under extension/subtitles/ (copied there by tools/bundle-subtitles.mjs). The video ID is the
 * only key used at runtime - never a filename's position. The service worker reads the files
 * through the extension's own URLs; a YouTube content script cannot reach the filesystem.
 *
 * Priority for a video:
 *   1. a subtitle file the viewer picked for this video in this tab (it always wins);
 *   2. the bundled lesson SRT for a known playlist video;
 *   3. normal YouTube caption discovery (which keeps the manual picker as its fallback).
 * A bundled file that is missing, malformed or rejected by the backend is reported visibly and
 * then falls through to (3). Subtitle text is passed on unchanged; the backend's own SRT/VTT
 * validation still decides what is acceptable.
 */

export const LESSONS_PATH = 'subtitles/lessons.json'
export const SUBTITLE_DIR = 'subtitles'
export const REBUILD_HINT = 'Run `npm run build` in extension/, then reload the extension.'

export class BundledSubtitleError extends Error {
  constructor(message) {
    super(message)
    this.name = 'BundledSubtitleError'
  }
}

export function findLesson(manifest, videoId) {
  if (!videoId || !Array.isArray(manifest?.lessons)) return null
  return manifest.lessons.find((lesson) => lesson.videoId === videoId) ?? null
}

export function lessonTitle(lesson) {
  return lesson.displayTitle || lesson.title || `Lesson ${lesson.lesson}`
}

const TIMESTAMP = /^(?:(\d+):)?(\d{2}):(\d{2})[,.](\d{3})$/

function timestampMs(value) {
  const match = TIMESTAMP.exec(value.trim())
  if (!match || Number(match[2]) > 59 || Number(match[3]) > 59) return null
  const [hours, minutes, seconds, millis] = [match[1] || 0, match[2], match[3], match[4]].map(Number)
  return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis
}

/**
 * Structural SRT check, so a broken bundled file is reported with its block number before it is
 * sent anywhere. It mirrors the backend's per-block rules (a timing line with valid timestamps,
 * ending after it starts) but changes nothing: the backend still parses the original bytes.
 * Returns the number of cue blocks.
 */
export function checkSrt(text, name = 'subtitle') {
  if (typeof text !== 'string' || !text.trim()) {
    throw new BundledSubtitleError(`Bundled subtitle ${name} is empty. ${REBUILD_HINT}`)
  }
  const malformed = (block, problem) => new BundledSubtitleError(
    `Bundled subtitle ${name} is malformed: block ${block} ${problem}. `
    + `Fix that block in the file in "SRT Files/". ${REBUILD_HINT}`,
  )
  const blocks = text.replace(/^﻿/, '').replace(/\r\n?/g, '\n').trim().split(/\n\s*\n/)
  blocks.forEach((block, index) => {
    const timing = block.split('\n').find((line) => line.includes('-->'))
    const [start = '', rest = ''] = timing ? timing.split('-->') : []
    const startMs = timestampMs(start)
    const endMs = timestampMs(rest.trim().split(/\s+/)[0] ?? '')
    if (startMs === null || endMs === null) {
      throw malformed(index + 1, 'has no valid "start --> end" timing line')
    }
    if (endMs <= startMs) throw malformed(index + 1, `ends before it starts (${timing.trim()})`)
  })
  return blocks.length
}

/**
 * The playlist's authored SRTs carry two text lines per cue: the spoken English caption followed
 * by its concise signing line. Keep the latter for motion planning so the backend does not try to
 * sign both versions consecutively. The original bundled SRT remains untouched for display and
 * auditing; this transform is only applied to known bundled lesson files, never a viewer-picked
 * subtitle where two lines may simply be visual wrapping.
 */
export function signingTextSrt(text) {
  const blocks = text.replace(/^﻿/, '').replace(/\r\n?/g, '\n').trim().split(/\n\s*\n/)
  return `${blocks.map((block) => {
    const lines = block.split('\n')
    const timingIndex = lines.findIndex((line) => line.includes('-->'))
    if (timingIndex < 0) return block
    const captionLines = lines.slice(timingIndex + 1).filter((line) => line.trim())
    if (captionLines.length < 2) return block
    return [...lines.slice(0, timingIndex + 1), captionLines.at(-1)].join('\n')
  }).join('\n\n')}\n`
}

/**
 * The bundled subtitle for `videoId`, or null when the video is not a known playlist lesson.
 * `readText(path)` reads an extension-relative file (fetch of chrome.runtime.getURL in the
 * service worker; the filesystem in tests). Throws BundledSubtitleError with an actionable
 * message when the mapped file is missing or malformed.
 */
export async function loadBundledSubtitle(videoId, readText) {
  let manifest
  try {
    manifest = JSON.parse(await readText(LESSONS_PATH))
  } catch (error) {
    throw new BundledSubtitleError(`Cannot read ${LESSONS_PATH} (${error.message}). ${REBUILD_HINT}`)
  }
  const lesson = findLesson(manifest, videoId)
  if (!lesson) return null

  const path = `${SUBTITLE_DIR}/${lesson.file}`
  let text
  try {
    text = await readText(path)
  } catch (error) {
    throw new BundledSubtitleError(
      `Bundled subtitle for ${lessonTitle(lesson)} is missing (${path}: ${error.message}). ${REBUILD_HINT}`,
    )
  }
  const cues = checkSrt(text, path)
  return {
    videoId, lesson: lesson.lesson, title: lessonTitle(lesson), filename: lesson.file, text, cues,
  }
}

/**
 * Pick and start the caption source for one video, in priority order (see the module comment).
 *
 *   manual        - { videoId, name, text, filename } chosen with "Load subtitle file…", or null
 *   loadBundled   - videoId -> bundled subtitle | null; throws on a missing/malformed file
 *   buildPlan     - (text, { filename }) -> { ok, error }; ok:false when the backend rejects it
 *   discover      - normal YouTube caption discovery
 *   report        - ({ source?, subtitleError? }) -> overlay patch
 *   isCurrent     - false once a newer choice (e.g. a manual pick) has superseded this one
 *
 * Resolves to which source started: 'manual' | 'bundled' | 'youtube' | 'superseded'.
 */
export async function startSubtitleSource({
  videoId, manual = null, loadBundled, buildPlan, discover, report, isCurrent = () => true,
}) {
  if (manual && manual.videoId === videoId) {
    report({ source: { kind: 'manual', name: manual.name } })
    await buildPlan(manual.text, { filename: manual.filename })
    return 'manual'
  }

  let bundled = null
  try {
    bundled = await loadBundled(videoId)
  } catch (error) {
    if (!isCurrent()) return 'superseded'
    report({ subtitleError: `${error.message} Falling back to YouTube captions.` })
  }
  if (!isCurrent()) return 'superseded'

  if (bundled) {
    report({ source: { kind: 'bundled', title: bundled.title, name: bundled.filename } })
    const result = await buildPlan(signingTextSrt(bundled.text), { filename: bundled.filename })
    if (result?.ok) return 'bundled'
    if (!isCurrent()) return 'superseded'
    report({
      source: null,
      subtitleError: `The backend rejected bundled subtitle ${bundled.filename}: ${result?.error || 'unknown error'}. `
        + 'Falling back to YouTube captions.',
    })
  }

  await discover()
  return 'youtube'
}
