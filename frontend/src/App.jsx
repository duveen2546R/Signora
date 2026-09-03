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

  const loadLandmarks = useCallback(async (sign) => {
    if (cache.current.has(sign.id)) return cache.current.get(sign.id)
    const payload = await api.landmarks(sign.landmarksUrl)
    cache.current.set(sign.id, payload)
    return payload
  }, [])

  const playSigns = useCallback(async (items) => {
    setError(null)
    try {
      const player = window.signsure
      if (!player?.isCalibrated()) {
        throw new Error('The avatar is still preparing. Wait for calibration to complete.')
      }
      for (const { sign, gloss } of items) {
        player.play(await loadLandmarks(sign), gloss ?? sign.gloss)
      }
    } catch (e) {
      setError(e.message)
    }
  }, [loadLandmarks])

  const avatarReady = status.startsWith('calibrated:')

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
              signs={signs}
              activeGloss={activeGloss}
              onPlay={playSigns}
              disabled={!avatarReady}
            />
            <SignLibrary
              signs={signs}
              activeGloss={activeGloss}
              onPlay={playSigns}
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
