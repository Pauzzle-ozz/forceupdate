/**
 * Les correspondances fixes sens → icône Lucide (MASTER, « Icônes »). Une icône à côté d'un
 * mot est `aria-hidden` (lucide-react le pose tout seul) ; une icône seule, dans un bouton,
 * prend un `aria-label` sur le bouton.
 */
import {
  Archive,
  CircleAlert,
  CircleArrowUp,
  CircleDot,
  CircleHelp,
  Hourglass,
  Info,
  Link2Off,
  OctagonAlert,
  PackageX,
  ShieldAlert,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import type { FindingKind, Severity } from '@/api/types'

export const KIND_ICON: Record<FindingKind, LucideIcon> = {
  vulnerable: ShieldAlert,
  eol: Hourglass,
  yanked: PackageX,
  deprecated: Archive,
  outdated: CircleArrowUp,
  unverifiable: Link2Off,
  inconclusive: CircleHelp,
}

export const SEVERITY_ICON: Record<Severity, LucideIcon> = {
  critical: OctagonAlert,
  high: TriangleAlert,
  medium: CircleAlert,
  low: CircleDot,
  info: Info,
}
