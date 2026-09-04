import { useState } from 'react'
import { api } from '../api/client'
import { blendNotices, playableTrack } from './blendQuality'
import { applyPhysicalTextKey } from './physicalTextInput'

/** Type a sentence, see which signs it resolves to, and play it on the avatar. */
export default function SignComposer({ activeGloss, onPlay, disabled }) {
  const [text, setText] = useState('')
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  function handlePhysicalKey(event) {
    // Older Unity WebGL builds prevent the browser's native text-editing default while their
    // canvas is mounted. Apply ordinary character/delete keys ourselves; paste, IME input,
    // shortcuts, selection, and mobile keyboards continue through the normal onChange path.
    if (event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return
    const input = event.currentTarget
    const edit = applyPhysicalTextKey(text, event.key, input.selectionStart, input.selectionEnd)
    if (!edit) return

    event.preventDefault()
    setText(edit.text)
    requestAnimationFrame(() => input.setSelectionRange(edit.caret, edit.caret))
  }


  async function handleSubmit(event) {
    event.preventDefault()
    if (!text.trim()) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.translate(text)
      setPlan(result)
      const track = playableTrack(result)
      if (track) onPlay(track)
      else if (result.error) setError(result.error)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="composer">
      <form onSubmit={handleSubmit}>
        <label htmlFor="composer-text">Sentence</label>
        <div className="composer__row">
          <input
            id="composer-text"
            type="text"
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={handlePhysicalKey}
            placeholder="good morning"
            autoComplete="off"
            inputMode="text"
          />
          <button type="submit" disabled={busy || disabled || !text.trim()}>
            {busy ? 'Translating…' : 'Sign it'}
          </button>
        </div>
      </form>

      {error && <p className="error">{error}</p>}

      {plan && (
        <div className="plan">
          {blendNotices(plan).map((warning) => (
            <p className="warning" role="status" key={warning}>{warning}</p>
          ))}
          <ol className="plan__glosses">
            {plan.items.map((item, index) => (
              <li
                key={`${item.gloss}-${index}`}
                className={[
                  'chip',
                  item.fingerspelled ? 'chip--spelled' : '',
                  item.gloss === activeGloss ? 'chip--active' : '',
                ].join(' ')}
              >
                {item.gloss}
              </li>
            ))}
          </ol>
          {plan.unmapped.length > 0 && (
            <p className="plan__unmapped">
              No sign recorded for: {plan.unmapped.join(', ')}. Record these, or add the manual
              alphabet so they can be fingerspelled.
            </p>
          )}
        </div>
      )}
    </section>
  )
}
