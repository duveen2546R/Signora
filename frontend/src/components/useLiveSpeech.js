import { useCallback, useEffect, useRef, useState } from 'react'

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

  recognition.onstart = () => handlers.onState?.('listening')
  recognition.onresult = (event) => {
    const final = []
    const interim = []
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const transcript = event.results[index][0]?.transcript?.trim()
      if (!transcript) continue
      if (event.results[index].isFinal) final.push(transcript)
      else interim.push(transcript)
    }
    handlers.onInterim?.(interim.join(' '))
    if (final.length) handlers.onFinal?.(final.join(' '))
  }
  recognition.onerror = (event) => {
    fatal = FATAL_ERRORS.has(event.error)
    handlers.onError?.(event.error)
    if (fatal) wanted = false
  }
  recognition.onend = () => {
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
    destroy() {
      wanted = false
      if (restartTimer !== null) clearTimeout(restartTimer)
      recognition.onstart = recognition.onresult = recognition.onerror = recognition.onend = null
      try { recognition.abort() } catch { /* recognition was never started */ }
    },
  }
}

export default function useLiveSpeech({ onFinal, onInterim }) {
  const callbacks = useRef({ onFinal, onInterim })
  const controller = useRef(null)
  const [state, setState] = useState('stopped')
  const [error, setError] = useState(null)
  const supported = typeof window !== 'undefined' && Boolean(speechRecognitionConstructor(window))

  useEffect(() => { callbacks.current = { onFinal, onInterim } }, [onFinal, onInterim])
  useEffect(() => {
    if (!supported) return undefined
    controller.current = createSpeechController(speechRecognitionConstructor(window), {
      onState: setState,
      onInterim: (text) => callbacks.current.onInterim?.(text),
      onFinal: (text) => callbacks.current.onFinal?.(text),
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

  return { supported, state, error, start, stop, listening: state === 'listening' || state === 'starting' || state === 'restarting' }
}
