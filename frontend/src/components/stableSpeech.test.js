import assert from 'node:assert/strict'
import test from 'node:test'
import { StableSpeechResult } from './stableSpeech.js'

test('starts from interim speech in under one second without waiting for final', () => {
  const result = new StableSpeechResult()
  result.update('hello', false, 0)
  assert.equal(result.take(349).text, '')
  assert.equal(result.take(350).text, 'hello')
  result.update('hello father', true, 3000)
  assert.equal(result.take(3000).text, 'father')
  assert.equal(result.take(3001).text, '')
})

test('changing last word does not indefinitely delay a stable prefix', () => {
  const result = new StableSpeechResult()
  result.update('hello fa', false, 0)
  result.update('hello fath', false, 100)
  result.update('hello father', false, 200)
  assert.equal(result.take(240).text, 'hello')
  assert.equal(result.take(550).text, 'father')
})

test('keeps multiword signs together with bounded phrase lookahead', () => {
  const result = new StableSpeechResult()
  const forms = [['good', 'morning']]
  result.update('good', false, 0)
  assert.equal(result.take(350, forms).text, '')
  result.update('good morning', false, 400)
  assert.equal(result.take(550, forms).text, '')
  assert.equal(result.take(750, forms).text, 'good morning')
  const whole = new StableSpeechResult()
  whole.update('good morning', false, 0)
  assert.equal(whole.take(350, forms).text, 'good morning')
})

test('revisions after commit are reported instead of replaying the utterance', () => {
  const result = new StableSpeechResult()
  result.update('father', false, 0)
  assert.equal(result.take(400).text, 'father')
  result.update('mother', true, 800)
  assert.equal(result.take(800).correction, true)
  assert.equal(result.take(800).text, '')
})

test('repeated words and a final-only event retain every occurrence', () => {
  const result = new StableSpeechResult()
  result.update('hello hello', true, 0)
  assert.equal(result.take(0).text, 'hello hello')
  assert.equal(result.take(1).text, '')
})
