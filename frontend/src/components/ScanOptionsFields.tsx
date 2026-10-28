import { ChevronRight } from 'lucide-react'
import { useId } from 'react'
import type { ScanOptions } from '@/api/types'
import { Switch } from '@/components/ui/switch'
import { useOnline } from '@/hooks/useStatus'
import { fr } from '@/lib/format'

const FIELDS: { key: keyof ScanOptions; label: string; hint?: string }[] = [
  { key: 'dev', label: 'Vérifier les dépendances de développement' },
  {
    key: 'transitive',
    label: 'Vérifier aussi les versions des dépendances indirectes',
    hint: '(leurs failles sont toujours cherchées)',
  },
  { key: 'include_tests', label: "Analyser aussi les dossiers de tests et d'exemples" },
  { key: 'offline', label: fr('Hors ligne : seulement le cache') },
  { key: 'cache', label: 'Utiliser le cache disque' },
]

/** Les options d'analyse (celles de `POST /api/scans`), repliées. */
export function ScanOptionsFields({
  value,
  onChange,
}: {
  value: ScanOptions
  onChange: (options: ScanOptions) => void
}) {
  const id = useId()
  const online = useOnline()
  return (
    <details className="group">
      <summary className="inline-flex min-h-(--control-h) items-center gap-2 text-sm font-medium">
        <ChevronRight
          className="size-4 transition-transform duration-200 ease-out group-open:rotate-90"
          aria-hidden="true"
        />
        Options d'analyse
      </summary>
      <div className="flex flex-col gap-1 pt-2 pl-6">
        {FIELDS.map(({ key, label, hint }) => (
          <div key={key} className="flex min-h-(--control-h) items-center gap-3 text-sm">
            <Switch
              id={`${id}-${key}`}
              checked={value[key]}
              disabled={key === 'offline' && !online}
              onCheckedChange={(checked) => onChange({ ...value, [key]: checked })}
            />
            <label htmlFor={`${id}-${key}`}>
              {label}
              {hint && <span className="text-fg-muted"> {hint}</span>}
              {key === 'offline' && !online && value.offline && (
                <span className="text-fg-muted"> {fr('(coché : pas de réseau)')}</span>
              )}
            </label>
          </div>
        ))}
      </div>
    </details>
  )
}
