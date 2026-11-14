/**
 * Copy the playlist's lesson SRTs into the extension, byte for byte.
 *
 * subtitles/lessons.json names, for each YouTube video ID, the source file in the repository's
 * `SRT Files/` folder and the bundled name under extension/subtitles/. This tool only reads the
 * source folder - it never modifies it - and warns about any lesson that is not a structurally
 * valid SRT, so a broken lesson is noticed at build time as well as on YouTube.
 *
 * When `SRT Files/` is absent (a checkout without the sources) the already-bundled copies are
 * validated and kept.
 *
 * Usage: node extension/tools/bundle-subtitles.mjs [--check]
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { BundledSubtitleError, LESSONS_PATH, SUBTITLE_DIR, checkSrt } from '../src/captions/bundled.js'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const check = process.argv.includes('--check')

const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/
const BUNDLED_NAME = /^[a-z0-9-]+\.srt$/

function fail(message) {
  console.error(`ERROR: ${message}`)
  process.exitCode = 1
}

const manifest = JSON.parse(await readFile(resolve(root, LESSONS_PATH), 'utf8'))
const sourceDir = resolve(root, '..', manifest.sourceDir || 'SRT Files')
const haveSources = existsSync(sourceDir)
if (!haveSources) console.warn(`note: ${sourceDir} not found; validating the bundled copies only.`)

const ids = new Set()
const files = new Set()
let copied = 0
let current = 0

for (const lesson of manifest.lessons) {
  const label = `lesson ${lesson.lesson} (${lesson.videoId})`
  if (!VIDEO_ID.test(lesson.videoId || '')) { fail(`${label}: invalid YouTube video ID`); continue }
  if (!BUNDLED_NAME.test(lesson.file || '')) { fail(`${label}: invalid bundled file name "${lesson.file}"`); continue }
  if (ids.has(lesson.videoId)) fail(`${label}: video ID listed twice`)
  if (files.has(lesson.file)) fail(`${label}: bundled file ${lesson.file} listed twice`)
  ids.add(lesson.videoId)
  files.add(lesson.file)

  const target = resolve(root, SUBTITLE_DIR, lesson.file)
  const existing = existsSync(target) ? await readFile(target) : null
  let bytes = existing
  if (haveSources) {
    const source = resolve(sourceDir, lesson.source || '')
    if (!existsSync(source)) { fail(`${label}: source "${lesson.source}" not found in ${sourceDir}`); continue }
    bytes = await readFile(source)
  } else if (!existing) {
    fail(`${label}: ${SUBTITLE_DIR}/${lesson.file} is missing and there is no source to copy`)
    continue
  }

  // A malformed lesson is still copied unchanged - this tool never edits subtitle text - and is
  // reported here and again, visibly, by the extension, which then falls back to YouTube captions.
  try {
    checkSrt(new TextDecoder('utf-8', { fatal: true }).decode(bytes), lesson.source || lesson.file)
  } catch (error) {
    const problem = error instanceof BundledSubtitleError ? error.message : `not UTF-8 text (${error.message})`
    console.warn(`WARNING ${label}: ${problem}`)
  }

  if (existing && Buffer.compare(existing, bytes) === 0) { current += 1; continue }
  if (check) { fail(`${label}: ${SUBTITLE_DIR}/${lesson.file} is stale. Run: npm run build (in extension/)`); continue }
  await mkdir(dirname(target), { recursive: true })
  await writeFile(target, bytes)
  copied += 1
}

if (!process.exitCode) {
  console.log(`subtitles: ${manifest.lessons.length} lessons (${copied} copied, ${current} up to date)`)
}
