import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

const NAV = [
  { to: '/sign', label: 'Sign' },
  { to: '/capture', label: 'Capture' },
]

function useScrolled(threshold = 4) {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > threshold)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [threshold])
  return scrolled
}

export default function Layout() {
  const scrolled = useScrolled()
  const { pathname } = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const isLanding = pathname === '/'

  useEffect(() => {
    if (!menuOpen) return undefined
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [menuOpen])

  return (
    <div className={`shell ${isLanding ? 'shell--landing' : ''}`}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className={`shell__head ${scrolled ? 'shell__head--scrolled' : ''}`}>
        <NavLink to="/" className="wordmark" aria-label="SignSure home" onClick={() => setMenuOpen(false)}>signsure</NavLink>

        <button
          type="button"
          className="shell__menu-button"
          aria-expanded={menuOpen}
          aria-controls="primary-navigation"
          aria-label={menuOpen ? 'Close navigation' : 'Open navigation'}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span>{menuOpen ? 'Close' : 'Menu'}</span>
          <svg viewBox="0 0 20 20" aria-hidden="true">
            {menuOpen
              ? <path d="M4 4l12 12M16 4 4 16" />
              : <path d="M3 6h14M3 14h14" />}
          </svg>
        </button>

        <nav id="primary-navigation" className={`shell__nav ${menuOpen ? 'shell__nav--open' : ''}`}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => `link ${isActive ? 'link--active' : ''}`}
              onClick={() => setMenuOpen(false)}
            >
              {item.label}
            </NavLink>
          ))}
          <NavLink to="/login" className="link shell__nav-mobile" onClick={() => setMenuOpen(false)}>Login</NavLink>
          <NavLink to="/register" className="link shell__nav-mobile" onClick={() => setMenuOpen(false)}>Join SignSure ↗</NavLink>
        </nav>

        <div className="shell__actions">
          <NavLink to="/login" className="link link--muted">Login</NavLink>
          <NavLink to="/register" className="link">Join</NavLink>
          <span className="shell__locale" aria-label="Language: English">EN</span>
        </div>
      </header>

      <main className="shell__main" id="main-content">
        <Outlet />
      </main>

      <footer className="shell__foot">
        <div className="shell__foot-statement">
          <h3>Movement in.</h3>
          <h3>Language out.</h3>
        </div>
        <div>
          <ul>
            <li>Indian Sign Language</li>
            <li>Rokoko Smartsuit &amp; Smartgloves</li>
          </ul>
        </div>
        <div>
          <ul>
            <li><NavLink to="/capture" className="link link--muted">Capture library</NavLink></li>
            <li><NavLink to="/register" className="link link--muted">Create account</NavLink></li>
          </ul>
        </div>
        <div className="foot__col--end">
          <div>SignSure® © {new Date().getFullYear()}</div>
        </div>
      </footer>
    </div>
  )
}
