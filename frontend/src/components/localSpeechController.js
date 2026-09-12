export function localSpeechUrl(base, location = window.location) {
  const url = new URL(`${base}/live/session`, location.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.href
}

export function createLocalSpeechController(handlers, options = {}) {
  const scope = options.scope ?? window
  let socket = null
  let stream = null
  let context = null
  let node = null
  let epoch = 0
  let startClock = 0
  let requestId = 0
  let ping = null
  let wanted = false
  let stopping = false
  const pending = new Map()
  const motionCache = new Map()
  let motionBytes = 0

  function releaseAudio() {
    node?.disconnect()
    node = null
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
    context?.close().catch(() => {})
    context = null
  }
  function fail(message) {
    handlers.onError?.(message)
    controller.cancel()
  }
  function send(value) {
    if (socket?.readyState !== 1) throw new Error('Local speech connection is closed.')
    socket.send(JSON.stringify(value))
  }
  const controller = {
    async start(start) {
      controller.cancel()
      const current = ++epoch
      wanted = true
      stopping = false
      handlers.onState?.('starting')
      try {
        const connected = new scope.WebSocket(localSpeechUrl(options.base ?? '/api/v1', scope.location))
        socket = connected
        await new Promise((resolve, reject) => {
          const timer = setTimeout(() => reject(new Error('Local speech connection timed out.')), 10000)
          connected.onopen = () => connected.send(JSON.stringify({ type: 'start', ...start }))
          connected.onerror = () => { clearTimeout(timer); reject(new Error('Cannot connect to local speech backend.')) }
          connected.onclose = () => { clearTimeout(timer); reject(new Error('Local speech connection closed.')) }
          connected.onmessage = (event) => {
            const value = JSON.parse(event.data)
            if (value.type === 'ready') { clearTimeout(timer); resolve() }
            if (value.type === 'error') { clearTimeout(timer); reject(new Error(value.message)) }
          }
        })
        if (current !== epoch || !wanted) return
        connected.onmessage = (event) => {
          if (current !== epoch) return
          const value = JSON.parse(event.data)
          if (value.type === 'error') return fail(value.message)
          if (value.generation !== start.generation || value.streamId !== start.streamId) return
          if (value.type === 'transcript') {
            handlers.onInterim?.(value.final ? '' : value.text)
            if (value.final && value.text) handlers.onFinal?.(value.text)
          } else if (value.type === 'commit') {
            handlers.onCommit?.(value.text, {
              ...value, sourceEndAt: startClock + value.sourceEndMs,
              sourceStartAt: value.sourceStartMs === null ? null : startClock + value.sourceStartMs,
              observedAt: startClock + value.observedAudioMs,
              wordCount: value.words.length, timingSource: 'audio-estimate',
            })
          } else if (value.type === 'correction') handlers.onCorrection?.(value.message)
          else if (value.type === 'stopped') handlers.onState?.('stopped')
          else if (value.type === 'response') {
            const request = pending.get(value.requestId)
            if (!request) return
            const settle = (error, result) => {
              if (!pending.delete(value.requestId)) return
              clearTimeout(request.timer)
              if (error) request.reject(error)
              else request.resolve(result)
            }
            if (value.error) settle(Object.assign(new Error(value.error), { status: value.status }))
            else if (value.value.motionReference) {
              const reference = value.value.motionReference
              const load = async () => {
                let motion = motionCache.get(reference.key)
                if (!motion) {
                  const response = await scope.fetch(`${options.base ?? '/api/v1'}/live/motion/${reference.key}`, { signal: request.abort.signal })
                  if (!response.ok) throw new Error('Cached motion unavailable; restart after refreshing readiness.')
                  motion = await response.json()
                  while (motionCache.size && motionBytes + reference.byteSize > 16 * 1024 * 1024) {
                    const key = motionCache.keys().next().value
                    motionBytes -= motionCache.get(key).bytes
                    motionCache.delete(key)
                  }
                  motion = { payload: motion, bytes: reference.byteSize }
                  motionCache.set(reference.key, motion)
                  motionBytes += reference.byteSize
                }
                if (current !== epoch) throw new Error('Speech session cancelled.')
                return { ...value.value, motion: motion.payload }
              }
              load().then((result) => settle(null, result), (error) => settle(error))
            } else settle(null, value.value)
          }
        }
        connected.onclose = () => { if (current === epoch) fail('Local speech connection lost. Accepted signs will drain; restart listening to reconnect.') }
        connected.onerror = () => { if (current === epoch) fail('Local speech connection failed.') }
        const media = await scope.navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false })
        if (current !== epoch || !wanted) { media.getTracks().forEach((track) => track.stop()); return }
        stream = media
        stream.getTracks().forEach((track) => { track.onended = () => { if (wanted) fail('Microphone device disconnected.') } })
        context = new scope.AudioContext({ latencyHint: 'interactive' })
        await context.audioWorklet.addModule(options.workletUrl)
        if (current !== epoch || !wanted) return
        const captureContext = context
        await captureContext.resume()
        if (current !== epoch || !wanted) return
        startClock = performance.now()
        node = new scope.AudioWorkletNode(context, 'signsure-microphone')
        node.port.onmessage = ({ data }) => {
          if (current !== epoch) return
          if (data.stopped) {
            send({ type: 'stop' })
            releaseAudio()
          } else {
            // Two seconds of audio is the hard transport bound. Never hide a discontinuity.
            if (connected.bufferedAmount > 65200) return fail('Audio transport is behind; microphone stopped without dropping queued signs.')
            if (connected.readyState === 1) connected.send(data)
          }
        }
        context.createMediaStreamSource(stream).connect(node)
        const mute = context.createGain()
        mute.gain.value = 0
        node.connect(mute).connect(context.destination)
        ping = setInterval(() => { if (connected.readyState === 1) send({ type: 'ping' }) }, 15000)
        handlers.onState?.('listening')
      } catch (error) {
        if (current === epoch) fail(error.name === 'NotAllowedError' ? 'Microphone permission was denied.' : error.message)
      }
    },
    request(type, body) {
      return new Promise((resolve, reject) => {
        const id = ++requestId
        const abort = new AbortController()
        const timer = setTimeout(() => { pending.delete(id); abort.abort(); reject(new Error('Live planning timed out.')) }, 10000)
        pending.set(id, { resolve, reject, timer, abort })
        try { send({ type, body, requestId: id }) } catch (error) { clearTimeout(timer); pending.delete(id); reject(error) }
      })
    },
    stop() {
      if (stopping) return
      stopping = true
      wanted = false
      handlers.onState?.('stopping')
      if (node) node.port.postMessage('stop')
      else controller.cancel()
    },
    cancel() {
      ++epoch
      wanted = false
      stopping = false
      clearInterval(ping)
      releaseAudio()
      if (socket) { socket.onclose = socket.onerror = socket.onmessage = null; socket.close(); socket = null }
      for (const { reject, timer, abort } of pending.values()) { clearTimeout(timer); abort.abort(); reject(new Error('Speech session cancelled.')) }
      pending.clear()
      handlers.onState?.('stopped')
    },
    applied(value) { if (socket?.readyState === 1) send({ type: 'applied', ...value }) },
    destroy() { controller.cancel() },
  }
  return controller
}
