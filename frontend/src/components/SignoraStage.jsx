import { useCallback, useEffect, useRef, useState } from 'react'
import { Unity, useUnityContext } from 'react-unity-webgl'
import SignoraPlayer from '../unity/SignoraPlayer'
import { api } from '../api/client'

// The build shipped in SignoraAvatarTracking/WebBuild, symlinked into public/unity.
const BUILD = '/unity/Build/WebBuild'

/**
 * Hosts the Signora WebGL avatar and streams landmark frames to it.
 *
 * The Unity runtime installs itself on scene load and talks to the page through two globals its
 * jslib calls - `SignoraUnityReady` and `SignoraCalibrationState` - rather than react-unity-webgl's
 * event system, so those are wired up here directly.
 */
export default function SignoraStage({ onSignStart, onIdle, onStatus }) {
  const { unityProvider, sendMessage, isLoaded, loadingProgression } = useUnityContext({
    loaderUrl: `${BUILD}.loader.js`,
    dataUrl: `${BUILD}.data`,
    frameworkUrl: `${BUILD}.framework.js`,
    codeUrl: `${BUILD}.wasm`,
  })

  const [status, setStatus] = useState('loading')
  const playerRef = useRef(null)
  const handlers = useRef({})

  useEffect(() => {
    handlers.current = { onSignStart, onIdle, onStatus }
  }, [onSignStart, onIdle, onStatus])

  const report = useCallback((next) => {
    setStatus(next)
    handlers.current.onStatus?.(next)
  }, [])

  // The runtime's jslib calls these two globals.
  useEffect(() => {
    window.SignoraUnityReady = () => report('ready')
    window.SignoraCalibrationState = (state) => {
      report(`calibration:${state}`)
      playerRef.current?.handleCalibrationState(state)
    }
    return () => {
      delete window.SignoraUnityReady
      delete window.SignoraCalibrationState
    }
  }, [report])

  useEffect(() => {
    if (!isLoaded) return undefined

    const player = new SignoraPlayer(sendMessage)
    playerRef.current = player
    player.onSignStart = (gloss) => handlers.current.onSignStart?.(gloss)
    player.onFinished = () => handlers.current.onIdle?.()
    player.onCalibrated = (state) => report(`calibrated:${state}`)
    player.onCalibrationFailed = (message) => report(`error:${message}`)

    window.signsure = {
      calibrate: (payload) => {
        player.setCalibrationPose(payload)
        player.calibrate()
      },
      play: (track) => player.play(track),
      clear: () => player.clear(),
      isCalibrated: () => player.calibrated,
    }

    // Calibrate here rather than from the app shell: the player only exists once Unity has
    // loaded, and the runtime's ready callback can fire before an outside effect would see it.
    let cancelled = false
    api.calibration()
      .then((payload) => {
        if (cancelled) return
        player.setCalibrationPose(payload)
        player.calibrate()
      })
      .catch((e) => report(`error:${e.message}`))

    return () => {
      cancelled = true
      player.stop()
      delete window.signsure
      playerRef.current = null
    }
  }, [isLoaded, sendMessage, report])

  const [kind, detail] = status.split(':')
  const label = kind === 'calibrated'
    ? 'Ready'
    : kind === 'calibration'
      ? 'Calibrating'
      : kind === 'error'
        ? 'Error'
        : kind === 'ready'
          ? 'Starting'
          : 'Loading'

  return (
    <div className="stage">
      <Unity
        unityProvider={unityProvider}
        className="stage__canvas"
        // The avatar has no keyboard controls. Keeping its canvas out of the tab order prevents
        // it from retaining focus while the user types a sentence in the HTML form.
        tabIndex={-1}
      />

      {!isLoaded && (
        <div className="stage__overlay">
          <p className="eyebrow">Loading avatar</p>
          <div className="stage__progress">
            <span style={{ transform: `scaleX(${loadingProgression || 0})` }} />
          </div>
          <p className="hint mono">{Math.round(loadingProgression * 100)}% — first load fetches 76&nbsp;MB</p>
        </div>
      )}

      {isLoaded && (
        <span
          className={`stage__status stage__status--${kind === 'calibrated' ? 'ready' : kind}`}
          title={detail ? `${label}: ${detail}` : label}
        >
          <span className="stage__dot" />
          {label}
        </span>
      )}
    </div>
  )
}
