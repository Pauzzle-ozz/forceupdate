import { ChevronRight, FileWarning } from 'lucide-react'
import type { Report } from '@/api/types'
import { SeverityBadge } from '@/components/badges'
import { Button } from '@/components/ui/button'
import { count, fr } from '@/lib/format'
import { Section } from '@/shell/Page'

/** Les fichiers écartés (dossiers de tests, de fixtures, d'exemples), repliés. */
export function Ignored({
  report,
  onIncludeTests,
  pending,
}: {
  report: Report
  onIncludeTests: (() => void) | null
  pending: boolean
}) {
  const ignored = report.ignored_manifests
  return (
    <Section aria-labelledby="ecartes-titre">
      <details className="group">
        <summary className="inline-flex min-h-(--control-h) items-center gap-2 text-sm font-medium">
          <ChevronRight className="size-4 transition-transform duration-200 group-open:rotate-90" aria-hidden="true" />
          <span id="ecartes-titre">Fichiers écartés ({ignored.length})</span>
        </summary>
        <div className="flex flex-col gap-3 pl-6">
          {ignored.length === 0 ? (
            <p className="text-sm text-fg-muted">
              {report.options?.include_tests
                ? 'Aucun : les dossiers de tests et d’exemples ont été analysés.'
                : "Aucun manifeste écarté. Ceux des dossiers de tests, de fixtures ou d'exemples seraient listés ici, avec de quoi relancer l'analyse en les gardant."}
            </p>
          ) : (
            <>
              <p className="text-sm text-fg-muted">
                Rangés dans des dossiers de tests, de fixtures ou d'exemples : ils ne font pas de projet.
              </p>
              <ul className="flex flex-col gap-1 font-mono text-sm break-all">
                {ignored.map((path) => (
                  <li key={path}>{path}</li>
                ))}
              </ul>
              {onIncludeTests && (
                <div>
                  <Button size="sm" onClick={onIncludeTests} disabled={pending}>
                    Analyser aussi les dossiers de tests
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      </details>
    </Section>
  )
}

/** Les remarques : ce que l'analyse n'a pas pu lire, ou pas pu vérifier, par fichier. */
export function Notices({ report }: { report: Report }) {
  const notices = report.projects.flatMap((project) => project.notices)
  // Les fins de vie des runtimes ont leur section (Lifecycles) : ici, le reste.
  const loose = report.projects.flatMap((project) =>
    project.findings.filter((finding) => !finding.dependency && finding.kind !== 'eol'),
  )
  if (notices.length === 0 && loose.length === 0) return null
  return (
    <>
      {loose.length > 0 && (
        <Section aria-labelledby="autres-titre">
          <h2 id="autres-titre" className="text-xl">
            Autres constats
          </h2>
          <ul className="rounded-md border border-border bg-surface">
            {loose.map((finding, index) => (
              <li key={index} className="flex flex-wrap items-start gap-3 border-border px-4 py-3 not-first:border-t">
                <SeverityBadge severity={finding.severity} />
                <span className="min-w-0 flex-1 text-sm">{finding.message}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
      {notices.length > 0 && (
        <Section aria-labelledby="remarques-titre" id="remarques">
          <h2 id="remarques-titre" className="text-xl">
            Remarques
          </h2>
          <p className="text-sm text-fg-muted">
            {fr(`${count(notices.length, 'remarque')} : ce que l'analyse n'a pas pu lire, ou pas pu vérifier.`)}
          </p>
          <ul className="rounded-md border border-border bg-surface">
            {notices.map((notice, index) => (
              <li key={index} className="flex items-start gap-3 border-border px-4 py-3 not-first:border-t">
                <FileWarning className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
                <div className="min-w-0 text-sm">
                  <span className="font-mono font-semibold break-all">{notice.file}</span>
                  <p>{notice.message}</p>
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </>
  )
}
