import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import useLiveSpeech from './useLiveSpeech'

const CLOSE_DELAY_MS = 800

function normalized(text) {
  return text.toLowerCase().replace(/[,;.!]+/g, ' ').replace(/\s+/g, ' ').trim()
}

export default function LiveSignComposer({ disabled, activeOccurrence, onEnqueue, onCancelQueued, onClear }) {
  const enabled = import.meta.env.VITE_LIVE_SIGNING !== 'false'
  const [readiness, setReadiness] = useState(null)
  const [interim, setInterim] = useState('')
  const [finalText, setFinalText] = useState('')
  const [items, setItems] = useState([])
  const [notices, setNotices] = useState([])
  const [activity, setActivity] = useState('stopped')
  const [lagMs, setLagMs] = useState(0)
  const [streamId] = useState(() => globalThis.crypto?.randomUUID?.() ?? `live-${Math.random()}`)
  const sequence = useRef(0)
  const generation = useRef(0)
  const tailClipId = useRef(null)
  const chain = useRef(Promise.resolve())
  const closeTimer = useRef(null)
  const closeToken = useRef(0)
  const closureEnqueued = useRef(false)
  const speculative = useRef(new Map())
  const busy = useRef(false)

  const refreshReadiness = useCallback(() => api.liveReadiness().then((value) => {
    setReadiness(value)
    return value
  }).catch((error) => {
    setNotices([error.message])
    return null
  }), [])

  useEffect(() => { if (enabled) refreshReadiness() }, [enabled, refreshReadiness])
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
    }).catch((error) => setNotices([error.message]))
  }, [onEnqueue, readiness, streamId])

  const scheduleClose = useCallback((requestGeneration) => {
    const token = ++closeToken.current
    if (closeTimer.current !== null) clearTimeout(closeTimer.current)
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null
      queueClose(token, requestGeneration)
    }, CLOSE_DELAY_MS)
  }, [queueClose])

  const commitFinal = useCallback((text) => {
    const phrase = text.trim()
    if (!phrase || !readiness) return
    invalidateClosure()
    setInterim('')
    setFinalText((previous) => previous ? `${previous} ${phrase}` : phrase)
    setActivity('processing')
    const requestGeneration = generation.current
    const requestSequence = sequence.current++
    scheduleClose(requestGeneration)
    chain.current = chain.current.then(async () => {
      if (requestGeneration !== generation.current) return
      busy.current = true
      const tail = tailClipId.current
      const key = `${readiness.libraryVersion}|${tail ?? 'rest'}|${normalized(phrase)}`
      let pending = speculative.current.get(key)
      speculative.current.delete(key)
      if (!pending) pending = api.liveTranslate({
        streamId,
        sequence: requestSequence,
        text: phrase,
        fromClipId: tail,
        libraryVersion: readiness.libraryVersion,
      })
      let value = await pending
      if (!value) value = await api.liveTranslate({
        streamId,
        sequence: requestSequence,
        text: phrase,
        fromClipId: tail,
        libraryVersion: readiness.libraryVersion,
      })
      if (requestGeneration !== generation.current) return
      setItems(value.items ?? [])
      setNotices((value.issues ?? []).map((issue) => issue.message).filter(Boolean))
      if (value.motion && !value.error) {
        onEnqueue(value.motion, requestSequence, 'live-motion')
        tailClipId.current = value.tailClipId
        setActivity('signing')
      } else {
        setActivity('listening')
      }
      busy.current = false
    }).catch(async (error) => {
      busy.current = false
      if (requestGeneration !== generation.current) return
      if (error.status === 409) {
        tailClipId.current = null
        await refreshReadiness()
      }
      setNotices([error.message])
      setActivity('error')
    })
  }, [invalidateClosure, onEnqueue, readiness, refreshReadiness, scheduleClose, streamId])

  const handleInterim = useCallback((text) => setInterim(text), [])
  const speech = useLiveSpeech({ onFinal: commitFinal, onInterim: handleInterim })

  useEffect(() => {
    if (!interim || !readiness || busy.current) return undefined
    const timer = setTimeout(() => {
      const tail = tailClipId.current
      const key = `${readiness.libraryVersion}|${tail ?? 'rest'}|${normalized(interim)}`
      if (!speculative.current.has(key)) {
        if (speculative.current.size >= 8) {
          speculative.current.delete(speculative.current.keys().next().value)
        }
        speculative.current.set(key, api.liveTranslate({
          streamId, sequence: sequence.current,
          text: interim, fromClipId: tail, libraryVersion: readiness.libraryVersion,
        }).catch(() => {
          speculative.current.delete(key)
          return null
        }))
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [interim, readiness, streamId])

  function clear() {
    generation.current += 1
    invalidateClosure()
    tailClipId.current = null
    chain.current = Promise.resolve()
    speculative.current.clear()
    setInterim('')
    setFinalText('')
    setItems([])
    setNotices([])
    setActivity(speech.listening ? 'listening' : 'stopped')
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
      {readiness && missingCount > 0 && (
        <p className="notice notice--warn">
          Preview library incomplete: {readiness.missingCoreGlosses.length} core and {readiness.missingAlphabetGlosses.length} alphabet recordings missing. Known phrases can still play.
        </p>
      )}
      <div className="live-transcript" aria-live="polite">
        <span>{finalText || 'Your finalized speech will appear here.'}</span>
        {interim && <em> {interim}</em>}
      </div>
      {lagMs > 1000 && <p className="hint">Signing is {(lagMs / 1000).toFixed(1)}s behind speech.</p>}
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
