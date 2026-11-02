import { ArrowRight, CircleCheck, Link2Off, ShieldCheck, TriangleAlert } from 'lucide-react'
import type { Finding, Report, UpdateOption } from '@/api/types'
import { GapBadge, SeverityBadge, UnknownSeverityBadge } from '@/components/badges'
import { KIND_ICON } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { agree, count, fr } from '@/lib/format'
import {
  GAP_WORD,
  KIND_WORD,
  findingsByKind,
  highest,
  shownOption,
  where,
  type Row,
} from '@/lib/report'
import { isCargoManifest } from '@/lib/update'

/** Une sous-ligne : 12 px, atténuée, sous la valeur. */
export function Sub({ children }: { children: React.ReactNode }) {
  return <span className="mt-0.5 block text-xs [overflow-wrap:anywhere] text-fg-muted">{children}</span>
}

/** Une version, en chasse fixe. */
export function Version({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-sm whitespace-nowrap">{children}</span>
}

/** « 0.12 → 0.12.5 » (l'icône : la police latine n'a pas le caractère « → »). */
export function VersionArrow({ from, to }: { from: string | null; to: React.ReactNode }) {
  if (from === null) return <span className="font-mono text-sm whitespace-nowrap">{to}</span>
  return (
    <span className="inline-flex flex-wrap items-center gap-1 font-mono text-sm">
      {from}
      <ArrowRight className="size-3.5 text-fg-muted" role="img" aria-label="vers" />
      {to}
    </span>
  )
}

/** L'écosystème, directe ou indirecte, et le scope s'il n'est pas `runtime`. */
export function PackageMeta({ row, project = false }: { row: Row; project?: boolean }) {
  const { dependency } = row
  return (
    <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
      <Badge variant="neutral">{dependency.ecosystem}</Badge>
      {dependency.direct ? 'directe' : 'indirecte'}
      {dependency.scope !== 'runtime' && <span>· {dependency.scope}</span>}
      {/* Entre 768 et 1024 px, la colonne « Projet » passe ici. */}
      {project && <span className="font-mono lg:hidden">· {row.project.path}</span>}
    </span>
  )
}

/** La version approximative d'une ligne sans lockfile : la borne basse de la contrainte. */
function approximate(row: Row): string | null {
  const found = row.findings.find((finding) => finding.current_is_approximate && finding.current_version)
  if (found?.current_version) return found.current_version
  if (row.update?.current_is_approximate) return row.update.current_version
  return null
}

export function UsedCell({ row }: { row: Row }) {
  const { dependency } = row
  if (!dependency.installed && row.findings.some((finding) => finding.kind === 'unpinned')) {
    return (
      <>
        <span className="text-sm">non fixée</span>
        <Sub>{dependency.imported ? 'un import, sans version' : 'ni contrainte ni lockfile'}</Sub>
      </>
    )
  }
  if (dependency.installed) {
    return (
      <>
        <Version>{dependency.installed}</Version>
        {dependency.lockfile && <Sub>{dependency.lockfile}</Sub>}
      </>
    )
  }
  const lower = approximate(row)
  if (lower) {
    return (
      <>
        <span className="inline-flex flex-wrap items-center gap-1.5">
          <Version>{lower}</Version>
          <Badge variant="outline">approximative</Badge>
        </span>
        <Sub>borne basse de la contrainte, sans lockfile</Sub>
      </>
    )
  }
  return (
    <>
      <span className="text-sm text-fg-muted">—</span>
      <Sub>pas de lockfile</Sub>
    </>
  )
}

export function ConstraintCell({ row }: { row: Row }) {
  const { dependency } = row
  if (!dependency.direct) {
    return <span className="text-sm text-fg-muted">{fr('aucune : vient du lockfile')}</span>
  }
  if (dependency.imported) {
    return (
      <>
        <span className="text-sm text-fg-muted">{fr('aucune : un import')}</span>
        <Sub>
          import <span className="font-mono">{dependency.imported}</span>
        </Sub>
        <Sub>{dependency.file}</Sub>
      </>
    )
  }
  return (
    <>
      {dependency.constraint ? (
        <Version>{dependency.constraint}</Version>
      ) : (
        <span className="text-sm text-fg-muted">aucune (toute version)</span>
      )}
      {dependency.resolved_constraint && (
        <Sub>
          <span className="font-mono">{dependency.resolved_constraint}</span>{' '}
          {isCargoManifest(dependency.file) ? '(workspace)' : '(catalogue)'}
        </Sub>
      )}
      <Sub>{where(dependency.file, dependency.location?.line)}</Sub>
    </>
  )
}

/** Les badges des constats d'une ligne : un par type, accordé. */
export function FindingBadges({ findings }: { findings: Finding[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {findingsByKind(findings).flatMap(([kind, group]) => {
        const Icon = KIND_ICON[kind]
        if (kind === 'vulnerable') {
          const severity = highest(group.map((finding) => finding.severity)) ?? 'medium'
          const possible = group.every((finding) => finding.current_is_approximate)
          return [
            <Badge key={kind} variant={severity}>
              <Icon aria-hidden="true" />
              {possible ? count(group.length, 'faille possible', 'failles possibles') : count(group.length, 'faille')}
            </Badge>,
          ]
        }
        if (kind === 'outdated') {
          return group.map((finding, index) => (
            <Badge key={`${kind}${index}`} variant={finding.gap === 'major' ? 'warning' : 'outline'}>
              <Icon aria-hidden="true" />
              <span className="font-mono">{finding.target_version}</span>
              {finding.gap && GAP_WORD[finding.gap][0]}
            </Badge>
          ))
        }
        if (kind === 'unpinned') {
          const latest = group[0].target_version
          return [
            // Il passe à la ligne s'il le faut : à 375 px, « dernière 5.0.0.93 » déborderait.
            <Badge key={kind} variant="info" className="min-w-0 shrink flex-wrap whitespace-normal">
              <Icon aria-hidden="true" />
              {latest ? (
                <>
                  non fixée · dernière <span className="font-mono whitespace-nowrap">{latest}</span>
                </>
              ) : (
                KIND_WORD.unpinned[0]
              )}
            </Badge>,
          ]
        }
        const [one, many] = KIND_WORD[kind]
        return [
          <Badge key={kind} variant={kind === 'inconclusive' ? 'inconclusive' : 'outline'}>
            <Icon aria-hidden="true" />
            {group.length > 1 ? count(group.length, one, many) : one}
          </Badge>,
        ]
      })}
    </div>
  )
}

/** Ce qu'on sait d'une ligne sans constat : à jour, ou ce qui n'a pas été vérifié. */
export function CoverageNote({ row, report }: { row: Row; report: Report }) {
  const { dependency } = row
  switch (row.coverage) {
    case 'up-to-date':
      return (
        <span className="inline-flex items-center gap-1.5 text-sm">
          <CircleCheck className="size-4 text-success" aria-hidden="true" />À jour
        </span>
      )
    case 'audit-only':
      return (
        <>
          <span className="inline-flex items-center gap-1.5 text-sm">
            <ShieldCheck className="size-4 text-success" aria-hidden="true" />
            Aucune faille connue
          </span>
          <Sub>version non vérifiée (indirecte)</Sub>
        </>
      )
    case 'unverifiable':
      return (
        <>
          <Badge variant="outline">
            <Link2Off aria-hidden="true" />
            non vérifiable
          </Badge>
          {dependency.unverifiable_reason && <Sub>{dependency.unverifiable_reason}</Sub>}
        </>
      )
    default: {
      let why = 'version inconnue'
      if (!report.options) why = 'dépendances non vérifiées'
      else if (dependency.scope === 'dev' && !report.options.dev) why = 'dépendance de développement'
      return (
        <>
          <span className="text-sm text-fg-muted">non vérifiée</span>
          <Sub>{why}</Sub>
        </>
      )
    }
  }
}

export function FindingsCell({ row, report }: { row: Row; report: Report }) {
  return row.findings.length > 0 ? <FindingBadges findings={row.findings} /> : <CoverageNote row={row} report={report} />
}

export function SeverityCell({ row }: { row: Row }) {
  if (row.severity) return <SeverityBadge severity={row.severity} />
  if (row.inconclusive) return <UnknownSeverityBadge />
  return <span className="text-sm text-fg-muted">—</span>
}

/** Ce que corrige une option : « corrige 1 faille sur 4 », « corrige les 6 failles ». */
export function fixesText(option: UpdateOption): string | null {
  const fixed = option.fixes.length
  const total = fixed + option.unfixed.length
  if (total === 0) return null
  if (option.unfixed.length === 0) return fixed === 1 ? 'corrige la faille' : `corrige les ${fixed} failles`
  if (fixed === 0) return `laisse ${count(total, 'faille')}`
  return `corrige ${count(fixed, 'faille')} sur ${total}`
}

export function UpdateCell({ row }: { row: Row }) {
  const update = row.update
  if (!update) return <span className="text-sm text-fg-muted">—</span>
  const option = shownOption(update)
  if (!option) {
    return update.note ? <span className="text-sm text-fg-muted">{update.note}</span> : <span className="text-sm text-fg-muted">—</span>
  }
  const proposed = update.selected === option.version
  const parts = [
    proposed && option.gap ? GAP_WORD[option.gap][0] : null,
    option.edits.length === 0 ? 'lockfile seul' : null,
    fixesText(option),
  ].filter(Boolean)
  return (
    <>
      <VersionArrow from={update.current_version} to={option.version} />
      {proposed ? (
        <Sub>{parts.join(' · ')}</Sub>
      ) : (
        <span className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-fg-muted">
          {option.gap && <GapBadge gap={option.gap} />}
          {option.manual ? 'à faire à la main' : 'proposée, pas cochée'}
        </span>
      )}
      {option.introduced.length > 0 && (
        <span className="mt-1 flex items-center gap-1 text-xs text-danger">
          <TriangleAlert className="size-3.5" aria-hidden="true" />
          {count(option.introduced.length, 'faille apportée', 'failles apportées')}
        </span>
      )}
    </>
  )
}

/** Le nombre de lignes affichées : « 7 dépendances », « 3 dépendances sur 7 ». */
export function shownCount(shown: number, total: number): string {
  const all = count(total, 'dépendance')
  return shown === total ? all : `${shown} ${agree(shown, 'dépendance')} sur ${total}`
}
