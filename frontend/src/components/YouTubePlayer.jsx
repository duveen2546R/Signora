import { useEffect, useRef } from 'react'

let apiPromise

function loadYouTubeApi() {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  if (apiPromise) return apiPromise
  apiPromise = new Promise((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      previous?.()
      resolve(window.YT)
    }
    const script = document.createElement('script')
    script.src = 'https://www.youtube.com/iframe_api'
    script.async = true
    script.onerror = () => reject(new Error('The YouTube player could not be loaded.'))
    document.head.appendChild(script)
  })
  return apiPromise
}

export default function YouTubePlayer({ videoId, onReady, onStateChange, onError }) {
  const hostRef = useRef(null)
  const callbacks = useRef({ onReady, onStateChange, onError })

  useEffect(() => {
    callbacks.current = { onReady, onStateChange, onError }
  }, [onReady, onStateChange, onError])

  useEffect(() => {
    let disposed = false
    let player
    loadYouTubeApi().then((YT) => {
      if (disposed || !hostRef.current) return
      player = new YT.Player(hostRef.current, {
        videoId,
        playerVars: { playsinline: 1, rel: 0 },
        events: {
          onReady: (event) => callbacks.current.onReady?.(event.target),
          onStateChange: (event) => callbacks.current.onStateChange?.(event.data),
          onError: (event) => callbacks.current.onError?.(event.data),
        },
      })
    }).catch((error) => callbacks.current.onError?.(error))
    return () => {
      disposed = true
      player?.destroy?.()
    }
  }, [videoId])

  return <div className="youtube-frame" ref={hostRef} aria-label="YouTube video player" />
}
