import { useEffect, useRef, useState } from 'react'

/**
 * Copier un texte (MASTER, « Commande ») : `copied` 2 s après la copie, et `said`, la phrase à
 * mettre dans une région `aria-live` à soi (pas de notification Sonner : elle injecte un
 * `<style>`, refusé par la CSP).
 */
export function useCopy(text: string, done: string) {
  const [copied, setCopied] = useState(false)
  const [said, setSaid] = useState('')
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  async function copy() {
    window.clearTimeout(timer.current)
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setSaid(done)
      timer.current = window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setSaid('Copie impossible : sélectionner le texte à la main.')
    }
  }

  return { copied, said, copy }
}
