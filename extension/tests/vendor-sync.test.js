/**
 * Guards against a second, divergent scheduler.
 *
 * The extension cannot import from frontend/src at runtime, so the scheduler is physically
 * copied into extension/vendor/. This test fails the moment the copy stops matching the
 * frontend original, which is what keeps "reuse" from silently decaying into "fork".
 *
 * Fix a failure with: node extension/tools/sync-vendor.mjs
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '..', '..')

const PAIRS = [
  ['frontend/src/video/YouTubeSignScheduler.js', 'extension/vendor/YouTubeSignScheduler.js'],
]

for (const [from, to] of PAIRS) {
  test(`${to} is byte-identical to ${from}`, async () => {
    const [source, vendored] = await Promise.all([
      readFile(resolve(repoRoot, from), 'utf8'),
      readFile(resolve(repoRoot, to), 'utf8'),
    ])
    assert.equal(
      vendored,
      source,
      `${to} has drifted. Run: node extension/tools/sync-vendor.mjs`,
    )
  })
}

test('the vendored scheduler exposes the API the extension depends on', async () => {
  const module = await import('../vendor/YouTubeSignScheduler.js')
  assert.equal(typeof module.default, 'function')
  assert.deepEqual(module.YT_STATE, { ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5 })
  for (const method of ['start', 'stop', 'tick', 'setPlayerState']) {
    assert.equal(typeof module.default.prototype[method], 'function', `missing ${method}`)
  }
})
