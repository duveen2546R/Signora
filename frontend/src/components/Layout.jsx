import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import ThemeToggle from './ThemeToggle'

// The header mixes routed destinations with in-page sections of the landing page, the way the
// reference marketing navigation does. Section links jump to the landing page first when the
// visitor is somewhere else, so the target always exists by the time we scroll.
const NAV = [
  { label: 'Product', to: '/sign' },
  { label: 'Technology', section: 'technology' },
  { label: 'Process', section: 'process' },
  { label: 'Library', to: '/capture' },
  { label: 'About', section: 'about' },
  { label: 'Contact', section: 'contact' },
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
  const navigate = useNavigate()
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

  const goToSection = (section) => (event) => {
    event.preventDefault()
    setMenuOpen(false)
    const scroll = () => document.getElementById(section)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    if (isLanding) {
      scroll()
    } else {
      navigate('/')
      // The landing page has to mount before the anchor exists.
      window.setTimeout(scroll, 80)
    }
  }

  return (
    <div className={`shell ${isLanding ? 'shell--landing' : ''}`}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className={`shell__head ${scrolled ? 'shell__head--scrolled' : ''}`}>
        <div className="shell__head-inner">
          <NavLink to="/" className="wordmark" aria-label="SignSure home" onClick={() => setMenuOpen(false)}>SignSure</NavLink>

          <div className="shell__menu-actions">
            <ThemeToggle />
          </div>

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
            {NAV.map((item) => (item.section ? (
              <a key={item.label} href={`#${item.section}`} className="link" onClick={goToSection(item.section)}>
                {item.label}
              </a>
            ) : (
              <NavLink
                key={item.label}
                to={item.to}
                className={({ isActive }) => `link ${isActive ? 'link--active' : ''}`}
                onClick={() => setMenuOpen(false)}
              >
                {item.label}
              </NavLink>
            )))}
            <NavLink to="/sign" className="link shell__nav-mobile" onClick={() => setMenuOpen(false)}>Open studio ↗</NavLink>
          </nav>

          <div className="shell__actions">
            <ThemeToggle />
            <NavLink to="/sign" className="link">Open studio ↗</NavLink>
          </div>
        </div>
      </header>

      <main className="shell__main" id="main-content">
        <Outlet />
      </main>

      <footer className="shell__foot" id="contact">
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
          </ul>
        </div>
        <div className="foot__col--end">
          <div>SignSure® © {new Date().getFullYear()}</div>
        </div>
      </footer>
    </div>
  )
}
