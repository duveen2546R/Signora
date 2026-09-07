import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import useLiveSpeech from './useLiveSpeech'
import { speechWords } from './stableSpeech'

const CLOSE_DELAY_MS = 800

export default function LiveSignComposer({ disabled, activeOccurrence, onEnqueue, onCancelQueued, onClear }) {
  const enabled = import.meta.env.VITE_LIVE_SIGNING !== 'false'
  const [readiness, setReadiness] = useState(null)
  const [interim, setInterim] = useState('')
  const [finalText, setFinalText] = useState('')
  const [items, setItems] = useState([])
  const [notices, setNotices] = useState([])
  const [activity, setActivity] = useState('stopped')
  const [lagMs, setLagMs] = useState(0)
  const [dispatchMs, setDispatchMs] = useState(null)
  const [forms, setForms] = useState([])
  const [streamId] = useState(() => globalThis.crypto?.randomUUID?.() ?? `live-${Math.random()}`)
  const sequence = useRef(0)
  const generation = useRef(0)
  const tailClipId = useRef(null)
  const chain = useRef(Promise.resolve())
  const closeTimer = useRef(null)
  const closeToken = useRef(0)
  const closureEnqueued = useRef(false)
  const nextOccurrence = useRef(0)
  const lastCommitAt = useRef(null)
  const wordIntervalMs = useRef(500)

  const refreshReadiness = useCallback(() => api.liveReadiness().then((value) => {
    setReadiness(value)
    return value
  }).catch((error) => {
    setNotices([error.message])
    return null
  }), [])

  useEffect(() => { if (enabled) refreshReadiness() }, [enabled, refreshReadiness])
  useEffect(() => {
    let cancelled = false
    api.patterns().then((value) => {
      if (!cancelled) setForms(value.patterns.flatMap((pattern) => pattern.forms.map(speechWords)))
    }).catch(() => {})
    return () => { cancelled = true }
  }, [])
  useEffect(() => () => {
    generation.current += 1
    clearTimeout(closeTimer.current)
  }, [])
  useEffect(() => {
    const timer = setInterval(() => setLagMs(window.signsure?.queuedDurationMs?.() ?? 0), 500)
    return () => clearInterval(timer)
  }, [])

  const invalidateClosure = useCallback(() => {
    closeToken.current += 1
    if (closeTimer.current !== null) clearTimeout(closeTimer.current)
    closeTimer.current = null
    if (closureEnqueued.current) {
      const removed = onCancelQueued?.('live-closure') ?? 0
      if (!removed) tailClipId.current = null
      closureEnqueued.current = false
    }
  }, [onCancelQueued])

  const queueClose = useCallback((token, requestGeneration) => {
    const closeSequence = sequence.current++
    chain.current = chain.current.then(async () => {
      if (token !== closeToken.current || requestGeneration !== generation.current || tailClipId.current === null) return
      const value = await api.liveClose({
        streamId,
        sequence: closeSequence,
        fromClipId: tailClipId.current,
        libraryVersion: readiness.libraryVersion,
      })
      if (token !== closeToken.current || requestGeneration !== generation.current) return
      onEnqueue(value.motion, value.sequence, 'live-closure')
      closureEnqueued.current = true
    }).catch((error) => {
      if (requestGeneration === generation.current) setNotices([error.message])
    })
  }, [onEnqueue, readiness, streamId])

  const scheduleClose = useCallback((requestGeneration) => {
    const token = ++closeToken.current
    if (closeTimer.current !== null) clearTimeout(closeTimer.current)
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null
      queueClose(token, requestGeneration)
    }, CLOSE_DELAY_MS)
  }, [queueClose])

  const commitSpeech = useCallback((text, timing = {}) => {
    const phrase = text.trim()
    if (!phrase || !readiness) return
    invalidateClosure()
    setActivity('processing')
    const committedAt = performance.now()
    const count = timing.wordCount ?? speechWords(phrase).length
    if (lastCommitAt.current !== null) {
      const interval = (committedAt - lastCommitAt.current) / Math.max(count, 1)
      if (interval > 100 && interval < 2000) wordIntervalMs.current = .7 * wordIntervalMs.current + .3 * interval
    }
    lastCommitAt.current = committedAt
    const requestGeneration = generation.current
    const requestSequence = sequence.current++
    scheduleClose(requestGeneration)
    chain.current = chain.current.then(async () => {
      if (requestGeneration !== generation.current) return
      const tail = tailClipId.current
      const value = await api.liveTranslate({
        streamId,
        sequence: requestSequence,
        text: phrase,
        fromClipId: tail,
        libraryVersion: readiness.libraryVersion,
      })
      if (requestGeneration !== generation.current) return
      const offset = nextOccurrence.current
      const currentItems = (value.items ?? []).map((item) => ({ ...item, occurrenceIndex: item.occurrenceIndex + offset }))
      nextOccurrence.current += currentItems.length
      setItems((previous) => [...previous, ...currentItems].slice(-100))
      setNotices((value.issues ?? []).map((issue) => issue.message).filter(Boolean))
      if (value.motion && !value.error) {
        const motion = { ...value.motion,
          segments: value.motion.segments.map((segment) => ({ ...segment,
            ...(Number.isInteger(segment.occurrenceIndex) ? { occurrenceIndex: segment.occurrenceIndex + offset } : {}),
          })),
          liveTiming: { targetDurationMs: wordIntervalMs.current * count },
        }
        onEnqueue(motion, requestSequence, 'live-motion')
        setDispatchMs(performance.now() - (timing.observedAt ?? committedAt))
        tailClipId.current = value.tailClipId
        setActivity('signing')
      } else {
        setActivity('listening')
      }
    }).catch(async (error) => {
      if (requestGeneration !== generation.current) return
      if (error.status === 409) {
        tailClipId.current = null
        await refreshReadiness()
      }
      setNotices([error.message])
      setActivity('error')
    })
  }, [invalidateClosure, onEnqueue, readiness, refreshReadiness, scheduleClose, streamId])

  const handleInterim = useCallback((text) => {
    setInterim(text)
    if (text) invalidateClosure()
    scheduleClose(generation.current)
  }, [invalidateClosure, scheduleClose])
  const speech = useLiveSpeech({
    onCommit: commitSpeech, onInterim: handleInterim, forms,
    onFinal: (text) => setFinalText((previous) => `${previous} ${text}`.trim().slice(-4000)),
    onCorrection: (message) => setNotices((previous) => [...previous, message].slice(-5)),
  })

  function clear() {
    generation.current += 1
    speech.cancel()
    invalidateClosure()
    tailClipId.current = null
    chain.current = Promise.resolve()
    lastCommitAt.current = null
    setDispatchMs(null)
    setInterim('')
    setFinalText('')
    setItems([])
    setNotices([])
    setActivity('stopped')
    onClear()
  }

  if (!enabled) return null
  const missingCount = (readiness?.missingCoreGlosses?.length ?? 0) + (readiness?.missingAlphabetGlosses?.length ?? 0)
  const canListen = speech.supported && readiness?.usable && !disabled
  const displayedActivity = speech.error ? 'error'
    : speech.listening && activity === 'stopped' ? 'listening' : activity
  const displayedNotices = speech.error ? [speech.error, ...notices] : notices

  return (
    <section className="panel live-panel" aria-labelledby="live-sign-heading">
      <div className="panel__head">
        <div>
          <p className="label">Live microphone</p>
          <h2 id="live-sign-heading">Speak to sign</h2>
        </div>
        <span className={`status live-panel__status live-panel__status--${displayedActivity}`}>{displayedActivity}</span>
      </div>
      <div className="row">
        <button
          className="button"
          type="button"
          disabled={!canListen}
          onClick={() => {
            if (speech.listening) {
              speech.stop()
              setActivity('stopped')
            } else {
              speech.start()
              setActivity('listening')
            }
          }}
        >
          {speech.listening ? 'Stop listening' : 'Start listening'}
        </button>
        <button className="button button--ghost" type="button" onClick={clear}>Clear</button>
      </div>
      {!speech.supported && <p className="notice notice--bad">Live recognition needs Chrome desktop with the Web Speech API.</p>}
      <p className="hint">Fast mode signs stable words before the sentence ends and adjusts playback to your pace. Recognition can still correct early words.</p>
      {readiness && missingCount > 0 && (
        <p className="notice notice--warn">
          Preview library incomplete: {readiness.missingCoreGlosses.length} core and {readiness.missingAlphabetGlosses.length} alphabet recordings missing. Known phrases can still play.
        </p>
      )}
      <div className="live-transcript" aria-live="polite">
        <span>{finalText || 'Your finalized speech will appear here.'}</span>
        {interim && <em> {interim}</em>}
      </div>
      {dispatchMs !== null && <p className="hint">Transcript to queue: {Math.round(dispatchMs)} ms · buffered motion: {(lagMs / 1000).toFixed(1)}s</p>}
      {lagMs > 3000 && <p className="hint">Speech is ahead of signing. Playback is adjusting within the motion speed limit.</p>}
      {displayedNotices.map((notice) => <p className="notice notice--warn" key={notice}>{notice}</p>)}
      {items.length > 0 && (
        <ol className="chips">
          {items.map((item) => (
            <li
              className={`chip ${item.fingerspelled ? 'chip--spelled' : ''} ${item.occurrenceIndex === activeOccurrence ? 'chip--active' : ''}`}
              key={`${item.gloss}-${item.occurrenceIndex}`}
            >{item.gloss}</li>
          ))}
        </ol>
      )}
    </section>
  )
}
