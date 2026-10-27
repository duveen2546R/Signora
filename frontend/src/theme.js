import { useCallback, useEffect, useState } from 'react'

const KEY = 'signsure-theme'
export const THEMES = ['system', 'light', 'dark']

function read() {
  try {
    const saved = localStorage.getItem(KEY)
    return THEMES.includes(saved) ? saved : 'system'
  } catch {
    // Private browsing can throw on access; fall back to following the system.
    return 'system'
  }
}

function apply(theme) {
  const root = document.documentElement
  // "system" stamps nothing, so prefers-color-scheme decides. An explicit choice stamps the
  // attribute, which the token layer treats as the winner in both directions.
  if (theme === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme)
}

/** Theme preference with three states, persisted, defaulting to whatever the reader's OS says. */
export function useTheme() {
  const [theme, setTheme] = useState(read)

  useEffect(() => {
    apply(theme)
    try {
      if (theme === 'system') localStorage.removeItem(KEY)
      else localStorage.setItem(KEY, theme)
    } catch {
      // Not being able to remember the choice is not a reason to fail to apply it.
    }
  }, [theme])

  const cycle = useCallback(() => {
    setTheme((current) => THEMES[(THEMES.indexOf(current) + 1) % THEMES.length])
  }, [])

  return { theme, setTheme, cycle }
}
