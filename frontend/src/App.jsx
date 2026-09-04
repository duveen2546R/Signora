import { useCallback, useEffect, useRef, useState } from 'react'
import SignoraStage from './components/SignoraStage'
import SignComposer from './components/SignComposer'
import SignLibrary from './components/SignLibrary'
import Capture from './pages/Capture'
import { api } from './api/client'
import './App.css'

export default function App() {
  const [tab, setTab] = useState('sign')
  const [signs, setSigns] = useState([])
  const [activeGloss, setActiveGloss] = useState(null)
  const [status, setStatus] = useState('loading')
  const [error, setError] = useState(null)

  // Landmark payloads are immutable and content-addressed, so cache them for the session.
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
    <div className="app">
      <header className="app__head">
        <h1>SignSure</h1>
        <nav>
          <button className={tab === 'sign' ? 'active' : ''} onClick={() => setTab('sign')}>
            Sign
          </button>
          <button className={tab === 'capture' ? 'active' : ''} onClick={() => setTab('capture')}>
            Capture
          </button>
        </nav>
      </header>

      {tab === 'sign' ? (
        <main className="app__main">
          <SignoraStage
            onStatus={setStatus}
            onSignStart={setActiveGloss}
            onIdle={() => setActiveGloss(null)}
          />
          <aside className="app__side">
            {error && <p className="error">{error}</p>}
            <SignComposer
              activeGloss={activeGloss}
              onPlay={playTrack}
              disabled={!avatarReady}
            />
            <SignLibrary
              signs={signs}
              activeGloss={activeGloss}
              onPlay={playSign}
              disabled={!avatarReady}
            />
          </aside>
        </main>
      ) : (
        <main className="app__main app__main--single">
          <Capture onLibraryChanged={refresh} />
        </main>
      )}
    </div>
  )
}
