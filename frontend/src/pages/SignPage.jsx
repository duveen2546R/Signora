import { useCallback, useEffect, useRef, useState } from 'react'
import SignoraStage from '../components/SignoraStage'
import SignComposer from '../components/SignComposer'
import SignLibrary from '../components/SignLibrary'
import { api } from '../api/client'

export default function SignPage() {
  const [signs, setSigns] = useState([])
  const [activeGloss, setActiveGloss] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)

  // Tracks are content-addressed and immutable, so they are worth keeping for the session.
  const cache = useRef(new Map())

  const refresh = useCallback(() => {
    api.listSigns().then((r) => setSigns(r.items)).catch(() => setSigns([]))
  }, [])

  useEffect(refresh, [refresh])

  const avatarReady = status.startsWith('calibrated:') && window.signsure?.isCalibrated() === true

  const playTrack = useCallback((track) => {
    setError(null)
    if (!window.signsure?.isCalibrated()) {
      setError('Wait for avatar calibration to finish before playing a sentence.')
      return
    }
    window.signsure.play(track)
  }, [])

  const playSign = useCallback(async (sign) => {
    setError(null)
    try {
      const cached = cache.current.get(sign.id) ?? await api.signTrack(sign.id)
      cache.current.set(sign.id, cached)
      if (!window.signsure?.isCalibrated()) {
        throw new Error('Wait for avatar calibration to finish before playing a sign.')
      }
      window.signsure.play(cached)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  return (
    <div className="studio-page">
      <header className="page-masthead">
        <p>01 / Studio</p>
        <h1>Make language<br />move.</h1>
        <span>Motion-captured signing<br />in your browser.</span>
      </header>
      <div className="sign">
        <div className="sign__stage">
          <SignoraStage
            onStatus={setStatus}
            onSignStart={setActiveGloss}
            onIdle={() => setActiveGloss(null)}
          />
        </div>

        <aside className="sign__rail">
          <SignComposer activeGloss={activeGloss} onPlay={playTrack} disabled={!avatarReady} />
          {error && <div className="panel"><p className="notice notice--bad">{error}</p></div>}
          <SignLibrary
            signs={signs}
            activeGloss={activeGloss}
            onPlay={playSign}
            disabled={!avatarReady}
          />
        </aside>
      </div>
    </div>
  )
}
