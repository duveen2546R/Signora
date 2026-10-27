/**
 * Bundle the ES-module sources into one classic content script.
 *
 * Why this exists: a content script declared in the manifest is a classic script, and
 * `import(chrome.runtime.getURL(...))` from the isolated world is rejected on youtube.com with
 * "Unsafe attempt to load URL ... Domains, protocols and ports must match". Module specifiers in
 * a content script resolve against the *page* origin, and web_accessible_resources does not
 * change that. So the modules are concatenated ahead of time into a single IIFE.
 *
 * The ES modules under src/ and vendor/ stay the single source of truth - `node --test` runs
 * against them directly. dist/content.bundle.js is generated output and is never hand-edited.
 *
 * This is a deliberately small, dependency-free transform for a module graph this repository
 * controls: static imports only, no circular dependencies, no dynamic import, no re-exports,
 * no `import * as`. tools/build.mjs throws if it meets anything outside that subset rather than
 * emitting a silently wrong bundle.
 *
 * Usage: node extension/tools/build.mjs [--check]
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { dirname, posix, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '..')
const ENTRY = 'src/main.js'
const OUT = resolve(root, 'dist/content.bundle.js')

const key = (absolute) => relative(root, absolute).split('\\').join('/')

const IMPORT_RE = /^[ \t]*import\s+([^'"]+?)\s+from\s*['"]([^'"]+)['"][ \t]*;?[ \t]*$/gm
const BARE_IMPORT_RE = /^[ \t]*import\s*['"]([^'"]+)['"][ \t]*;?[ \t]*$/gm

/** Collect the module graph depth-first so dependencies are emitted before dependents. */
async function collect(entryKey, seen = new Map(), order = []) {
  if (seen.has(entryKey)) return { seen, order }
  const absolute = resolve(root, entryKey)
  const source = await readFile(absolute, 'utf8')
  seen.set(entryKey, source)

  for (const guard of [/\bimport\s*\(/, /\bexport\s+\*/, /\bimport\s*\*\s*as\b/]) {
    if (guard.test(source)) {
      throw new Error(`${entryKey}: unsupported syntax for this bundler (${guard}).`)
    }
  }

  const deps = []
  for (const match of source.matchAll(IMPORT_RE)) deps.push(match[2])
  for (const match of source.matchAll(BARE_IMPORT_RE)) deps.push(match[1])

  for (const specifier of deps) {
    if (!specifier.startsWith('.')) throw new Error(`${entryKey}: bare specifier "${specifier}" is not supported.`)
    const depKey = key(resolve(dirname(absolute), specifier))
    await collect(depKey, seen, order)
  }
  order.push(entryKey)
  return { seen, order }
}

/** Rewrite one module's import/export statements into registry calls. */
function transform(moduleKey, source) {
  let out = source

  out = out.replace(IMPORT_RE, (_full, clause, specifier) => {
    const depKey = key(resolve(dirname(resolve(root, moduleKey)), specifier))
    const ref = `__req(${JSON.stringify(depKey)})`
    const text = clause.trim()

    // `import Default, { a, b as c } from '...'`
    const combined = /^([A-Za-z_$][\w$]*)\s*,\s*\{([\s\S]*)\}$/.exec(text)
    if (combined) {
      return `const ${combined[1]} = ${ref}.default; const {${combined[2]}} = ${ref};`
    }
    // `import { a, b as c } from '...'`
    if (text.startsWith('{')) {
      return `const ${text} = ${ref};`
    }
    // `import Default from '...'`
    return `const ${text} = ${ref}.default;`
  })

  out = out.replace(BARE_IMPORT_RE, (_full, specifier) => {
    const depKey = key(resolve(dirname(resolve(root, moduleKey)), specifier))
    return `__req(${JSON.stringify(depKey)});`
  })

  // `export default class X` / `export default function X` keep their binding, then register it.
  const defaults = []
  out = out.replace(/^[ \t]*export\s+default\s+(class|function)\s+([A-Za-z_$][\w$]*)/gm, (_f, kind, name) => {
    defaults.push(name)
    return `${kind} ${name}`
  })

  // Named declarations: export (const|let|function|async function|class) NAME
  const named = []
  out = out.replace(
    /^[ \t]*export\s+(?!default\b)(async\s+function|function|class|const|let|var)\s+([A-Za-z_$][\w$]*)/gm,
    (_f, kind, name) => {
      named.push(name)
      return `${kind} ${name}`
    },
  )

  if (/^[ \t]*export\b/m.test(out)) {
    const leftover = (/^[ \t]*export\b.*$/m.exec(out) || [''])[0].trim()
    throw new Error(`${moduleKey}: unsupported export form -> ${leftover}`)
  }

  const registrations = [
    ...named.map((name) => `  __x.${name} = ${name};`),
    ...defaults.map((name) => `  __x.default = ${name};`),
  ].join('\n')

  return `__def(${JSON.stringify(moduleKey)}, function (__x, __req) {\n${out}\n${registrations}\n});`
}

const BOOTSTRAP = `
  // Entry: only act on a watch page, and survive YouTube's SPA navigation.
  var __start = function () {
    try { __req(${JSON.stringify(ENTRY)}).boot(); }
    catch (e) { console.warn('[signora] failed to start:', e); }
  };
  var __isWatch = function () {
    try {
      return location.pathname === '/watch'
        && new URL(location.href).searchParams.has('v');
    } catch (e) { return false; }
  };
  try {
    if (__isWatch()) {
      __start();
    } else {
      var __onNav = function () {
        if (!__isWatch()) return;
        window.removeEventListener('yt-navigate-finish', __onNav);
        window.removeEventListener('popstate', __onNav);
        __start();
      };
      window.addEventListener('yt-navigate-finish', __onNav);
      window.addEventListener('popstate', __onNav);
    }
  } catch (e) {
    console.warn('[signora] bootstrap failed:', e);
  }
`

async function build() {
  const { seen, order } = await collect(ENTRY)
  const parts = order.map((moduleKey) => transform(moduleKey, seen.get(moduleKey)))

  return `/* GENERATED by extension/tools/build.mjs - do not edit.
 * Sources: extension/src/**, extension/vendor/**  (edit those, then re-run the builder)
 * Modules, in dependency order:
 *   ${order.join('\n *   ')}
 */
(function () {
  'use strict';
  if (window.__signoraBundleLoaded) return;
  window.__signoraBundleLoaded = true;

  var __registry = Object.create(null);
  var __cache = Object.create(null);
  function __def(name, factory) { __registry[name] = factory; }
  function __req(name) {
    if (__cache[name]) return __cache[name];
    var factory = __registry[name];
    if (!factory) throw new Error('[signora] missing module: ' + name);
    var exports = {};
    __cache[name] = exports;
    factory(exports, __req);
    return exports;
  }

${parts.join('\n\n')}

${BOOTSTRAP}
})();
`
}

const bundle = await build()
const check = process.argv.includes('--check')
const current = existsSync(OUT) ? await readFile(OUT, 'utf8') : null

if (current === bundle) {
  console.log('up to date: extension/dist/content.bundle.js')
} else if (check) {
  console.error('DRIFT: extension/dist/content.bundle.js is stale.')
  console.error('Run: node extension/tools/build.mjs')
  process.exit(1)
} else {
  await mkdir(dirname(OUT), { recursive: true })
  await writeFile(OUT, bundle, 'utf8')
  console.log(`built:   extension/dist/content.bundle.js (${(bundle.length / 1024).toFixed(1)} kB)`)
}
