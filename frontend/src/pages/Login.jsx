import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Reveal from '../components/Reveal'
import { api } from '../api/client'

export default function Login() {
  const navigate = useNavigate()
  const [form, setForm] = useState({ email: '', password: '' })
  const [errors, setErrors] = useState({})
  const [failure, setFailure] = useState(null)
  const [busy, setBusy] = useState(false)

  const set = (key) => (event) => {
    setForm((current) => ({ ...current, [key]: event.target.value }))
    setErrors((current) => ({ ...current, [key]: undefined }))
  }

  function validate() {
    const found = {}
    if (!form.email.trim()) found.email = 'Enter the email you signed up with.'
    else if (!/^\S+@\S+\.\S+$/.test(form.email)) found.email = 'That does not look like an email address.'
    if (!form.password) found.password = 'Enter your password.'
    setErrors(found)
    return Object.keys(found).length === 0
  }

  async function onSubmit(event) {
    event.preventDefault()
    setFailure(null)
    if (!validate()) return
    setBusy(true)
    try {
      await api.login(form)
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
        <p className="eyebrow">Sign in</p>
        <h1 className="display">Welcome<br />back</h1>
        <p className="lede">
          The capture library, ingest queue and quality reports live behind an account. Signing is
          open to anyone.
        </p>
      </Reveal>

      <div className="auth__form-side">
        <Reveal as="form" className="auth__form" delay={120} onSubmit={onSubmit} noValidate>
          <div className="auth__fields">
            <div className="field">
              <label className="label" htmlFor="login-email">Email</label>
              <input
                id="login-email"
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
              <label className="label" htmlFor="login-password">Password</label>
              <input
                id="login-password"
                className={`input ${errors.password ? 'input--invalid' : ''}`}
                type="password"
                autoComplete="current-password"
                value={form.password}
                onChange={set('password')}
                aria-invalid={Boolean(errors.password)}
                disabled={busy}
              />
              {errors.password && <p className="field__error">{errors.password}</p>}
            </div>
          </div>

          {failure && <p className="notice notice--bad">{failure}</p>}

          <button type="submit" className="button button--wide" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>

          <p className="auth__foot">
            No account yet? <Link to="/register" className="link">Create one</Link>
          </p>
        </Reveal>
      </div>
    </div>
  )
}
