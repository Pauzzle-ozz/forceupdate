import { ExternalLink as ExternalIcon } from 'lucide-react'
import type { ReactNode } from 'react'

/** Un lien qui ouvre un onglet : dit aux lecteurs d'écran, sans `Referer`. */
export function ExternalLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
      <ExternalIcon className="ml-0.5 inline size-4 align-[-3px]" aria-hidden="true" />{' '}
      <span className="sr-only">(nouvel onglet)</span>
    </a>
  )
}
