import { WifiOff } from 'lucide-react'
import type { ScanOptions } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { fr } from '@/lib/format'

/** Les options d'une analyse, en badges : ce qui a été vérifié, et ce qui ne l'a pas été. */
export function OptionBadges({ options }: { options: ScanOptions }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="outline">
        {options.dev ? 'dépendances de dev comprises' : 'sans les dépendances de dev'}
      </Badge>
      <Badge variant="outline">
        {options.transitive ? 'indirectes vérifiées' : fr('indirectes : failles seulement')}
      </Badge>
      {options.include_tests && <Badge variant="outline">dossiers de tests compris</Badge>}
      {!options.cache && <Badge variant="outline">sans cache</Badge>}
      {options.offline && (
        <Badge variant="warning">
          <WifiOff aria-hidden="true" />
          hors ligne
        </Badge>
      )}
    </div>
  )
}
