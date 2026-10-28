import { Check, Copy } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'

/**
 * Une commande à lancer (MASTER, « Commande ») : en chasse fixe, préfixée de `$` (qui ne se
 * copie pas), avec « Copier » qui devient « Copié » 2 s. La copie s'annonce par une région
 * `aria-live` à soi, pas par une notification Sonner (qui injecte un `<style>`, refusé par la CSP).
 */
export function Command({ command, label }: { command: string; label: string }) {
  const [copied, setCopied] = useState(false)
  const [said, setSaid] = useState('')
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  async function copy() {
    window.clearTimeout(timer.current)
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      setSaid('Commande copiée.')
      timer.current = window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setSaid('Copie impossible : sélectionner la commande à la main.')
    }
  }

  return (
    <div className="flex items-start gap-2 rounded-sm border border-border bg-surface-2 py-2 pr-2 pl-3">
      <code className="min-w-0 flex-1 pt-1.5 text-[13px] whitespace-pre-wrap [overflow-wrap:anywhere] before:text-fg-muted before:content-['$_'] before:select-none">
        {command}
      </code>
      <Button variant="ghost" size="sm" onClick={() => void copy()} aria-label={copied ? 'Copié' : `Copier ${label}`}>
        {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
        {copied ? 'Copié' : 'Copier'}
      </Button>
      <span className="sr-only" aria-live="polite">
        {said}
      </span>
    </div>
  )
}
