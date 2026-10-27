import assert from 'node:assert/strict'
import test from 'node:test'
import { applyPhysicalTextKey } from './physicalTextInput.js'

test('inserts a physical key at the caret', () => {
  assert.deepEqual(applyPhysicalTextKey('helo', 'l', 3, 3), { text: 'hello', caret: 4 })
})

test('replaces the current selection', () => {
  assert.deepEqual(applyPhysicalTextKey('hello earth', 'w', 6, 11), { text: 'hello w', caret: 7 })
})

test('supports backspace and forward delete', () => {
  assert.deepEqual(applyPhysicalTextKey('helllo', 'Backspace', 4, 4), { text: 'hello', caret: 3 })
  assert.deepEqual(applyPhysicalTextKey('helllo', 'Delete', 3, 3), { text: 'hello', caret: 3 })
})

test('leaves navigation and composition keys to the browser', () => {
  assert.equal(applyPhysicalTextKey('hello', 'ArrowLeft', 5, 5), null)
  assert.equal(applyPhysicalTextKey('hello', 'Process', 5, 5), null)
})
