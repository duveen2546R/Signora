import assert from 'node:assert/strict'
import test from 'node:test'

import { createSpeechController } from './useLiveSpeech.js'

class FakeRecognition {
  constructor() { FakeRecognition.instance = this }
  start() { this.starts = (this.starts ?? 0) + 1; this.onstart?.() }
  stop() { this.onend?.() }
  abort() {}
}

test('speech controller configures Chrome for continuous English phrase results', () => {
  const controller = createSpeechController(FakeRecognition, {})
  const recognition = controller.recognition
  assert.equal(recognition.lang, 'en-IN')
  assert.equal(recognition.continuous, true)
  assert.equal(recognition.interimResults, true)
  assert.equal(recognition.maxAlternatives, 1)
  controller.destroy()
})

test('interim revisions display but only final phrases commit', () => {
  const seen = { interim: [], final: [] }
  const controller = createSpeechController(FakeRecognition, {
    onInterim: (value) => seen.interim.push(value),
    onFinal: (value) => seen.final.push(value),
  })
  const recognition = controller.recognition
  const result = (text, isFinal) => Object.assign([{ transcript: text }], { isFinal })
  recognition.onresult({ resultIndex: 0, results: [result('hello fa', false)] })
  recognition.onresult({ resultIndex: 0, results: [result('hello father', false)] })
  recognition.onresult({ resultIndex: 0, results: [result('hello father', true)] })
  assert.deepEqual(seen.interim, ['hello fa', 'hello father', ''])
  assert.deepEqual(seen.final, ['hello father'])
  controller.destroy()
})

test('ordinary recognition endings restart while permission failures stop', async () => {
  const controller = createSpeechController(FakeRecognition, {}, 0)
  const recognition = controller.recognition
  controller.start()
  recognition.onend()
  await new Promise((resolve) => setTimeout(resolve, 5))
  assert.equal(recognition.starts, 2)
  recognition.onerror({ error: 'not-allowed' })
  recognition.onend()
  await new Promise((resolve) => setTimeout(resolve, 5))
  assert.equal(recognition.starts, 2)
  controller.destroy()
})
