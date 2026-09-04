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

test('legacy automatic-phase messages are grouped into one advisory', () => {
  const notices = blendNotices({
    warnings: [
      'HELLO uses automatically detected phase boundaries; review it.',
      'NAMASTE uses automatically detected phase boundaries; review it.',
      'FATHER uses automatically detected phase boundaries; review it.',
    ],
  })
  assert.equal(notices.length, 1)
  assert.match(notices[0], /HELLO, NAMASTE, FATHER/)
  assert.match(notices[0], /safe full-motion fallback/)
})
