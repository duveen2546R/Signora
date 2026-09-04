import { useTheme } from '../theme'

const LABEL = { system: 'Match system', light: 'Light', dark: 'Dark' }

function Glyph({ theme }) {
  if (theme === 'dark') {
    return (
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="currentColor">
        <path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8Z" />
      </svg>
    )
  }
  if (theme === 'light') {
    return (
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"
           fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round">
        <circle cx="8" cy="8" r="3.1" />
        <path d="M8 1.4v1.7M8 12.9v1.7M1.4 8h1.7M12.9 8h1.7M3.3 3.3l1.2 1.2M11.5 11.5l1.2 1.2M12.7 3.3l-1.2 1.2M4.5 11.5l-1.2 1.2" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"
         fill="none" stroke="currentColor" strokeWidth="1.3">
      <circle cx="8" cy="8" r="5.4" />
      <path d="M8 2.6v10.8" />
      <path d="M8 2.6a5.4 5.4 0 0 1 0 10.8Z" fill="currentColor" stroke="none" />
    </svg>
  )
}

export default function ThemeToggle() {
  const { theme, cycle } = useTheme()
  return (
    <button
      type="button"
      className="button button--icon"
      onClick={cycle}
      title={`Theme: ${LABEL[theme]}`}
      aria-label={`Theme: ${LABEL[theme]}. Activate to change.`}
    >
      <Glyph theme={theme} />
    </button>
  )
}
