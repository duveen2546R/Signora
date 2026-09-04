import assert from 'node:assert/strict'
import test from 'node:test'

import { blendNotices, playableTrack } from './blendQuality.js'

test('a rejected composition never exposes a playable track', () => {
  assert.equal(playableTrack({ track: null, error: 'blend rejected' }), null)
})

test('neutral fallback and capture warnings are visible', () => {
  const notices = blendNotices({
    blendQuality: { status: 'neutral-fallback' },
    warnings: ['The skeleton proportions differ.'],
  })
  assert.equal(notices.length, 2)
  assert.match(notices[0], /neutral-pose bridge/)
  assert.match(notices[1], /skeleton proportions/)
})
