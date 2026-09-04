import { useMemo, useState } from 'react'

/** Browse the recorded vocabulary and play any single sign. */
export default function SignLibrary({ signs, activeGloss, onPlay, disabled = false }) {
  const [query, setQuery] = useState('')

  const visible = useMemo(() => {
    const needle = query.trim().toUpperCase()
    return needle ? signs.filter((s) => s.gloss.includes(needle)) : signs
  }, [signs, query])

  return (
    <section className="library">
      <div className="library__head">
        <h2>Vocabulary <span className="count">{signs.length}</span></h2>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search signs"
          aria-label="Search signs"
        />
      </div>

      {signs.length === 0 ? (
        <p className="empty">
          No signs yet. Upload a Rokoko CSV on the Capture tab to add the first one.
        </p>
      ) : (
        <ul className="library__list">
          {visible.map((sign) => (
            <li key={sign.id}>
              <button
                type="button"
                className={sign.gloss === activeGloss ? 'sign sign--active' : 'sign'}
                onClick={() => onPlay(sign)}
                disabled={disabled}
              >
                <span className="sign__gloss">{sign.gloss}</span>
                <span className="sign__meta">{(sign.durationMs / 1000).toFixed(1)}s</span>
                {sign.qc?.warnings?.length > 0 && (
                  <span className="sign__warn" title={sign.qc.warnings.join('\n')}>!</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
