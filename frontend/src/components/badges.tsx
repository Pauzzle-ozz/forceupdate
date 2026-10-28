import { CircleHelp, TriangleAlert } from 'lucide-react'
import type { Gap, Severity } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { SEVERITY_ICON } from '@/components/icons'
import { GAP_LABEL, SEVERITY_LABEL } from '@/lib/report'

/** La gravité : icône et mot ; critique en plein, les autres teintés. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  const Icon = SEVERITY_ICON[severity]
  return (
    <Badge variant={severity}>
      <Icon aria-hidden="true" />
      {SEVERITY_LABEL[severity]}
    </Badge>
  )
}

/** Gravité inconnue : seulement des constats « non concluant ». */
export function UnknownSeverityBadge() {
  return (
    <Badge variant="inconclusive">
      <CircleHelp aria-hidden="true" />
      Inconnue
    </Badge>
  )
}

/** L'écart : « Correctif », « Mineure » en contour ; « Majeure » en avertissement, avec icône. */
export function GapBadge({ gap }: { gap: Gap }) {
  if (gap === 'major') {
    return (
      <Badge variant="warning">
        <TriangleAlert aria-hidden="true" />
        {GAP_LABEL.major}
      </Badge>
    )
  }
  return <Badge variant="outline">{GAP_LABEL[gap]}</Badge>
}
