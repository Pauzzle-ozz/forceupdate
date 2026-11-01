import { Ban, TriangleAlert, X } from 'lucide-react'
import { Link } from 'react-router'
import type { Finding, Report, Update } from '@/api/types'
import { ExternalLink } from '@/components/ExternalLink'
import { GapBadge, SeverityBadge } from '@/components/badges'
import { KIND_ICON } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Sheet, SheetBody, SheetFooter, SheetHeader } from '@/components/ui/sheet'
import { count, fr } from '@/lib/format'
import { where, type Row } from '@/lib/report'
import { CoverageNote, Version, VersionArrow, fixesText } from './cells'

const REASON: Record<string, string> = {
  latest_patch: 'Dernier correctif',
  latest_minor: 'Dernière mineure',
  latest_major: 'Dernière version',
  security_fix: 'Corrige les failles',
  replacement: 'Remplace une version retirée ou dépréciée',
  supported_cycle: 'Cycle conseillé (fin de vie)',
}

/**
 * Le détail d'une dépendance (ECRANS.md, écran 4 ; pages/rapport.md, « Panneau de détail ») :
 * versions, constats, mises à jour possibles, déclarations. Un paquet peut avoir plusieurs
 * lignes (déclaré en runtime et en dev) : le détail les réunit.
 */
export function DependencyDetail({
  rows,
  report,
  scanId,
  onClose,
}: {
  rows: Row[]
  report: Report
  /** L'analyse dont on choisit la mise à jour ; `null` : pas de mise à jour ici (un dépôt). */
  scanId: string | null
  onClose: () => void
}) {
  const open = rows.length > 0
  return (
    <Sheet open={open} onClose={onClose} aria-labelledby="detail-titre">
      {open && <Detail rows={rows} report={report} scanId={scanId} onClose={onClose} />}
    </Sheet>
  )
}

function Detail({ rows, report, scanId, onClose }: { rows: Row[]; report: Report; scanId: string | null; onClose: () => void }) {
  const first = rows[0]
  const { dependency } = first
  const findings = uniqueFindings(rows)
  const update = rows.find((row) => row.update)?.update ?? null
  const outdated = findings.find((finding) => finding.kind === 'outdated')
  const scopes = [...new Set(rows.map((row) => row.dependency.scope))]

  return (
    <>
      <SheetHeader>
        <div className="flex min-w-0 grow flex-col gap-2">
          <h2 id="detail-titre" className="font-mono text-xl break-all" tabIndex={-1} data-autofocus>
            {dependency.name}
          </h2>
          <div className="flex flex-wrap gap-1.5">
            <Badge>{dependency.ecosystem}</Badge>
            <Badge variant="outline">{dependency.direct ? 'directe' : 'indirecte'}</Badge>
            {scopes.map((scope) => (
              <Badge key={scope} variant="outline">
                {scope}
              </Badge>
            ))}
            {report.projects.length > 1 && (
              <Badge variant="outline">
                projet <span className="font-mono">{first.project.path}</span>
              </Badge>
            )}
          </div>
        </div>
        <Button variant="ghost" size="icon" aria-label="Fermer le détail" onClick={onClose}>
          <X aria-hidden="true" />
        </Button>
      </SheetHeader>

      <SheetBody>
        <section className="flex flex-col gap-2" aria-labelledby="detail-versions">
          <h3 id="detail-versions" className="text-base">
            Versions
          </h3>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-fg-muted">Utilisée</dt>
            <dd>
              {dependency.installed ? (
                <>
                  <Version>{dependency.installed}</Version>{' '}
                  {dependency.lockfile && <span className="text-fg-muted">lue dans {dependency.lockfile}</span>}
                </>
              ) : update?.current_is_approximate ? (
                <>
                  <Version>{update.current_version}</Version>{' '}
                  <span className="text-fg-muted">
                    {fr('approximative : la borne basse de la contrainte, sans lockfile')}
                  </span>
                </>
              ) : (
                <span className="text-fg-muted">inconnue (pas de lockfile)</span>
              )}
            </dd>
            {dependency.direct &&
              rows.map((row) => (
                <ConstraintLine key={row.key} row={row} />
              ))}
            {outdated?.wanted_version && (
              <>
                <dt className="text-fg-muted">Acceptée</dt>
                <dd>
                  <Version>{outdated.wanted_version}</Version>{' '}
                  <span className="text-fg-muted">
                    {outdated.wanted_version === outdated.current_version
                      ? fr('la plus haute que la contrainte permet : la monter demande de changer la contrainte')
                      : fr('la plus haute que la contrainte permet déjà : régénérer le lockfile suffit pour y monter')}
                  </span>
                </dd>
              </>
            )}
            {outdated?.target_version && (
              <>
                <dt className="text-fg-muted">Dernière</dt>
                <dd className="flex flex-wrap items-center gap-2">
                  <Version>{outdated.target_version}</Version>
                  {outdated.gap && <GapBadge gap={outdated.gap} />}
                </dd>
              </>
            )}
          </dl>
        </section>

        <section className="flex flex-col gap-2" aria-labelledby="detail-constats">
          <h3 id="detail-constats" className="text-base">
            {findings.length > 0 ? count(findings.length, 'constat') : 'Constats'}
          </h3>
          {findings.length === 0 ? (
            <CoverageNote row={first} report={report} />
          ) : (
            <ul>
              {findings.map((finding, index) => (
                <FindingItem key={index} finding={finding} />
              ))}
            </ul>
          )}
        </section>

        {update && <Options update={update} />}

        {update && update.dependencies.length > 0 && (
          <section className="flex flex-col gap-2" aria-labelledby="detail-declarations">
            <h3 id="detail-declarations" className="text-base">
              Déclarations
            </h3>
            <ul className="flex flex-col gap-1 text-sm">
              {update.dependencies.map((declaration, index) => (
                <li key={index} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono">{where(declaration.file, declaration.location?.line)}</span>
                  {declaration.constraint && <Version>{declaration.constraint}</Version>}
                  {declaration.scope !== 'runtime' && <Badge variant="outline">{declaration.scope}</Badge>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </SheetBody>

      <SheetFooter>
        <Button onClick={onClose}>Fermer</Button>
        {scanId !== null && update && update.options.length > 0 && (
          <Link
            to={`/analyses/${scanId}/mise-a-jour?paquet=${encodeURIComponent(update.id)}`}
            className={buttonVariants({ variant: 'primary' })}
          >
            Choisir la version de <span className="font-mono">{dependency.name}</span>
          </Link>
        )}
      </SheetFooter>
    </>
  )
}

function ConstraintLine({ row }: { row: Row }) {
  const { dependency } = row
  return (
    <>
      <dt className="text-fg-muted">Contrainte</dt>
      <dd>
        {dependency.constraint ? <Version>{dependency.constraint}</Version> : <span className="text-fg-muted">aucune</span>}{' '}
        <span className="text-fg-muted">{where(dependency.file, dependency.location?.line)}</span>
      </dd>
    </>
  )
}

/** Les constats des lignes, sans les doubles d'un paquet déclaré deux fois. */
function uniqueFindings(rows: Row[]): Finding[] {
  const seen = new Set<string>()
  const kept: Finding[] = []
  for (const row of rows) {
    for (const finding of row.findings) {
      const key = `${finding.kind}|${finding.message}`
      if (!seen.has(key)) {
        seen.add(key)
        kept.push(finding)
      }
    }
  }
  return kept
}

function FindingItem({ finding }: { finding: Finding }) {
  const vulnerable = finding.kind === 'vulnerable'
  const Icon = KIND_ICON[finding.kind]
  return (
    <li className="grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-1 border-border py-3 not-first:border-t first:pt-0">
      {finding.kind === 'inconclusive' ? (
        <Badge variant="inconclusive">
          <Icon aria-hidden="true" />
          Non concluant
        </Badge>
      ) : (
        <SeverityBadge severity={finding.severity} />
      )}
      <div className="flex min-w-0 flex-col gap-1">
        {vulnerable && finding.detail ? (
          <p className="text-sm" lang="en">
            {finding.detail}
          </p>
        ) : (
          <p className="text-sm">{finding.message}</p>
        )}
        {finding.identifiers.length > 0 && (
          <div className="flex flex-wrap gap-x-2 gap-y-1 font-mono text-xs text-fg-muted">
            {finding.identifiers.map((identifier) => (
              <span key={identifier}>{identifier}</span>
            ))}
          </div>
        )}
        {vulnerable && finding.current_is_approximate && (
          <p className="text-sm text-fg-muted">
            {fr('Faille possible : elle touche la borne basse de la contrainte ; la version installée peut être corrigée.')}
          </p>
        )}
        <p className="text-sm text-fg-muted">
          {[
            vulnerable && finding.cvss_score !== null ? `CVSS ${finding.cvss_score.toLocaleString('fr-FR')}` : null,
            vulnerable && finding.target_version ? `corrigée en ${finding.target_version}` : null,
            vulnerable && !finding.target_version ? 'aucune version corrigée connue' : null,
            !vulnerable && finding.detail && finding.kind !== 'inconclusive' ? finding.detail : null,
          ]
            .filter(Boolean)
            .join(' · ')}
          {finding.url && (
            <>
              {' · '}
              <ExternalLink href={finding.url}>
                {vulnerable ? 'avis sur osv.dev' : finding.kind === 'eol' ? 'cycles sur endoflife.date' : 'page du paquet'}
              </ExternalLink>
            </>
          )}
        </p>
      </div>
    </li>
  )
}

function Options({ update }: { update: Update }) {
  return (
    <section className="flex flex-col gap-2" aria-labelledby="detail-maj">
      <h3 id="detail-maj" className="text-base">
        Mises à jour possibles
      </h3>
      {update.note && <p className="text-sm">{update.note}</p>}
      {update.options.length === 0 ? (
        !update.note && <p className="text-sm text-fg-muted">Aucune.</p>
      ) : (
        <ul className="rounded-md border border-border bg-surface">
          {update.options.map((option) => (
            <li key={option.version} className="flex flex-col gap-1 border-border px-4 py-3 not-first:border-t">
              <div className="flex flex-wrap items-center gap-2">
                <VersionArrow from={update.current_version} to={<b>{option.version}</b>} />
                {option.gap && <GapBadge gap={option.gap} />}
                {update.selected === option.version && <Badge variant="primary">pré-cochée</Badge>}
                {option.manual && (
                  <Badge variant="outline">
                    <Ban aria-hidden="true" />à faire à la main
                  </Badge>
                )}
              </div>
              <p className="text-sm text-fg-muted">
                {[
                  option.reasons.map((reason) => REASON[reason] ?? reason).join(', '),
                  fixesText(option),
                  option.edits.length === 0 ? 'lockfile seul' : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
              {option.manual && <p className="text-sm text-fg-muted">{option.manual}</p>}
              {option.introduced.length > 0 && (
                <p className="flex items-start gap-2 text-sm text-danger">
                  <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                  {fr(`Failles apportées : ${option.introduced.join(', ')}`)}
                </p>
              )}
              {option.warnings.map((warning) => (
                <p key={warning} className="flex items-start gap-2 text-sm text-warning">
                  <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                  {warning}
                </p>
              ))}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
