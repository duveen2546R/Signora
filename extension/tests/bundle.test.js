/**
 * Guards the loader bug that reached a real browser: the content script previously used
 * `import(chrome.runtime.getURL('src/main.js'))`, which Chrome rejects on youtube.com with
 * "Unsafe attempt to load URL ... Domains, protocols and ports must match".
 *
 * These tests evaluate the *generated bundle* the same way Chrome does - as one classic script
 * in a page-like global - and assert it wires itself up and boots. A regression here means the
 * extension silently does nothing on YouTube, which is exactly what happened before.
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import { execFileSync } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { createContext, runInContext } from 'node:vm'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const extensionRoot = resolve(here, '..')
const BUNDLE = resolve(extensionRoot, 'dist/content.bundle.js')

/** Minimal DOM/extension surface: only what the bundle actually touches. */
function makeSandbox({ href = 'https://www.youtube.com/watch?v=oK6LGQY_7A4' } = {}) {
  const created = []
  const warnings = []

  const makeElement = (tag) => {
    const element = {
      tagName: String(tag).toUpperCase(),
      style: {}, children: [], hidden: false,
      innerHTML: '', textContent: '', className: '', id: '',
      files: null, firstElementChild: null,
      setAttribute() {}, addEventListener() {}, removeEventListener() {},
      appendChild(child) { this.children.push(child); return child },
      remove() {}, click() {},
      attachShadow() {
        const shadow = {
          innerHTML: '',
          getElementById: () => makeElement('div'),
        }
        element.shadowRoot = shadow
        return shadow
      },
    }
    created.push(element)
    return element
  }

  const video = {
    currentTime: 0, playbackRate: 1, duration: 57, paused: true, ended: false,
    readyState: 4,
    addEventListener() {}, removeEventListener() {},
    pause() { this.paused = true }, play() { this.paused = false; return Promise.resolve() },
  }

  const url = new URL(href)
  const sandbox = {
    console: { log() {}, warn: (...a) => warnings.push(a.join(' ')), error() {} },
    setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask,
    performance, URL, Promise, Error, Object, Array, JSON, Math, Number, String, Boolean, Set, Map,
    fetch: async () => ({ ok: false, status: 503, statusText: 'stub', json: async () => ({}) }),
    location: { href, pathname: url.pathname, origin: url.origin, search: url.search },
    document: {
      documentElement: makeElement('html'),
      createElement: makeElement,
      querySelector: () => video,
      getElementById: () => null,
      addEventListener() {}, removeEventListener() {},
      hidden: false,
    },
    chrome: {
      runtime: {
        lastError: null,
        getURL: (p) => `chrome-extension://test/${p}`,
        // Always report the backend as unreachable; this test is about wiring, not the backend.
        sendMessage: (_message, reply) => reply({ ok: false, error: 'stub offline', offline: true }),
      },
      storage: { sync: { get: async () => ({}) } },
    },
    _created: created,
    _warnings: warnings,
    _video: video,
  }
  // The bundle registers SPA-navigation listeners on `window`.
  sandbox.addEventListener = () => {}
  sandbox.removeEventListener = () => {}
  sandbox.postMessage = () => {}
  sandbox.window = sandbox
  sandbox.globalThis = sandbox
  sandbox.self = sandbox
  return sandbox
}

test('the committed bundle is up to date with the ES module sources', () => {
  // A stale bundle means Chrome runs different code from what the other tests cover.
  execFileSync(process.execPath, [resolve(extensionRoot, 'tools/build.mjs'), '--check'], {
    stdio: 'pipe',
  })
})

test('the bundle contains no ESM syntax Chrome would reject in a content script', async () => {
  const source = await readFile(BUNDLE, 'utf8')
  assert.equal(/^\s*import\s/m.test(source), false, 'top-level import survived bundling')
  assert.equal(/^\s*export\s/m.test(source), false, 'top-level export survived bundling')
  assert.equal(
    /import\s*\(/.test(source), false,
    'dynamic import() survived - this is the exact call Chrome rejected on youtube.com',
  )
})

test('every module resolves and the bundle boots on a watch page', async () => {
  const source = await readFile(BUNDLE, 'utf8')
  const sandbox = makeSandbox()
  createContext(sandbox)

  assert.doesNotThrow(
    () => runInContext(source, sandbox, { filename: 'content.bundle.js' }),
    'bundle threw while evaluating',
  )

  // Let the async start() settle far enough to build the overlay.
  await new Promise((r) => setTimeout(r, 50))

  const missing = sandbox._warnings.filter((w) => w.includes('missing module'))
  assert.deepEqual(missing, [], `unresolved modules: ${missing.join(', ')}`)

  const host = sandbox._created.find((el) => el.id === 'signora-overlay-host')
  assert.ok(host, 'the overlay host element was never created - boot() did not run')
  assert.ok(host.shadowRoot, 'the overlay did not attach a shadow root')
})

test('the bundle does nothing on a non-watch YouTube page', async () => {
  const source = await readFile(BUNDLE, 'utf8')
  const sandbox = makeSandbox({ href: 'https://www.youtube.com/feed/subscriptions' })
  createContext(sandbox)
  runInContext(source, sandbox, { filename: 'content.bundle.js' })
  await new Promise((r) => setTimeout(r, 30))

  const host = sandbox._created.find((el) => el.id === 'signora-overlay-host')
  assert.equal(host, undefined, 'the overlay must not mount outside a watch page')
})

test('the bundle is idempotent if injected twice', async () => {
  const source = await readFile(BUNDLE, 'utf8')
  const sandbox = makeSandbox()
  createContext(sandbox)
  runInContext(source, sandbox, { filename: 'content.bundle.js' })
  runInContext(source, sandbox, { filename: 'content.bundle.js' })
  await new Promise((r) => setTimeout(r, 50))

  const hosts = sandbox._created.filter((el) => el.id === 'signora-overlay-host')
  assert.equal(hosts.length, 1, 'a second injection must not mount a second overlay')
})

test('the manifest points at the generated bundle, not an ESM entry', async () => {
  const manifest = JSON.parse(await readFile(resolve(extensionRoot, 'manifest.json'), 'utf8'))
  const isolated = manifest.content_scripts.find((c) => c.world !== 'MAIN')
  assert.ok(isolated, 'no isolated-world content script declared')
  assert.deepEqual(
    isolated.js, ['dist/content.bundle.js'],
    'the isolated content script must load the bundle',
  )
})
