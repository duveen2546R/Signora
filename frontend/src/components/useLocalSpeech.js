import { useCallback, useEffect, useRef, useState } from 'react'
import { createLocalSpeechController } from './localSpeechController.js'
import workletUrl from './microphone.worklet.js?worker&url'

export default function useLocalSpeech(handlers) {
  const callbacks = useRef(handlers)
  const controller = useRef(null)
  const [state, setState] = useState('stopped')
  const [error, setError] = useState(null)
  const supported = Boolean(globalThis.navigator?.mediaDevices?.getUserMedia && globalThis.AudioWorkletNode)
  useEffect(() => { callbacks.current = handlers }, [handlers])
  useEffect(() => {
    controller.current = createLocalSpeechController({
      onState: setState, onError: setError,
      onInterim: (text) => callbacks.current.onInterim?.(text),
      onFinal: (text) => callbacks.current.onFinal?.(text),
      onCommit: (text, timing) => callbacks.current.onCommit?.(text, timing),
      onCorrection: (text) => callbacks.current.onCorrection?.(text),
    }, { base: import.meta.env.VITE_API_BASE ?? '/api/v1', workletUrl })
    return () => controller.current.destroy()
  }, [])
  const start = useCallback((options) => { setError(null); return controller.current.start(options) }, [])
  const stop = useCallback(() => controller.current.stop(), [])
  const cancel = useCallback(() => controller.current.cancel(), [])
  const request = useCallback((type, body) => controller.current.request(type, body), [])
  const applied = useCallback((value) => controller.current.applied(value), [])
  return { state, error, supported, start, stop, cancel, request, applied,
    listening: ['starting', 'listening', 'stopping'].includes(state) }
}
