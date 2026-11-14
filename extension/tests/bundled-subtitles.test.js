/**
 * Bundled lesson subtitles for the target grammar playlist: the video-ID manifest, the copies
 * the extension ships, and the order in which a caption source is chosen for a video. The real
 * bundled files are read from disk the way the service worker reads them through extension URLs.
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  BundledSubtitleError, LESSONS_PATH, checkSrt, loadBundledSubtitle, signingTextSrt, startSubtitleSource,
} from '../src/captions/bundled.js'
import { subtitleSourceText } from '../src/overlay/overlay.js'

const here = dirname(fileURLToPath(import.meta.url))
const extensionRoot = resolve(here, '..')
const readExtensionText = (path) => readFile(resolve(extensionRoot, path), 'utf8')
const manifest = JSON.parse(await readFile(resolve(extensionRoot, LESSONS_PATH), 'utf8'))

const LESSON_1 = 'bobPMUfr_c0' // "Learn English Consonants and Vowels", playlist position 2
const UNKNOWN = 'oK6LGQY_7A4' // the acceptance video, not part of the playlist
const GOOD_SRT = '1\n00:00:01,000 --> 00:00:02,500\nHello.\n\n2\n00:00:03,000 --> 00:00:04,000\nBye.\n'

/** Fakes for startSubtitleSource that record what happened, in order. */
function flow({ bundled = null, bundledError = null, backendRejects = false, manual = null } = {}) {
  const calls = []
  const patches = []
  return {
    calls,
    patches,
    run: (videoId, extra = {}) => startSubtitleSource({
      videoId,
      manual,
      loadBundled: async (id) => {
        calls.push(['loadBundled', id])
        if (bundledError) throw bundledError
        return bundled
      },
      buildPlan: async (text, { filename }) => {
        calls.push(['buildPlan', filename, text])
        return backendRejects ? { ok: false, error: 'Subtitle block 3 ends before it starts.' } : { ok: true }
      },
      discover: async () => { calls.push(['discover']) },
      report: (patch) => patches.push(patch),
      ...extra,
    }),
  }
}

test('the manifest maps 24 distinct video IDs to bundled files, never by position', () => {
  assert.equal(manifest.playlistId, 'PL2IkMHFHWdErCjwGKA3InTW6a0gfMPRRM')
  assert.equal(manifest.lessons.length, 24)
  assert.equal(new Set(manifest.lessons.map((l) => l.videoId)).size, 24)
  assert.equal(new Set(manifest.lessons.map((l) => l.file)).size, 24)
  for (const lesson of manifest.lessons) {
    assert.match(lesson.videoId, /^[A-Za-z0-9_-]{11}$/)
    assert.ok(lesson.title && lesson.source && lesson.file, `lesson ${lesson.lesson} is incomplete`)
  }
})

test('every bundled copy is byte-identical to its file in "SRT Files/"', async (t) => {
  const sourceDir = resolve(extensionRoot, '..', manifest.sourceDir)
  if (!existsSync(sourceDir)) { t.skip('"SRT Files/" is not present in this checkout'); return }
  for (const lesson of manifest.lessons) {
    const source = await readFile(resolve(sourceDir, lesson.source))
    const bundled = await readFile(resolve(extensionRoot, 'subtitles', lesson.file))
    assert.ok(source.equals(bundled), `${lesson.file} differs from "${lesson.source}"`)
  }
  // The bundler agrees nothing is stale (and exits non-zero when something is).
  execFileSync(process.execPath, [resolve(extensionRoot, 'tools/bundle-subtitles.mjs'), '--check'], { stdio: 'pipe' })
})

test('a known video ID loads its mapped bundled SRT, unchanged', async () => {
  const subtitle = await loadBundledSubtitle(LESSON_1, readExtensionText)
  assert.equal(subtitle.filename, 'lesson-01.srt')
  assert.equal(subtitle.title, 'Lesson 1 — Learn English Consonants and Vowels')
  assert.equal(subtitle.text, await readExtensionText('subtitles/lesson-01.srt'))
  assert.ok(subtitle.cues > 0)

  const f = flow({ bundled: subtitle })
  assert.equal(await f.run(LESSON_1), 'bundled')
  assert.deepEqual(f.calls, [['loadBundled', LESSON_1], ['buildPlan', 'lesson-01.srt', signingTextSrt(subtitle.text)]])
  assert.deepEqual(f.patches, [{ source: { kind: 'bundled', title: subtitle.title, name: 'lesson-01.srt' } }])
  assert.equal(subtitleSourceText(f.patches[0].source),
    'Using bundled lesson subtitle: Lesson 1 — Learn English Consonants and Vowels')
})

test('bundled lesson planning uses the authored signing line rather than duplicating each cue', () => {
  const source = '1\n00:00:01,000 --> 00:00:02,000\nHello everybody.\nhello everybody\n\n2\n00:00:03,000 --> 00:00:04,000\nBye.\n'
  assert.equal(signingTextSrt(source),
    '1\n00:00:01,000 --> 00:00:02,000\nhello everybody\n\n2\n00:00:03,000 --> 00:00:04,000\nBye.\n')
})

test('an unknown video ID uses normal YouTube caption discovery', async () => {
  assert.equal(await loadBundledSubtitle(UNKNOWN, readExtensionText), null)
  const f = flow({ bundled: null })
  assert.equal(await f.run(UNKNOWN), 'youtube')
  assert.deepEqual(f.calls, [['loadBundled', UNKNOWN], ['discover']])
  assert.deepEqual(f.patches, [], 'no error and no bundled source is claimed')
})

test('a missing bundled file is reported and falls back to YouTube captions', async () => {
  const readWithout = (path) => (path.endsWith('lesson-01.srt')
    ? Promise.reject(new Error('ENOENT: no such file'))
    : readExtensionText(path))
  await assert.rejects(loadBundledSubtitle(LESSON_1, readWithout), (error) => {
    assert.ok(error instanceof BundledSubtitleError)
    assert.match(error.message, /missing \(subtitles\/lesson-01\.srt/)
    assert.match(error.message, /npm run build/)
    return true
  })

  const error = await loadBundledSubtitle(LESSON_1, readWithout).catch((e) => e)
  const f = flow({ bundledError: error })
  assert.equal(await f.run(LESSON_1), 'youtube')
  assert.deepEqual(f.calls.map((c) => c[0]), ['loadBundled', 'discover'], 'nothing is sent to the backend')
  assert.match(f.patches[0].subtitleError, /missing.*Falling back to YouTube captions\.$/)
})

test('a malformed SRT reports which block to fix, and falls back', async () => {
  assert.equal(checkSrt(GOOD_SRT), 2)
  assert.equal(checkSrt(GOOD_SRT.replace(/\n/g, '\r\n')), 2, 'CRLF files are fine')
  const cases = [
    ['1\n00:00:01,000 --> 00:00:02,000\nHi.\n\n2\nno timing here\n', /block 2 has no valid "start --> end" timing line/],
    ['1\n00:00:01,000 --> 00:00:02,000\nHi.\n\n2\n00:00:00,000 --> 00:00:00,000\nBye.\n', /block 2 ends before it starts/],
    ['1\n00:00:01,000 --> 00:61:02,000\nHi.\n', /block 1 has no valid/],
    ['   \n', /is empty/],
  ]
  for (const [text, expected] of cases) {
    assert.throws(() => checkSrt(text, 'lesson-99.srt'), (error) => {
      assert.ok(error instanceof BundledSubtitleError)
      assert.match(error.message, expected)
      if (!/empty/.test(error.message)) assert.match(error.message, /lesson-99\.srt.*SRT Files.*npm run build/)
      return true
    })
  }

  const malformed = { lessons: [{ lesson: 99, videoId: 'AAAAAAAAAAA', title: 'Test', file: 'lesson-99.srt' }] }
  const read = async (path) => (path === LESSONS_PATH ? JSON.stringify(malformed) : cases[1][0])
  const error = await loadBundledSubtitle('AAAAAAAAAAA', read).catch((e) => e)
  assert.ok(error instanceof BundledSubtitleError)
  const f = flow({ bundledError: error })
  assert.equal(await f.run('AAAAAAAAAAA'), 'youtube')
  assert.match(f.patches[0].subtitleError, /block 2 ends before it starts/)
})

test('a bundled SRT the backend rejects is reported, and YouTube captions are tried next', async () => {
  const bundled = { title: 'Lesson 17 — Learn Articles a / an / the', filename: 'lesson-17.srt', text: GOOD_SRT }
  const f = flow({ bundled, backendRejects: true })
  assert.equal(await f.run('r_yUCo0SL3A'), 'youtube')
  assert.deepEqual(f.calls.map((c) => c[0]), ['loadBundled', 'buildPlan', 'discover'])
  const last = f.patches.at(-1)
  assert.equal(last.source, null, 'the rejected lesson is no longer claimed as the source')
  assert.match(last.subtitleError, /rejected bundled subtitle lesson-17\.srt: Subtitle block 3 ends before it starts/)
})

test('a manually selected file overrides automatic loading for that video in this tab', async () => {
  const bundled = await loadBundledSubtitle(LESSON_1, readExtensionText)
  const manual = { videoId: LESSON_1, name: 'my-edit.srt', text: GOOD_SRT, filename: 'captions.vtt' }

  // Every later preparation of the same video (Retry, navigating back) keeps the viewer's file.
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const f = flow({ bundled, manual })
    assert.equal(await f.run(LESSON_1), 'manual')
    assert.deepEqual(f.calls, [['buildPlan', 'captions.vtt', GOOD_SRT]], 'the bundled lesson is not even read')
    assert.equal(subtitleSourceText(f.patches[0].source), 'Using manually selected subtitle file')
  }

  // It belongs to the video it was picked on: another lesson still loads its bundled file.
  const other = flow({ bundled, manual })
  assert.equal(await other.run('iJt12OE3c7k'), 'bundled')
})

test('a manual pick made while the bundled lesson is loading wins', async () => {
  let current = true
  const bundled = await loadBundledSubtitle(LESSON_1, readExtensionText)
  const f = flow({ bundled })
  const result = await f.run(LESSON_1, {
    loadBundled: async () => { current = false; return bundled }, // the viewer picks a file meanwhile
    isCurrent: () => current,
  })
  assert.equal(result, 'superseded')
  assert.deepEqual(f.calls, [], 'the bundled lesson is neither planned nor followed by discovery')
  assert.deepEqual(f.patches, [])
})

test('the overlay names each caption source', () => {
  assert.equal(subtitleSourceText({ kind: 'bundled', title: 'Lesson 3 — Learn Singular and Plural Nouns +s +es' }),
    'Using bundled lesson subtitle: Lesson 3 — Learn Singular and Plural Nouns +s +es')
  assert.equal(subtitleSourceText({ kind: 'youtube' }), 'Using YouTube captions')
  assert.equal(subtitleSourceText({ kind: 'manual', name: 'x.srt' }), 'Using manually selected subtitle file')
  assert.equal(subtitleSourceText(null), '')
})
