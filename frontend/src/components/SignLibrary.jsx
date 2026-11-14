import { useMemo, useState } from 'react'
import { applyPhysicalTextKey } from './physicalTextInput'
import { filterSigns } from './signSearch'

/** Browse the recorded vocabulary and play any single sign. */
export default function SignLibrary({ signs, activeGloss, onPlay, onEditPhases, disabled = false }) {
  const [query, setQuery] = useState('')

  const visible = useMemo(() => filterSigns(signs, query), [signs, query])

  function handlePhysicalKey(event) {
    // Unity WebGL can prevent the browser's default text editing while its canvas is mounted.
    // Mirror the composer input so the vocabulary search remains usable with a physical keyboard.
    if (event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return
    const input = event.currentTarget
    const edit = applyPhysicalTextKey(query, event.key, input.selectionStart, input.selectionEnd)
    if (!edit) return

    event.preventDefault()
    setQuery(edit.text)
    requestAnimationFrame(() => input.setSelectionRange(edit.caret, edit.caret))
  }

  return (
    <section className="panel">
      <div className="panel__head">
        <h2 className="label">Vocabulary</h2>
        <span className="panel__count mono">{signs.length}</span>
      </div>

      <input
        className="input"
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={handlePhysicalKey}
        placeholder="Search signs"
        aria-label="Search signs"
        autoComplete="off"
      />

      {query.trim() && <p className="hint" role="status">{visible.length} matching sign{visible.length === 1 ? '' : 's'}</p>}

      {signs.length === 0 ? (
        <p className="empty" style={{ marginTop: 16 }}>
          No signs yet. Upload a combined Rokoko FBX on the Capture page to add the first one.
        </p>
      ) : (
        <ul className="library">
          {visible.length === 0 && <li className="empty">No matching sign. Try a shorter word or use alphabet fallback.</li>}
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
