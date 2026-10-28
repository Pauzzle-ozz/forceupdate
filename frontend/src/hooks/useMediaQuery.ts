import { useCallback, useSyncExternalStore } from 'react'

/** Vrai tant que `query` (une media query CSS) correspond à la fenêtre. */
export function useMediaQuery(query: string, fallback = true): boolean {
  const subscribe = useCallback(
    (listener: () => void) => {
      const media = window.matchMedia?.(query)
      media?.addEventListener('change', listener)
      return () => media?.removeEventListener('change', listener)
    },
    [query],
  )
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia?.(query).matches ?? fallback,
    () => fallback,
  )
}
