/**
 * Copy the shared scheduler from the frontend into extension/vendor/ verbatim.
 *
 * The extension is an unbundled MV3 package and cannot reach outside its own directory at
 * runtime, so the file has to physically exist under extension/. Copying it rather than
 * rewriting it - and asserting byte equality in extension/tests/vendor-sync.test.js - is what
 * keeps a second, divergent scheduler from quietly appearing.
 *
 * Usage:  node extension/tools/sync-vendor.mjs [--check]
 *   --check exits non-zero instead of writing, for CI.
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, '..', '..')

export const VENDORED = [
  {
    from: resolve(repoRoot, 'frontend/src/video/YouTubeSignScheduler.js'),
    to: resolve(repoRoot, 'extension/vendor/YouTubeSignScheduler.js'),
  },
]

const check = process.argv.includes('--check')
let drift = 0

for (const { from, to } of VENDORED) {
  const source = await readFile(from, 'utf8')
  const current = existsSync(to) ? await readFile(to, 'utf8') : null
  if (current === source) {
    console.log(`up to date: ${to.replace(repoRoot, '.')}`)
    continue
  }
  if (check) {
    console.error(`DRIFT: ${to.replace(repoRoot, '.')} differs from ${from.replace(repoRoot, '.')}`)
    drift += 1
    continue
  }
  await mkdir(dirname(to), { recursive: true })
  await writeFile(to, source, 'utf8')
  console.log(`synced:  ${from.replace(repoRoot, '.')} -> ${to.replace(repoRoot, '.')}`)
}

if (drift) {
  console.error('\nRun `node extension/tools/sync-vendor.mjs` to resynchronise.')
  process.exit(1)
}
