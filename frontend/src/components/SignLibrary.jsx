import { useMemo, useState } from 'react'

/** Browse the recorded vocabulary and play any single sign. */
export default function SignLibrary({ signs, activeGloss, onPlay, onEditPhases, disabled = false }) {
  const [query, setQuery] = useState('')

  const visible = useMemo(() => {
    const needle = query.trim().toUpperCase()
    return needle ? signs.filter((s) => s.gloss.includes(needle)) : signs
  }, [signs, query])

  return (
    <section className="panel">
      <div className="panel__head">
        <h2 className="label">Vocabulary</h2>
        <span className="panel__count mono">{signs.length}</span>
      </div>

      <input
        className="input"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search signs"
        aria-label="Search signs"
      />

      {signs.length === 0 ? (
        <p className="empty" style={{ marginTop: 16 }}>
          No signs yet. Upload a Rokoko CSV on the Capture page to add the first one.
        </p>
      ) : (
        <ul className="library">
          {visible.map((sign) => (
            <li key={sign.id}>
              <button
                type="button"
                className={`sign-row ${sign.gloss === activeGloss ? 'sign-row--active' : ''}`.trim()}
                onClick={() => onPlay(sign)}
                disabled={disabled}
              >
                <span className="sign-row__gloss">{sign.gloss}</span>
                {sign.qc?.phases?.reviewed === false ? (
                  <span className="sign-row__flag" title={sign.qc.warnings?.join('\n')}>
                    Review phases
                  </span>
                ) : sign.qc?.warnings?.length > 0 ? (
                  <span className="sign-row__flag" title={sign.qc.warnings.join('\n')}>
                    Check capture
                  </span>
                ) : null}
                <span className="sign-row__meta mono">{(sign.durationMs / 1000).toFixed(1)}s</span>
              </button>
              <button type="button" className="library__edit" onClick={() => onEditPhases(sign)} aria-label={`Edit ${sign.gloss} phase timestamps`}>Edit timestamps</button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
