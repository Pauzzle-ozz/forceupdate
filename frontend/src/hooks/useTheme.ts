import { useCallback, useEffect, useSyncExternalStore } from 'react'

/** Le thème choisi : clair, sombre, ou celui du système (par défaut). */
export type Theme = 'light' | 'dark' | 'system'

/** Même clé que public/theme.js, qui pose le thème avant le premier affichage. */
export const THEME_KEY = 'forceupdate-theme'

const listeners = new Set<() => void>()

function read(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    return stored === 'light' || stored === 'dark' ? stored : 'system'
  } catch {
    return 'system'
  }
}

function systemDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

/** Pose (ou retire) la classe « dark » de <html>, d'après le choix et le système. */
export function applyTheme(theme: Theme = read()): void {
  const dark = theme === 'dark' || (theme === 'system' && systemDark())
  document.documentElement.classList.toggle('dark', dark)
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Le thème choisi, gardé dans le navigateur (une préférence d'affichage, pas une donnée). */
export function useTheme(): [Theme, (theme: Theme) => void] {
  const theme = useSyncExternalStore(subscribe, read, () => 'system' as Theme)

  useEffect(() => {
    applyTheme(theme)
    if (theme !== 'system') return
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    const follow = () => applyTheme('system')
    media?.addEventListener('change', follow)
    return () => media?.removeEventListener('change', follow)
  }, [theme])

  const setTheme = useCallback((next: Theme) => {
    try {
      if (next === 'system') localStorage.removeItem(THEME_KEY)
      else localStorage.setItem(THEME_KEY, next)
    } catch {
      // stockage refusé : le choix vaut pour cette page seulement
    }
    applyTheme(next)
    for (const listener of listeners) listener()
  }, [])

  return [theme, setTheme]
}
