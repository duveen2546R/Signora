import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { initialPhaseDraft, snapPhaseDraft, validatePhaseDraft } from '../capturePhases'
import MotionPhaseEditor from './MotionPhaseEditor'

export default function PhaseReview({ sign, onSaved, onClose }) {
  const [track, setTrack] = useState(null)
  const [draft, setDraft] = useState({ signStart: '', signEnd: '' })
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let cancelled = false
    api.landmarks(sign.rawUrl ?? sign.landmarksUrl).then((raw) => {
      if (cancelled) return
      setTrack(raw)
      setDraft(initialPhaseDraft(raw))
    }).catch((e) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [sign.rawUrl, sign.landmarksUrl])

  async function save() {
    const validation = validatePhaseDraft({ ...draft, track, duration: track.durationSeconds ?? track.frameCount / track.fps })
    if (validation) { setError(validation); return }
    setBusy(true)
    setError(null)
    try {
      const snapped = snapPhaseDraft({ ...draft, track })
      const updated = await api.updatePhases(sign.id, {
        signStartSeconds: snapped.signStart, signEndSeconds: snapped.signEnd,
        expectedContentHash: sign.contentHash,
      })
      onSaved(updated)
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  return (
    <section className="panel" aria-label={`Edit ${sign.gloss} phases`}>
      <h2>{sign.gloss}: phase timestamps</h2>
      {!track && !error && <p role="status">Loading captured movement…</p>}
      {track && <MotionPhaseEditor track={track} {...draft} disabled={busy} onChange={(change) => { setDraft((previous) => ({ ...previous, ...change })); setError(null) }} />}
      {error && <p className="notice notice--bad" role="alert">{error}</p>}
      <div className="phase-draft__actions">
        <button type="button" className="secondary" onClick={onClose} disabled={busy}>Close editor</button>
        <button type="button" onClick={save} disabled={busy || !track}>{busy ? 'Saving…' : 'Save timestamps'}</button>
      </div>
    </section>
  )
}
