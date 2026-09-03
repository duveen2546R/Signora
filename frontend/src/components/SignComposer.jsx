import { useState } from 'react'
import { api } from '../api/client'

/** Type a sentence, see which signs it resolves to, and play it on the avatar. */
export default function SignComposer({ signs, activeGloss, onPlay, disabled }) {
  const [text, setText] = useState('')
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const signFor = (clipId) => signs.find((s) => s.id === clipId)

  async function handleSubmit(event) {
    event.preventDefault()
    if (!text.trim()) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.translate(text)
      setPlan(result)
      const items = result.items
        .map((item) => ({ gloss: item.gloss, sign: signFor(item.clipId) }))
        .filter((item) => item.sign)
      if (items.length > 0) await onPlay(items)
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
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="good morning"
            autoComplete="off"
          />
          <button type="submit" disabled={busy || disabled || !text.trim()}>
            {busy ? 'Translating…' : 'Sign it'}
          </button>
        </div>
      </form>

      {error && <p className="error">{error}</p>}

      {plan && (
        <div className="plan">
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
