import { useCallback, useEffect, useRef, useState } from 'react'
import { StableSpeechResult } from './stableSpeech.js'

const FATAL_ERRORS = new Set(['not-allowed', 'service-not-allowed', 'audio-capture', 'language-not-supported'])

export function speechRecognitionConstructor(scope = window) {
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null
}

export function createSpeechController(Recognition, handlers, restartDelayMs = 250) {
  if (!Recognition) return null
  const recognition = new Recognition()
  recognition.lang = 'en-IN'
  recognition.continuous = true
  recognition.interimResults = true
  recognition.maxAlternatives = 1
  let wanted = false
  let fatal = false
  let restartTimer = null
  let stableTimer = null
  let results = new Map()
  let finalThrough = -1
  let ignoreResults = false
  const flushStable = () => {
    stableTimer = null
    for (const [index, result] of results) {
      const commit = result.take(performance.now(), handlers.getForms?.() ?? [])
      if (commit.correction && !result.reported) {
        result.reported = true
        handlers.onCorrection?.('Speech recognition corrected words already sent for signing. The corrected transcript is shown; those signs were not replayed.')
      }
      if (commit.text) handlers.onCommit?.(commit.text, commit)
      if (result.final) {
        results.delete(index)
        finalThrough = Math.max(index, finalThrough)
      } else {
        // Preserve recognition result order even if later items finalize first.
        if (result.committed.length < result.words.length && !result.conflict) {
          stableTimer = setTimeout(flushStable, 40)
        }
        break
      }
    }
  }

  recognition.onstart = () => {
    ignoreResults = false
    results = new Map()
    finalThrough = -1
    handlers.onState?.('listening')
  }
  recognition.onresult = (event) => {
    if (ignoreResults) return
    const final = []
    const interim = []
    for (let index = 0; index < event.results.length; index += 1) {
      const transcript = event.results[index][0]?.transcript?.trim()
      if (!transcript) continue
      if (event.results[index].isFinal) {
        if (index > finalThrough) final.push(transcript)
      } else interim.push(transcript)
      if (index <= finalThrough) continue
      const result = results.get(index) ?? new StableSpeechResult()
      result.update(transcript, event.results[index].isFinal, performance.now())
      results.set(index, result)
    }
    for (const index of results.keys()) if (index >= event.results.length) results.delete(index)
    if (stableTimer !== null) clearTimeout(stableTimer)
    flushStable()
    handlers.onInterim?.(interim.join(' '))
    if (final.length) handlers.onFinal?.(final.join(' '))
  }
  recognition.onerror = (event) => {
    fatal = FATAL_ERRORS.has(event.error)
    handlers.onError?.(event.error)
    if (fatal) wanted = false
  }
  recognition.onend = () => {
    if (stableTimer !== null) clearTimeout(stableTimer)
    stableTimer = null
    if (!wanted || fatal) {
      handlers.onState?.('stopped')
      return
    }
    restartTimer = setTimeout(() => {
      restartTimer = null
      try { recognition.start() } catch { handlers.onState?.('restarting') }
    }, restartDelayMs)
  }

  return {
    recognition,
    start() {
      wanted = true
      fatal = false
      handlers.onState?.('starting')
      recognition.start()
    },
    stop() {
      wanted = false
      if (restartTimer !== null) clearTimeout(restartTimer)
      restartTimer = null
      recognition.stop()
    },
    cancel() {
      wanted = false
      ignoreResults = true
      clearTimeout(restartTimer)
      clearTimeout(stableTimer)
      restartTimer = stableTimer = null
      results.clear()
      recognition.abort()
      handlers.onState?.('stopped')
    },
    destroy() {
      wanted = false
      if (restartTimer !== null) clearTimeout(restartTimer)
      if (stableTimer !== null) clearTimeout(stableTimer)
      recognition.onstart = recognition.onresult = recognition.onerror = recognition.onend = null
      try { recognition.abort() } catch { /* recognition was never started */ }
    },
  }
}

export default function useLiveSpeech({ onFinal, onInterim, onCommit, onCorrection, forms = [] }) {
  const callbacks = useRef({ onFinal, onInterim, onCommit, onCorrection, forms })
  const controller = useRef(null)
  const [state, setState] = useState('stopped')
  const [error, setError] = useState(null)
  const supported = typeof window !== 'undefined' && Boolean(speechRecognitionConstructor(window))

  useEffect(() => { callbacks.current = { onFinal, onInterim, onCommit, onCorrection, forms } }, [onFinal, onInterim, onCommit, onCorrection, forms])
  useEffect(() => {
    if (!supported) return undefined
    controller.current = createSpeechController(speechRecognitionConstructor(window), {
      onState: setState,
      onInterim: (text) => callbacks.current.onInterim?.(text),
      onFinal: (text) => callbacks.current.onFinal?.(text),
      onCommit: (text, timing) => callbacks.current.onCommit?.(text, timing),
      onCorrection: (message) => callbacks.current.onCorrection?.(message),
      getForms: () => callbacks.current.forms,
      onError: (code) => {
        if (code === 'no-speech' || code === 'aborted') return
        setError(code === 'not-allowed' || code === 'service-not-allowed'
          ? 'Microphone permission was denied.'
          : `Speech recognition stopped: ${code}.`)
      },
    })
    return () => controller.current?.destroy()
  }, [supported])

  const start = useCallback(() => {
    setError(null)
    controller.current?.start()
  }, [])
  const stop = useCallback(() => controller.current?.stop(), [])
  const cancel = useCallback(() => controller.current?.cancel(), [])

  return { supported, state, error, start, stop, cancel, listening: state === 'listening' || state === 'starting' || state === 'restarting' }
}
