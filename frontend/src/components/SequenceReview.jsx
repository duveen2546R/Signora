import { useState } from 'react'
import { api } from '../api/client'

/** Review generated motion explicitly, without representing it as an approved translation. */
export default function SequenceReview({ signs, disabled, onPlay }) {
  const [chosen, setChosen] = useState(['', '', ''])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [warnings, setWarnings] = useState([])
  async function preview() {
    setBusy(true)
    setError(null)
    setWarnings([])
    try {
      const result = await api.previewSequence(chosen.filter(Boolean).map(Number))
      setWarnings(result.warnings ?? [])
      if (!result.track || result.blendQuality?.status !== 'direct') {
        setError(result.error || 'The transition did not pass motion validation.')
        return
      }
      onPlay(result.track)
    } catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  return (
    <details className="panel sequence-review">
      <summary>Preview automatic transitions</summary>
      <p className="hint">Optional motion preview. Each sign’s saved phases work with every neighbour automatically; no pair setup or approval is required. This preview does not approve sentence meaning.</p>
      {chosen.map((value, index) => (
        <label key={index}>{['First sign', 'Second sign', 'Third sign (optional)'][index]}
          <select value={value} disabled={busy} onChange={(event) => setChosen((previous) => previous.map((item, at) => at === index ? event.target.value : item))}>
            <option value="">Choose a recording</option>
            {signs.map((sign) => <option key={sign.id} value={sign.id}>{sign.gloss}</option>)}
          </select>
        </label>
      ))}
      <button type="button" className="button" disabled={disabled || busy || !chosen[0] || !chosen[1]} onClick={preview}>{busy ? 'Checking motion…' : 'Preview transition'}</button>
      {warnings.map((warning) => <p className="notice notice--warn" key={warning}>{warning}</p>)}
      {error && <p className="notice notice--bad" role="alert">{error}</p>}
    </details>
  )
}
