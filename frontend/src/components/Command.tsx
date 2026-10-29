import { Check, Copy } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useCopy } from '@/hooks/useCopy'

/**
 * Une commande à lancer (MASTER, « Commande ») : en chasse fixe, préfixée de `$` (qui ne se
 * copie pas), avec « Copier » qui devient « Copié » 2 s. La copie s'annonce par une région
 * `aria-live` à soi, pas par une notification Sonner (qui injecte un `<style>`, refusé par la CSP).
 */
export function Command({ command, label }: { command: string; label: string }) {
  const { copied, said, copy } = useCopy(command, 'Commande copiée.')

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
