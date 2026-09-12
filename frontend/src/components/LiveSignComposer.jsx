import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import useLiveSpeech from './useLiveSpeech'
import useLocalSpeech from './useLocalSpeech'
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
  const [recognizer, setRecognizer] = useState('local')
  const [warming, setWarming] = useState(false)
  const [appliedMs, setAppliedMs] = useState(null)
  const [submittedMs, setSubmittedMs] = useState(null)
  const [rate, setRate] = useState('auto')
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
  const audioWindow = useRef([])
  const transport = useRef(null)
  const pendingMs = useRef(0)
  const tailRate = useRef(1)

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
    const timer = setInterval(() => setLagMs((window.signsure?.queuedDurationMs?.() ?? 0) + pendingMs.current), 250)
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
      const body = {
        streamId,
        sequence: closeSequence,
        fromClipId: tailClipId.current,
        libraryVersion: readiness.libraryVersion,
        streaming: recognizer === 'local', rate: tailRate.current,
        motionVersion: readiness.streaming?.publicationVersion,
        boundary: window.signsure?.isPlaying?.() ? 'flow' : 'held',
      }
      let value = await (transport.current ? transport.current('close', body) : api.liveClose(body))
      if (body.streaming && body.boundary === 'flow' && !window.signsure?.isPlaying?.()) {
        value = await transport.current('close', { ...body, boundary: 'held' })
      }
      if (token !== closeToken.current || requestGeneration !== generation.current) return
      onEnqueue(value.motion, value.sequence, 'live-closure')
      closureEnqueued.current = true
    }).catch((error) => {
      if (requestGeneration === generation.current) setNotices([error.message])
    })
  }, [onEnqueue, readiness, streamId, recognizer])

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
    if (Number.isFinite(timing.sourceEndAt)) {
      const previousEnd = audioWindow.current.at(-1)?.at
      audioWindow.current.push({ at: timing.sourceEndAt, count })
      audioWindow.current = audioWindow.current.filter((entry) => entry.at >= timing.sourceEndAt - 2000)
      const window = audioWindow.current
      if (window.length > 1) {
        const words = window.slice(1).reduce((sum, entry) => sum + entry.count, 0)
        wordIntervalMs.current = Math.max(100, Math.min(3000, (timing.sourceEndAt - window[0].at) / words))
      } else if (Number.isFinite(previousEnd)) {
        wordIntervalMs.current = Math.max(100, Math.min(10000, (timing.sourceEndAt - previousEnd) / count))
      }
    }
    lastCommitAt.current = committedAt
    const requestGeneration = generation.current
    const requestSequence = sequence.current++
    const reserveMs = Math.max(1000, count * 3000)
    pendingMs.current += reserveMs
    scheduleClose(requestGeneration)
    chain.current = chain.current.then(async () => {
      if (requestGeneration !== generation.current) return
      const tail = tailClipId.current
      const body = {
        streamId,
        sequence: requestSequence,
        text: phrase,
        fromClipId: tail,
        libraryVersion: readiness.libraryVersion,
        mode: 'literal',
        streaming: recognizer === 'local', rate: tail === null && rate !== 'auto' ? Number(rate) : tailRate.current,
        autoPace: rate === 'auto', targetDurationMs: Math.min(60000, wordIntervalMs.current * count),
        motionVersion: readiness.streaming?.publicationVersion,
        boundary: window.signsure?.isPlaying?.() ? 'flow' : 'held',
      }
      let value = await (transport.current ? transport.current('translate', body) : api.liveTranslate(body))
      if (body.streaming && body.fromClipId !== null && body.boundary === 'flow' && !window.signsure?.isPlaying?.()) {
        value = await transport.current('translate', { ...body, boundary: 'held' })
      }
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
          liveTiming: { targetDurationMs: wordIntervalMs.current * count,
            sourceEndAt: timing.sourceEndAt, desiredSignAt: Number.isFinite(timing.sourceEndAt) ? timing.sourceEndAt + 750 : null },
        }
        onEnqueue(motion, requestSequence, 'live-motion')
        setDispatchMs(performance.now() - (timing.observedAt ?? committedAt))
        tailClipId.current = value.tailClipId
        tailRate.current = value.motion.playbackVariant ?? 1
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
    }).finally(() => { if (requestGeneration === generation.current) pendingMs.current = Math.max(0, pendingMs.current - reserveMs) })
  }, [invalidateClosure, onEnqueue, readiness, refreshReadiness, scheduleClose, streamId, recognizer, rate])

  const handleInterim = useCallback((text) => {
    setInterim(text)
    if (text) invalidateClosure()
    scheduleClose(generation.current)
  }, [invalidateClosure, scheduleClose])
  const speechHandlers = {
    onCommit: commitSpeech, onInterim: handleInterim, forms,
    onFinal: (text) => setFinalText((previous) => `${previous} ${text}`.trim().slice(-4000)),
    onCorrection: (message) => setNotices((previous) => [...previous, message].slice(-5)),
  }
  const chromeSpeech = useLiveSpeech(speechHandlers)
  const localSpeech = useLocalSpeech(speechHandlers)
  const speech = recognizer === 'local' ? localSpeech : chromeSpeech
  const { listening, stop } = speech
  const acknowledge = localSpeech.applied
  useEffect(() => { transport.current = recognizer === 'local' ? localSpeech.request : null }, [recognizer, localSpeech.request])
  useEffect(() => {
    const timer = setTimeout(() => {
      if (lagMs >= 60000 && listening) {
        stop()
        setNotices((previous) => [...previous, '60 seconds of accepted motion is pending. Microphone stopped; every accepted sign will drain.'].slice(-5))
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [lagMs, listening, stop])
  useEffect(() => {
    const submitted = ({ detail }) => { if (Number.isFinite(detail.sourceEndAt)) setSubmittedMs(detail.at - detail.sourceEndAt) }
    const applied = ({ detail }) => {
      if (Number.isFinite(detail.sourceEndAt)) setAppliedMs(detail.at - detail.sourceEndAt)
      acknowledge(detail)
    }
    const visibility = () => {
      if (document.hidden && listening) {
        stop()
        setNotices((previous) => [...previous, 'Microphone stopped because the avatar tab is hidden. Accepted signs resume when visible.'].slice(-5))
      }
    }
    window.addEventListener('signsure-sign-submitted', submitted)
    window.addEventListener('signsure-sign-applied', applied)
    document.addEventListener('visibilitychange', visibility)
    return () => {
      window.removeEventListener('signsure-sign-submitted', submitted)
      window.removeEventListener('signsure-sign-applied', applied)
      document.removeEventListener('visibilitychange', visibility)
    }
  }, [acknowledge, listening, stop])

  function clear() {
    generation.current += 1
    speech.cancel()
    invalidateClosure()
    tailClipId.current = null
    chain.current = Promise.resolve()
    lastCommitAt.current = null
    pendingMs.current = 0
    audioWindow.current = []
    setAppliedMs(null)
    setSubmittedMs(null)
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
  const canListen = speech.supported && readiness?.usable && !disabled && lagMs === 0
    && (recognizer !== 'local' || readiness?.speech?.warm && readiness?.streaming?.warm)
  const displayedActivity = speech.error || activity === 'error' ? 'error'
    : lagMs > 0 ? 'signing' : speech.listening ? (activity === 'processing' ? 'processing' : 'listening') : 'stopped'
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
        <label>Recognition <select value={recognizer} disabled={speech.listening || lagMs > 0}
          onChange={(event) => { clear(); setRecognizer(event.target.value) }}>
          <option value="local">Local streaming (offline)</option>
          <option value="chrome">Chrome fallback (network timing)</option>
        </select></label>
        {recognizer === 'local' && <label>Motion variant <select value={rate} disabled={speech.listening || lagMs > 0}
          onChange={(event) => setRate(event.target.value)}>
          <option value="auto">Adaptive (approved variants only)</option>
          <option value="1">Recorded speed</option><option value="0.8">80% (slower validated transitions)</option>
        </select></label>}
        <button
          className="button"
          type="button"
          disabled={!speech.listening && !canListen}
          onClick={() => {
            if (speech.listening) {
              speech.stop()
              setActivity('stopped')
            } else {
              speech.start({ streamId, generation: generation.current, libraryVersion: readiness.libraryVersion })
              setActivity('listening')
            }
          }}
        >
          {speech.listening ? 'Stop listening' : 'Start listening'}
        </button>
        <button className="button button--ghost" type="button" onClick={clear}>Clear</button>
      </div>
      {recognizer === 'local' && (!readiness?.speech?.warm || !readiness?.streaming?.warm) && <div>
        <p className="hint">Local recognizer: {warming ? 'warming' : readiness?.speech?.state ?? 'checking'}.
          {readiness?.speech?.state === 'not-installed' && ' Install requirements-live.txt and run tools/setup_live_speech.py in the backend first.'}</p>
        <button className="button button--ghost" disabled={warming} onClick={async () => {
          setWarming(true)
          try { await api.liveWarm(); await refreshReadiness() } catch (error) { setNotices([error.message]) }
          finally { setWarming(false) }
        }}>Warm local recognizer</button>
        {readiness?.speech?.error && <p className="notice notice--bad">{readiness.speech.error}</p>}
        {readiness?.streaming?.error && <p className="notice notice--warn">{readiness.streaming.error}</p>}
      </div>}
      {!speech.supported && <p className="notice notice--bad">Use Chrome desktop on localhost or HTTPS with microphone support.</p>}
      <p className="hint">Literal signing preview—not a reviewed ISL translation. Preserves every committed sign; existing motion may lag fast speech. Sub-second performance is not yet certified.</p>
      {recognizer === 'local' && readiness?.streaming?.published && <details>
        <summary>Motion readiness: {readiness.streaming.compiled}/{readiness.streaming.required} artifacts verified</summary>
        {Object.entries(readiness.streaming.durations ?? {}).filter(([key]) => key.startsWith(`${Number(rate === 'auto' ? 1 : rate).toFixed(1)}:`)).map(([key, duration]) =>
          <p className="hint" key={key}>{key.split(':')[1]}: {(duration.signMs / 1000).toFixed(2)}s protected motion; {Math.round(duration.entryMs)} ms entry.</p>)}
        {readiness.streaming.failed?.map((entry) => <p className="hint" key={entry.unit}>{entry.unit}: {entry.error}</p>)}
      </details>}
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
      {submittedMs !== null && <p className="hint">Estimated audio to sign submission: {Math.round(submittedMs)} ms.</p>}
      {appliedMs !== null && <p className="hint">Estimated audio to Unity-applied sign: {Math.round(appliedMs)} ms. Visible onset still requires video validation.</p>}
      {lagMs > 3000 && <p className="hint">Speech is ahead of signing. Every committed sign is retained; protected movements will not be accelerated without approval.</p>}
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
