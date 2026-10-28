import assert from 'node:assert/strict'
import test from 'node:test'
import {
  describeReadiness,
  diffNewlyReady,
  isPlanTerminal,
  progressSummary,
  summarizeIssues,
} from '../src/plan/progressive.js'

const UNIT = (id, startMs, endMs, status, motionAvailable) => ({ id, startMs, endMs, status, motionAvailable })

test('isPlanTerminal recognises only ready and failed', () => {
  assert.equal(isPlanTerminal('ready'), true)
  assert.equal(isPlanTerminal('failed'), true)
  assert.equal(isPlanTerminal('pending'), false)
  assert.equal(isPlanTerminal('processing'), false)
})

test('diffNewlyReady reports only units that just transitioned', () => {
  const units = [
    UNIT(1, 0, 1000, 'literal-preview', true),
    UNIT(2, 1000, 2000, 'pending', false),
    UNIT(3, 2000, 3000, 'motion-rejected', false),
  ]
  const { newlyReady, readyIds } = diffNewlyReady(units, new Set())
  assert.deepEqual(newlyReady.map((u) => u.id), [1])
  assert.deepEqual([...readyIds], [1])
})

test('diffNewlyReady does not re-report an already-known unit', () => {
  const units = [UNIT(1, 0, 1000, 'literal-preview', true)]
  const { newlyReady } = diffNewlyReady(units, new Set([1]))
  assert.deepEqual(newlyReady, [])
})

test('diffNewlyReady picks up a unit that becomes ready on a later poll', () => {
  const first = [UNIT(1, 0, 1000, 'pending', false)]
  const { readyIds: afterFirst } = diffNewlyReady(first, new Set())
  assert.deepEqual([...afterFirst], [])

  const second = [UNIT(1, 0, 1000, 'literal-preview', true)]
  const { newlyReady, readyIds } = diffNewlyReady(second, afterFirst)
  assert.deepEqual(newlyReady.map((u) => u.id), [1])
  assert.deepEqual([...readyIds], [1])
})

test('describeReadiness: current unit ready -> signable', () => {
  const units = [UNIT(1, 1000, 4000, 'literal-preview', true)]
  const result = describeReadiness(2000, units, new Set([1]), 'ready')
  assert.equal(result.state, 'signable')
  assert.equal(result.unit.id, 1)
})

test('describeReadiness: current unit still composing -> buffering-current, not stuck forever', () => {
  // This is the exact case that produced the "stuck at 0/10" symptom: the viewer's playhead is
  // inside a caption window whose unit the backend has not finished composing yet.
  const units = [UNIT(1, 1000, 4000, 'pending', false)]
  const result = describeReadiness(2000, units, new Set(), 'processing')
  assert.equal(result.state, 'buffering-current')
  assert.equal(result.unit.id, 1)
})

test('describeReadiness: current unit settled with no sign -> unsignable, not buffering', () => {
  // The backend already gave a final, honest answer (e.g. motion-rejected or unsupported-unit);
  // reporting "buffering" here would imply it might still arrive, which it will not.
  const units = [UNIT(1, 1000, 4000, 'unsupported', false)]
  const result = describeReadiness(2000, units, new Set(), 'ready')
  assert.equal(result.state, 'unsignable')
})

test('describeReadiness: no current unit, but an upcoming one in the lookahead is still pending', () => {
  const units = [
    UNIT(1, 1000, 2000, 'literal-preview', true),
    UNIT(2, 5000, 6000, 'pending', false),
  ]
  const result = describeReadiness(3000, units, new Set([1]), 'processing', 2)
  assert.equal(result.state, 'buffering-lookahead')
  assert.deepEqual(result.units.map((u) => u.id), [2])
})

test('describeReadiness: lookahead respects the configured count', () => {
  const units = [
    UNIT(1, 5000, 6000, 'pending', false),
    UNIT(2, 7000, 8000, 'pending', false),
    UNIT(3, 9000, 10000, 'pending', false),
  ]
  const result = describeReadiness(0, units, new Set(), 'processing', 2)
  assert.equal(result.state, 'buffering-lookahead')
  assert.deepEqual(result.units.map((u) => u.id), [1, 2])
})

test('describeReadiness: nothing current and the plan already finished -> idle, not buffering', () => {
  const units = [UNIT(1, 1000, 2000, 'unsupported', false)]
  const result = describeReadiness(5000, units, new Set(), 'ready')
  assert.equal(result.state, 'idle')
})

test('describeReadiness: nothing current, plan still processing, but lookahead is already settled -> idle', () => {
  const units = [UNIT(1, 5000, 6000, 'unsupported', false)]
  const result = describeReadiness(0, units, new Set(), 'processing', 2)
  assert.equal(result.state, 'idle')
})

test('progressSummary counts settled and ready independently', () => {
  const units = [
    UNIT(1, 0, 1000, 'literal-preview', true),
    UNIT(2, 1000, 2000, 'motion-rejected', false),
    UNIT(3, 2000, 3000, 'pending', false),
  ]
  const summary = progressSummary(units, new Set([1]))
  assert.deepEqual(summary, { total: 3, settled: 2, ready: 1 })
})

test('summarizeIssues reports a rejected unit as its caption, never blaming innocent glosses', () => {
  // Before the fix, "Add all." being rejected (only the join into ADD failed) put
  // "ALL (motion rejected)" on screen although ALL plays fine on its own.
  const { notSigned } = summarizeIssues([{
    text: 'Add all.', glosses: ['ADD', 'ALL'], motionAvailable: false,
    issues: [{ code: 'motion-rejected', message: 'Cannot blend rest to ADD' }],
  }])
  assert.deepEqual(notSigned, ['“Add all.” (motion rejected)'])
  assert.ok(!notSigned.some((entry) => entry.includes('ALL (')))
})

test('summarizeIssues counts labelled fallbacks as playable, not as unsupported', () => {
  const { notSigned, fallbackUnits } = summarizeIssues([
    { text: 'Thank you.', glosses: ['THANKYOU'], motionAvailable: true,
      issues: [{ code: 'motion-fallback', blendStatus: 'reviewed-direct', message: '...' }] },
    { text: 'Hello.', glosses: ['HELLO'], motionAvailable: true, issues: [] },
  ])
  assert.deepEqual(notSigned, [])
  assert.equal(fallbackUnits, 1)
})

test('summarizeIssues still lists genuinely unsupported words', () => {
  const { notSigned } = summarizeIssues([{
    text: 'zebra quixotic', glosses: [], motionAvailable: false,
    issues: [{ code: 'unsupported-unit', sourceWords: ['zebra', 'quixotic'] }],
  }])
  assert.deepEqual(notSigned, ['zebra', 'quixotic'])
})
