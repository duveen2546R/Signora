import assert from 'node:assert/strict'
import test from 'node:test'
import {
  cuesToVtt,
  formatVttTimestamp,
  parseJson3,
  parseTimedTextXml,
  timedTextToVtt,
} from '../src/captions/convert.js'

test('formats VTT timestamps the backend regex accepts', () => {
  assert.equal(formatVttTimestamp(0), '00:00:00.000')
  assert.equal(formatVttTimestamp(1500), '00:00:01.500')
  assert.equal(formatVttTimestamp(61_000), '00:01:01.000')
  assert.equal(formatVttTimestamp(3_661_123), '01:01:01.123')
  assert.equal(formatVttTimestamp(-5), '00:00:00.000')
})

test('parses JSON3 events and joins their segments', () => {
  const cues = parseJson3({
    events: [
      { tStartMs: 1000, dDurationMs: 2000, segs: [{ utf8: 'hello' }, { utf8: ' father' }] },
      { tStartMs: 4000, dDurationMs: 1500, segs: [{ utf8: 'good morning' }] },
    ],
  })
  assert.equal(cues.length, 2)
  assert.deepEqual(cues[0], { startMs: 1000, endMs: 3000, text: 'hello father' })
  assert.equal(cues[1].text, 'good morning')
})

test('drops rolling aAppend duplicates from auto-generated tracks', () => {
  const cues = parseJson3({
    events: [
      { tStartMs: 0, dDurationMs: 1000, segs: [{ utf8: 'hello' }] },
      { tStartMs: 1000, dDurationMs: 10, aAppend: 1, segs: [{ utf8: '\n' }] },
      { tStartMs: 1010, dDurationMs: 1000, segs: [{ utf8: 'father' }] },
    ],
  })
  assert.deepEqual(cues.map((c) => c.text), ['hello', 'father'])
})

test('ignores blank, whitespace-only and segment-less events', () => {
  const cues = parseJson3({
    events: [
      { tStartMs: 0, dDurationMs: 500, segs: [{ utf8: '   ' }] },
      { tStartMs: 500, dDurationMs: 500 },
      { tStartMs: 1000, dDurationMs: 500, segs: [{ utf8: '\n' }] },
      { tStartMs: 1500, dDurationMs: 500, segs: [{ utf8: 'real' }] },
    ],
  })
  assert.deepEqual(cues.map((c) => c.text), ['real'])
})

test('collapses caption line breaks into one spaced line', () => {
  const [cue] = parseJson3({
    events: [{ tStartMs: 0, dDurationMs: 900, segs: [{ utf8: 'thank\n  you' }] }],
  })
  assert.equal(cue.text, 'thank you')
})

test('gives a missing duration an implied one from the next cue', () => {
  const cues = parseJson3({
    events: [
      { tStartMs: 0, segs: [{ utf8: 'one' }] },
      { tStartMs: 2000, dDurationMs: 1000, segs: [{ utf8: 'two' }] },
    ],
  })
  assert.equal(cues[0].endMs, 2000)
  assert.ok(cues[0].endMs > cues[0].startMs)
})

test('every produced cue has a strictly positive duration even when events overlap', () => {
  // The backend rejects the whole subtitle file on one non-positive cue, so this is the
  // invariant that matters most.
  const cues = parseJson3({
    events: [
      { tStartMs: 1000, dDurationMs: 5000, segs: [{ utf8: 'long' }] },
      { tStartMs: 1200, dDurationMs: 5000, segs: [{ utf8: 'overlapping' }] },
      { tStartMs: 1200, dDurationMs: 0, segs: [{ utf8: 'zero length' }] },
    ],
  })
  assert.ok(cues.length >= 3)
  for (const cue of cues) assert.ok(cue.endMs > cue.startMs, `${cue.text} has no duration`)
})

test('sorts out-of-order events by start time', () => {
  const cues = parseJson3({
    events: [
      { tStartMs: 5000, dDurationMs: 500, segs: [{ utf8: 'second' }] },
      { tStartMs: 1000, dDurationMs: 500, segs: [{ utf8: 'first' }] },
    ],
  })
  assert.deepEqual(cues.map((c) => c.text), ['first', 'second'])
})

test('parses srv3 XML with millisecond attributes', () => {
  const cues = parseTimedTextXml(
    '<timedtext><body>'
    + '<p t="1000" d="2000"><s>hello</s><s> father</s></p>'
    + '<p t="4000" d="1000"><s>again</s></p>'
    + '</body></timedtext>',
  )
  assert.equal(cues.length, 2)
  assert.deepEqual(cues[0], { startMs: 1000, endMs: 3000, text: 'hello father' })
})

test('parses legacy XML with second-based attributes and decodes entities', () => {
  const cues = parseTimedTextXml(
    '<transcript>'
    + '<text start="1.5" dur="2.0">it&amp;#39;s &amp;quot;here&amp;quot;</text>'
    + '</transcript>',
  )
  assert.equal(cues.length, 1)
  assert.equal(cues[0].startMs, 1500)
  assert.equal(cues[0].endMs, 3500)
  assert.ok(cues[0].text.includes('&'))
})

test('decodes numeric and named entities', () => {
  const [cue] = parseTimedTextXml('<transcript><text start="0" dur="1">a &lt;b&gt; &#65;</text></transcript>')
  assert.equal(cue.text, 'a <b> A')
})

test('renders a WEBVTT document with numbered cues', () => {
  const vtt = cuesToVtt([{ startMs: 1000, endMs: 3000, text: 'hello father' }])
  const lines = vtt.split('\n')
  assert.equal(lines[0], 'WEBVTT')
  assert.equal(lines[1], '')
  assert.equal(lines[2], '1')
  assert.equal(lines[3], '00:00:01.000 --> 00:00:03.000')
  assert.equal(lines[4], 'hello father')
})

test('timedTextToVtt detects JSON3, XML and parsed-object inputs', () => {
  const json = JSON.stringify({ events: [{ tStartMs: 0, dDurationMs: 1000, segs: [{ utf8: 'hi' }] }] })
  assert.equal(timedTextToVtt(json).format, 'json3')
  assert.equal(timedTextToVtt(JSON.parse(json)).format, 'json3')
  assert.equal(timedTextToVtt('<transcript><text start="0" dur="1">hi</text></transcript>').format, 'xml')
})

test('timedTextToVtt throws on empty or textless payloads instead of returning a blank file', () => {
  // An empty body is exactly what YouTube returns when it refuses to serve timed text, so this
  // must surface as an error the overlay can report, never as a zero-cue subtitle upload.
  assert.throws(() => timedTextToVtt(''), /no usable spoken cues/)
  assert.throws(() => timedTextToVtt('{"events":[]}'), /no usable spoken cues/)
  assert.throws(() => timedTextToVtt('<transcript></transcript>'), /no usable spoken cues/)
})

test('preserves a repeated word as separate timed cues', () => {
  // Repeated-occurrence handling is the backend's job, but the conversion must not dedupe.
  const cues = parseJson3({
    events: [
      { tStartMs: 0, dDurationMs: 900, segs: [{ utf8: 'again' }] },
      { tStartMs: 1000, dDurationMs: 900, segs: [{ utf8: 'again' }] },
    ],
  })
  assert.equal(cues.length, 2)
  assert.notEqual(cues[0].startMs, cues[1].startMs)
})

test('handles a caption unit with many words, not just three', () => {
  const words = ['hello', 'father', 'good', 'morning', 'again', 'all', 'age', 'answer',
    'able', 'action', 'after', 'agree', 'always']
  const [cue] = parseJson3({
    events: [{ tStartMs: 0, dDurationMs: 6000, segs: [{ utf8: words.join(' ') }] }],
  })
  assert.equal(cue.text.split(' ').length, words.length)
  assert.ok(words.length > 3, 'the fixture must be longer than the old three-sign limit')
  assert.equal(cue.text, words.join(' '), 'no words are dropped or reordered')
})
