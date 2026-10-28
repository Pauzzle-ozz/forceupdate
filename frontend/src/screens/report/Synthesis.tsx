import { ShieldCheck } from 'lucide-react'
import { cn } from 'cn'
import type { FindingKind, Summary } from '@/api/types'
import { KIND_ICON } from '@/components/icons'
import { Card } from '@/components/ui/card'
import { agree, count, formatNumber, fr } from '@/lib/format'
import { GAP_WORD, KINDS, KIND_LABEL, SEVERITIES, SEVERITY_LABEL, SEVERITY_WORD } from '@/lib/report'
import { Section } from '@/shell/Page'

const BAR: Record<string, string> = {
  critical: 'bg-chart-critical',
  high: 'bg-chart-high',
  medium: 'bg-chart-medium',
  low: 'bg-chart-low',
  info: 'bg-chart-info',
}

/** « 13 élevées · 14 moyennes · 1 faible » : les gravités non nulles. */
function bySeverity(counts: Record<string, number>): string {
  return SEVERITIES.filter((severity) => counts[severity])
    .map((severity) => {
      const n = counts[severity]
      const [one, many] = SEVERITY_WORD[severity]
      return `${formatNumber(n)} ${agree(n, one, many)}`
    })
    .join(' · ')
}

/**
 * La synthèse (ECRANS.md, écran 4) : un compteur par type de constat, toujours là, même à zéro
 * (un zéro dit « vérifié, rien trouvé ») ; un compteur non nul filtre le tableau. Puis la barre
 * des gravités de ce qui est à mettre à jour.
 */
export function Synthesis({
  summary,
  kind,
  onKind,
}: {
  summary: Summary
  kind: FindingKind | null
  onKind: (kind: FindingKind) => void
}) {
  const coverage = [
    `${count(summary.direct, 'directe')}, ${count(summary.transitive, 'indirecte')}`,
    `${count(summary.checked, 'vérifiée', 'vérifiées')} auprès des registres`,
    `${count(summary.audited, 'auditée', 'auditées')} par OSV`,
  ].join(' · ')

  return (
    <Section aria-labelledby="synthese-titre">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="synthese-titre" className="text-xl">
          Synthèse
        </h2>
        <p className="text-sm text-fg-muted">{coverage}</p>
      </div>
      <div
        className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(150px,1fr))]"
        role="group"
        aria-label="Constats par type ; choisir un type filtre le tableau"
      >
        {KINDS.map((each) => (
          <Counter
            key={each}
            kind={each}
            value={summary.findings[each] ?? 0}
            detail={detail(each, summary)}
            audited={summary.audited}
            pressed={kind === each}
            onPress={() => onKind(each)}
          />
        ))}
      </div>
      {summary.to_update > 0 && <SeverityBar summary={summary} />}
    </Section>
  )
}

function detail(kind: FindingKind, summary: Summary): string | null {
  if (kind === 'vulnerable') return bySeverity(summary.vulnerabilities) || null
  if (kind === 'outdated') {
    const parts = (['major', 'minor', 'patch'] as const)
      .filter((gap) => summary.outdated[gap])
      .map((gap) => {
        const n = summary.outdated[gap]
        return `${formatNumber(n)} ${agree(n, ...GAP_WORD[gap])}`
      })
    return parts.join(' · ') || null
  }
  if (kind === 'inconclusive') return 'registre ou OSV muet'
  return null
}

function Counter({
  kind,
  value,
  detail,
  audited,
  pressed,
  onPress,
}: {
  kind: FindingKind
  value: number
  detail: string | null
  audited: number
  pressed: boolean
  onPress: () => void
}) {
  const Icon = kind === 'vulnerable' && value === 0 ? ShieldCheck : KIND_ICON[kind]
  const sense =
    value > 0 && kind === 'vulnerable'
      ? 'border-l-4 border-l-high'
      : value > 0 && kind === 'inconclusive'
        ? 'border-l-4 border-dashed border-l-inconclusive'
        : value === 0 && kind === 'vulnerable' && audited > 0
          ? 'border-l-4 border-l-success'
          : ''
  const content = (
    <>
      <span className="flex items-center gap-2 text-sm font-medium text-fg-muted">
        <Icon className="size-4" aria-hidden="true" />
        {KIND_LABEL[kind]}
      </span>
      <span
        className={cn(
          'text-2xl leading-[1.1] tabular-nums sm:text-3xl',
          value === 0 ? 'font-medium text-fg-muted' : 'font-semibold',
        )}
      >
        {formatNumber(value)}
      </span>
      {value === 0 && kind === 'vulnerable' && audited > 0 ? (
        <span className="text-xs text-fg-muted">{count(audited, 'dépendance auditée', 'dépendances auditées')}</span>
      ) : (
        detail && <span className="text-xs text-fg-muted">{detail}</span>
      )}
    </>
  )
  const box = cn(
    'flex flex-col gap-1 rounded-md border border-border bg-surface px-4 py-3 text-left text-fg',
    sense,
  )
  if (value === 0) return <div className={box}>{content}</div>
  return (
    <button
      type="button"
      aria-pressed={pressed}
      className={cn(box, 'transition-colors duration-150 hover:border-control', pressed && 'bg-primary-soft')}
      onClick={onPress}
    >
      {content}
    </button>
  )
}

/** La barre empilée des gravités, sa légende avec les nombres, et tout dans son `aria-label`. */
function SeverityBar({ summary }: { summary: Summary }) {
  const total = summary.to_update
  const label = fr(`Gravité des ${count(total, 'constat')} : ${SEVERITIES.map((severity) => {
    const n = summary.severities[severity] ?? 0
    return `${formatNumber(n)} ${agree(n, ...SEVERITY_WORD[severity])}`
  }).join(', ')}`)
  return (
    <Card className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-base">Gravité des {count(total, 'constat')}</h3>
        <span className="text-sm text-fg-muted">du plus grave au moins grave</span>
      </div>
      <div className="flex h-3 gap-0.5 overflow-hidden rounded-full bg-track" role="img" aria-label={label}>
        {SEVERITIES.map((severity) => {
          const n = summary.severities[severity] ?? 0
          if (!n) return null
          return <span key={severity} className={cn('block h-full', BAR[severity])} style={{ width: `${(n / total) * 100}%` }} />
        })}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-2 text-sm" aria-hidden="true">
        {SEVERITIES.map((severity) => (
          <li key={severity} className="inline-flex items-center gap-2">
            <span className={cn('size-2.5 rounded-[2px]', BAR[severity])} />
            {SEVERITY_LABEL[severity]} <b className="tabular-nums">{formatNumber(summary.severities[severity] ?? 0)}</b>
          </li>
        ))}
      </ul>
    </Card>
  )
}
