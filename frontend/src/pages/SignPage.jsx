import { useCallback, useEffect, useRef, useState } from 'react'
import SignoraStage from '../components/SignoraStage'
import SignComposer from '../components/SignComposer'
import SequenceReview from '../components/SequenceReview'
import PhaseReview from '../components/PhaseReview'
import SignLibrary from '../components/SignLibrary'
import { api } from '../api/client'

export default function SignPage() {
  const [signs, setSigns] = useState([])
  const [activeGloss, setActiveGloss] = useState(null)
  const [activeOccurrence, setActiveOccurrence] = useState(null)
  const [playbackSource, setPlaybackSource] = useState(null)
  const [editingSign, setEditingSign] = useState(null)
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
    setActiveOccurrence(null)
    setPlaybackSource('sentence')
    window.signsure.play(track)
  }, [])

  const playSign = useCallback(async (sign) => {
    setError(null)
    try {
      const cached = cache.current.get(sign.contentHash) ?? await api.signTrack(sign.id)
      cache.current.set(sign.contentHash, cached)
      if (!window.signsure?.isCalibrated()) {
        throw new Error('Wait for avatar calibration to finish before playing a sign.')
      }
      setActiveOccurrence(null)
      setPlaybackSource('sign')
      window.signsure.play(cached)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  return (
    <div className="studio-page">
      <header className="page-masthead">
        <p>01 / Studio</p>
        <h1>Make language move.</h1>
        <span>Motion-captured signing<br />in your browser.</span>
      </header>
      <div className="sign">
        <div className="sign__stage">
          <SignoraStage
            onStatus={setStatus}
            onSignStart={(gloss, occurrence) => { setActiveGloss(gloss); setActiveOccurrence(occurrence) }}
            onIdle={() => { setActiveGloss(null); setActiveOccurrence(null) }}
          />
        </div>

        <aside className="sign__rail">
          <SignComposer activeOccurrence={playbackSource === 'sentence' ? activeOccurrence : null} onClear={() => { window.signsure?.clear(); setActiveGloss(null); setActiveOccurrence(null) }} onPlay={playTrack} disabled={!avatarReady} />
          {error && <div className="panel"><p className="notice notice--bad">{error}</p></div>}
          {editingSign && <PhaseReview
            key={editingSign.contentHash} sign={editingSign}
            onClose={() => setEditingSign(null)}
            onSaved={(updated) => {
              setSigns((previous) => previous.map((sign) => sign.id === updated.id ? updated : sign))
              setEditingSign(null)
            }}
          />}
          <SignLibrary
            signs={signs}
            activeGloss={activeGloss}
            onPlay={playSign}
            onEditPhases={setEditingSign}
            disabled={!avatarReady}
          />
          <SequenceReview signs={signs} disabled={!avatarReady} onPlay={(track) => {
            playTrack(track)
            setPlaybackSource('review')
          }} />
        </aside>
      </div>
    </div>
  )
}
