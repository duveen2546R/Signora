import assert from 'node:assert/strict'
import test from 'node:test'

import { filterSigns } from './signSearch.js'

const signs = [
  { gloss: 'GOOD_MORNING' },
  { gloss: 'YOU_RE' },
  { gloss: 'FATHER' },
]

test('finds a gloss with ordinary spaces instead of filename underscores', () => {
  assert.deepEqual(filterSigns(signs, 'good morning'), [signs[0]])
})

test('ignores case and punctuation while searching', () => {
  assert.deepEqual(filterSigns(signs, "you're"), [signs[1]])
  assert.deepEqual(filterSigns(signs, 'FATHER'), [signs[2]])
})

test('keeps every sign visible for an empty search', () => {
  assert.equal(filterSigns(signs, '   '), signs)
})
