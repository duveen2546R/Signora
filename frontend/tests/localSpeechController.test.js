import test from 'node:test'
import assert from 'node:assert/strict'
import { createLocalSpeechController, localSpeechUrl } from '../src/components/localSpeechController.js'

function environment({ denied = false } = {}) {
  const sockets = [], tracks = [], nodes = []
  class Socket {
    constructor() { this.readyState = 1; this.bufferedAmount = 0; this.sent = []; sockets.push(this); queueMicrotask(() => this.onopen?.()) }
    send(value) {
      this.sent.push(value)
      if (typeof value === 'string' && JSON.parse(value).type === 'start') {
        this.identity = JSON.parse(value)
        queueMicrotask(() => this.event({ type: 'ready' }))
      }
    }
    event(value) { this.onmessage?.({ data: JSON.stringify({ streamId: 's', generation: 1, ...value }) }) }
    close() { this.readyState = 3 }
  }
  class Context {
    audioWorklet = { addModule: async () => {} }
    async resume() {}
    async close() {}
    createMediaStreamSource() { return { connect() {} } }
    createGain() { return { gain: {}, connect() {} } }
  }
  class Node {
    constructor() { nodes.push(this); this.port = { postMessage: () => this.port.onmessage({ data: { stopped: true } }) } }
    connect() { return { connect() {} } }
    disconnect() {}
  }
  return { sockets, tracks, nodes, scope: {
    location: { href: 'http://localhost:5173/sign' }, WebSocket: Socket, AudioContext: Context, AudioWorkletNode: Node,
    navigator: { mediaDevices: { getUserMedia: async () => {
      if (denied) throw Object.assign(new Error(), { name: 'NotAllowedError' })
      const track = { stopped: false, stop() { this.stopped = true } }
      tracks.push(track)
      return { getTracks: () => [track] }
    } } },
  } }
}
const start = { streamId: 's', generation: 1, libraryVersion: 'v' }

test('websocket URL respects HTTPS and configured backend', () => {
  assert.equal(localSpeechUrl('/api/v1', { href: 'https://example.test/sign' }), 'wss://example.test/api/v1/live/session')
})

test('local controller uses audio offsets, stop drains final events and clear ignores late results', async () => {
  const env = environment(), commits = [], states = []
  const controller = createLocalSpeechController({ onCommit: (...args) => commits.push(args), onState: state => states.push(state) }, env)
  await controller.start(start)
  const socket = env.sockets[0]
  socket.event({ type: 'transcript', text: 'hello', final: false })
  assert.equal(commits.length, 0)
  socket.event({ type: 'commit', text: 'hello', words: [{}], sourceStartMs: 100, sourceEndMs: 400, observedAudioMs: 500 })
  assert.equal(commits.length, 1)
  assert.equal(commits[0][1].sourceEndAt - commits[0][1].sourceStartAt, 300)
  controller.stop()
  assert.equal(JSON.parse(socket.sent.at(-1)).type, 'stop')
  assert.equal(env.tracks[0].stopped, true)
  socket.event({ type: 'commit', text: 'father', words: [{}], sourceEndMs: 800, observedAudioMs: 900 })
  assert.equal(commits.length, 2)
  const late = socket.onmessage
  controller.cancel()
  late({ data: JSON.stringify({ type: 'commit', streamId: 's', generation: 1, text: 'late', words: [] }) })
  assert.equal(commits.length, 2)
  assert.equal(states.at(-1), 'stopped')
})

test('permission denial releases socket and exposes error', async () => {
  const env = environment({ denied: true }), errors = []
  const controller = createLocalSpeechController({ onError: message => errors.push(message) }, env)
  await controller.start(start)
  assert.match(errors[0], /permission/)
  assert.equal(env.sockets[0].readyState, 3)
})

test('device failure and transport backlog stop capture without silently dropping packets', async () => {
  for (const cause of ['device', 'backlog']) {
    const env = environment(), errors = []
    const controller = createLocalSpeechController({ onError: message => errors.push(message) }, env)
    await controller.start(start)
    if (cause === 'device') env.tracks[0].onended()
    else { env.sockets[0].bufferedAmount = 70000; env.nodes[0].port.onmessage({ data: new ArrayBuffer(652) }) }
    assert.equal(errors.length, 1)
    assert.equal(env.tracks[0].stopped, true)
    assert.equal(env.sockets[0].readyState, 3)
  }
})

test('out-of-order responses resolve the correct request; cancellation rejects pending requests', async () => {
  const env = environment()
  const controller = createLocalSpeechController({}, env)
  await controller.start(start)
  const a = controller.request('translate', {}), b = controller.request('close', {})
  env.sockets[0].event({ type: 'response', requestId: 2, value: 'b' })
  env.sockets[0].event({ type: 'response', requestId: 1, value: 'a' })
  assert.deepEqual(await Promise.all([a, b]), ['a', 'b'])
  const pending = controller.request('translate', {})
  controller.cancel()
  await assert.rejects(pending, /cancelled/)
})
