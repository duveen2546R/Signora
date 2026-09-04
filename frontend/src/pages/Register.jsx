import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Reveal from '../components/Reveal'
import { api } from '../api/client'

/** Four independent things a password can do to resist guessing; each one lights a bar. */
function strengthOf(password) {
  return [
    password.length >= 10,
    /[a-z]/.test(password) && /[A-Z]/.test(password),
    /\d/.test(password),
    /[^A-Za-z0-9]/.test(password),
  ]
}

export default function Register() {
  const navigate = useNavigate()
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [errors, setErrors] = useState({})
  const [failure, setFailure] = useState(null)
  const [busy, setBusy] = useState(false)

  const strength = useMemo(() => strengthOf(form.password), [form.password])

  const set = (key) => (event) => {
    setForm((current) => ({ ...current, [key]: event.target.value }))
    setErrors((current) => ({ ...current, [key]: undefined }))
  }

  function validate() {
    const found = {}
    if (!form.name.trim()) found.name = 'Tell us what to call you.'
    if (!form.email.trim()) found.email = 'An email address is required.'
    else if (!/^\S+@\S+\.\S+$/.test(form.email)) found.email = 'That does not look like an email address.'
    if (form.password.length < 10) found.password = 'Use at least 10 characters.'
    setErrors(found)
    return Object.keys(found).length === 0
  }

  async function onSubmit(event) {
    event.preventDefault()
    setFailure(null)
    if (!validate()) return
    setBusy(true)
    try {
      await api.register(form)
      navigate('/')
    } catch (error) {
      setFailure(error.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth">
      <Reveal className="auth__art">
        <p className="eyebrow">Create account</p>
        <h1 className="display">Start<br />signing</h1>
        <p className="lede">
          An account lets you upload captures, review how each sign was segmented, and see why a
          sentence blended the way it did.
        </p>
      </Reveal>

      <div className="auth__form-side">
        <Reveal as="form" className="auth__form" delay={120} onSubmit={onSubmit} noValidate>
          <div className="auth__fields">
            <div className="field">
              <label className="label" htmlFor="register-name">Name</label>
              <input
                id="register-name"
                className={`input ${errors.name ? 'input--invalid' : ''}`}
                autoComplete="name"
                value={form.name}
                onChange={set('name')}
                aria-invalid={Boolean(errors.name)}
                disabled={busy}
              />
              {errors.name && <p className="field__error">{errors.name}</p>}
            </div>

            <div className="field">
              <label className="label" htmlFor="register-email">Email</label>
              <input
                id="register-email"
                className={`input ${errors.email ? 'input--invalid' : ''}`}
                type="email"
                autoComplete="email"
                value={form.email}
                onChange={set('email')}
                aria-invalid={Boolean(errors.email)}
                disabled={busy}
              />
              {errors.email && <p className="field__error">{errors.email}</p>}
            </div>

            <div className="field">
              <label className="label" htmlFor="register-password">Password</label>
              <input
                id="register-password"
                className={`input ${errors.password ? 'input--invalid' : ''}`}
                type="password"
                autoComplete="new-password"
                value={form.password}
                onChange={set('password')}
                aria-invalid={Boolean(errors.password)}
                disabled={busy}
              />
              <div className="strength" aria-hidden="true">
                {strength.map((on, index) => (
                  <span key={index} data-on={String(on)} />
                ))}
              </div>
              {errors.password
                ? <p className="field__error">{errors.password}</p>
                : <p className="hint">At least 10 characters. Mixed case, a digit and a symbol each help.</p>}
            </div>
          </div>

          {failure && <p className="notice notice--bad">{failure}</p>}

          <button type="submit" className="button button--wide" disabled={busy}>
            {busy ? 'Creating account…' : 'Create account'}
          </button>

          <p className="auth__foot">
            Already have one? <Link to="/login" className="link">Sign in</Link>
          </p>
        </Reveal>
      </div>
    </div>
  )
}
