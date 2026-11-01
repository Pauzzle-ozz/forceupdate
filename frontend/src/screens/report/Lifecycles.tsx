import { Hourglass, TriangleAlert } from 'lucide-react'
import type { Ref } from 'react'
import type { EndOfLife, Finding, Project, Report } from '@/api/types'
import { ExternalLink } from '@/components/ExternalLink'
import { Badge } from '@/components/ui/badge'
import { NBSP, count, formatDay, fr } from '@/lib/format'
import { dependencyKey, type Row } from '@/lib/report'
import { Section } from '@/shell/Page'
import { PackageButton } from './Dependencies'
import { Version } from './cells'

interface Item {
  project: Project
  finding: Finding
  eol: EndOfLife
}

/**
 * Les fins de vie (E27 ; ECRANS.md, écran 4) : celles des runtimes du projet (Python, Node.js…),
 * qui ne sont pas dans le tableau des dépendances, puis celles des frameworks (Django…), dont le
 * nom ouvre le détail. Pour chacune : le cycle, sa date de fin, d'où vient la version, et le
 * cycle conseillé ; tout vient du rapport (`Finding.eol`).
 */
export function Lifecycles({
  report,
  all,
  onOpen,
  sectionRef,
}: {
  report: Report
  all: Row[]
  onOpen: (row: Row) => void
  sectionRef?: Ref<HTMLElement>
}) {
  const items: Item[] = report.projects.flatMap((project) =>
    project.findings.flatMap((finding) =>
      finding.kind === 'eol' && finding.eol ? [{ project, finding, eol: finding.eol }] : [],
    ),
  )
  if (items.length === 0) return null
  const several = report.projects.length > 1
  return (
    <Section aria-labelledby="fins-de-vie-titre" id="fins-de-vie" ref={sectionRef} className="scroll-mt-20">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="fins-de-vie-titre" className="text-xl">
          Fins de vie
        </h2>
        <p className="text-sm text-fg-muted">
          {fr(`${count(items.length, 'cycle')}, d'après endoflife.date`)}
        </p>
      </div>
      <p className="text-sm text-fg-muted">
        {fr(
          "Un runtime en fin de vie ne reçoit plus de correctifs de sécurité : il se change à la main. Un framework monte comme une autre dépendance.",
        )}
      </p>
      <ul className="rounded-md border border-border bg-surface">
        {items.map((item, index) => (
          <LifecycleItem key={index} item={item} row={rowOf(item, all)} several={several} onOpen={onOpen} />
        ))}
      </ul>
    </Section>
  )
}

/** La ligne du tableau d'un framework, pour ouvrir son détail. */
function rowOf({ project, finding }: Item, all: Row[]): Row | null {
  if (!finding.dependency) return null
  const key = dependencyKey(finding.dependency)
  return all.find((row) => row.project === project && dependencyKey(row.dependency) === key) ?? null
}

function LifecycleItem({
  item,
  row,
  several,
  onOpen,
}: {
  item: Item
  row: Row | null
  several: boolean
  onOpen: (row: Row) => void
}) {
  const { project, finding, eol } = item
  const runtime = eol.runtime
  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-1 border-border px-4 py-3 not-first:border-t">
      {eol.passed ? (
        <Badge variant="medium">
          <Hourglass aria-hidden="true" />
          Fin de vie
        </Badge>
      ) : (
        <Badge variant="low">
          <Hourglass aria-hidden="true" />
          Bientôt
        </Badge>
      )}
      <div className="flex min-w-0 flex-col gap-1 text-sm">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-semibold">
            {eol.label} <Version>{eol.cycle}</Version>
          </span>
          <Badge variant="outline">{runtime ? 'runtime' : 'framework'}</Badge>
          {several && (
            <Badge variant="outline">
              projet <span className="font-mono">{project.path}</span>
            </Badge>
          )}
        </p>
        <p>{fr(ending(eol))}</p>
        {runtime ? (
          <p className="text-fg-muted">
            Lu dans <span className="font-mono [overflow-wrap:anywhere]">{runtime.file}</span>
            {`${NBSP}: `}
            <span className="font-mono [overflow-wrap:anywhere]">{runtime.source}</span>
            {runtime.approximate && ` (${runtime.version} et plus)`}
          </p>
        ) : (
          finding.dependency && (
            <p className="flex flex-wrap items-center gap-x-2 text-fg-muted">
              Dépendance
              {row ? (
                <PackageButton row={row} onOpen={onOpen} />
              ) : (
                <span className="font-mono font-semibold text-fg">{finding.dependency.name}</span>
              )}
              {finding.current_version && <Version>{finding.current_version}</Version>}
            </p>
          )
        )}
        <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
          {eol.advised_cycle ? (
            <>
              <span>
                {fr('Cycle conseillé :')} <Version>{eol.advised_cycle}</Version>
              </span>
              {eol.advised_lts && <Badge variant="success">LTS</Badge>}
              {eol.advised_version && (
                <>
                  <span aria-hidden="true" className="text-fg-muted">
                    ·
                  </span>
                  <span>
                    dernière version <Version>{eol.advised_version}</Version>
                  </span>
                </>
              )}
            </>
          ) : (
            <span className="text-fg-muted">Aucun cycle maintenu à conseiller.</span>
          )}
        </p>
        {eol.advised_blocked && (
          <p className="flex items-start gap-2 text-warning">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {eol.advised_blocked}
          </p>
        )}
        {finding.url && (
          <p>
            <ExternalLink href={finding.url}>Les cycles de {eol.label} sur endoflife.date</ExternalLink>
          </p>
        )}
      </div>
    </li>
  )
}

/** « Fin de vie depuis le 7 oct. 2024. », « Fin de vie le 10 nov. 2026, dans moins de 6 mois. » */
function ending(eol: EndOfLife): string {
  if (eol.ends_on === null) return 'En fin de vie : endoflife.date n’en donne pas la date.'
  if (eol.passed) return `Fin de vie depuis le ${formatDay(eol.ends_on)}.`
  return `Fin de vie le ${formatDay(eol.ends_on)}, dans moins de 6 mois.`
}
