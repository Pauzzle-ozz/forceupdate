import { Boxes, ChevronRight, FileCode } from 'lucide-react'
import { cn } from 'cn'
import type { CodeFile, Project, Report } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Card, CardTitle } from '@/components/ui/card'
import { count, fr } from '@/lib/format'
import { ecosystems, runtimeLines } from '@/lib/report'
import { Section } from '@/shell/Page'

/** Langages (du plus lourd au plus léger) et projets, côte à côte au-delà de 900 px. */
export function Overview({ report }: { report: Report }) {
  return (
    <Section aria-labelledby="projets-titre">
      <h2 id="projets-titre" className="sr-only">
        Langages et projets
      </h2>
      <div className="grid grid-cols-1 gap-4 nav:grid-cols-3">
        <Languages report={report} />
        <Projects projects={report.projects} code={report.code} />
      </div>
    </Section>
  )
}

function Languages({ report }: { report: Report }) {
  const total = report.languages.reduce((sum, language) => sum + language.bytes, 0)
  return (
    <Card className="flex flex-col gap-2">
      <CardTitle>
        <FileCode className="size-4" aria-hidden="true" />
        Langages
      </CardTitle>
      {report.languages.length === 0 ? (
        <>
          <p className="text-sm text-fg-muted">
            {fr('Aucun code source reconnu : le dossier ne contient que des fichiers de dépendances.')}
          </p>
          <div className="flex flex-wrap gap-2">
            {ecosystems(report).map((ecosystem) => (
              <Badge key={ecosystem}>{ecosystem}</Badge>
            ))}
          </div>
        </>
      ) : (
        <ul className="flex flex-col gap-1.5 text-sm">
          {report.languages.map((language) => (
            <li key={language.name} className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{language.name}</span>
              <span className="text-fg-muted tabular-nums">
                {total > 0 ? `${Math.max(1, Math.round((language.bytes / total) * 100))} %` : ''}
              </span>
              {language.ecosystem && <Badge>{language.ecosystem}</Badge>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/** Comment se lit le manifeste d'un projet fait d'un fichier de code seul (E28). */
const CODE_MANIFEST: Record<'script' | 'imports', [string, string]> = {
  script: ['Manifeste', 'son bloc PEP 723'],
  imports: ['Fichier de code', 'ses imports, sans version'],
}

function Projects({ projects, code }: { projects: Project[]; code: CodeFile | null }) {
  const alone = code && code.reading !== 'project' ? CODE_MANIFEST[code.reading] : null
  const title = (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <CardTitle>
        <Boxes className="size-4" aria-hidden="true" />
        {count(projects.length, 'projet')}
      </CardTitle>
      <span className="text-sm text-fg-muted">un dossier avec au moins un manifeste</span>
    </div>
  )
  if (projects.length > 3) {
    // Au-delà de 3 projets : une liste repliable, un projet par ligne.
    return (
      <Card className="flex flex-col gap-2 nav:col-span-2">
        {title}
        <details className="group">
          <summary className="inline-flex min-h-(--control-h) items-center gap-2 text-sm font-medium">
            <ChevronRight className="size-4 transition-transform duration-200 group-open:rotate-90" aria-hidden="true" />
            Voir les {projects.length} projets
          </summary>
          <ul className="flex flex-col text-sm">
            {projects.map((project) => (
              <li key={project.path} className="flex flex-wrap items-center gap-2 border-t border-border py-2">
                <span className="font-mono font-semibold break-all">{project.path}</span>
                {project.ecosystems.map((ecosystem) => (
                  <Badge key={ecosystem}>{ecosystem}</Badge>
                ))}
                <span className="text-fg-muted">
                  {count(project.dependencies.length, 'dépendance')} · {count(project.findings.length, 'constat')}
                </span>
              </li>
            ))}
          </ul>
        </details>
      </Card>
    )
  }
  return (
    <Card className="flex flex-col gap-3 nav:col-span-2">
      {title}
      {projects.map((project, index) => (
        <dl
          key={project.path}
          className={cn('grid grid-cols-[max-content_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm', index > 0 && 'border-t border-border pt-3')}
        >
          <dt className="text-fg-muted">Dossier</dt>
          <dd>
            <span className="font-mono break-all">{project.path}</span>
            {project.path === '.' && <span className="text-fg-muted"> (la racine)</span>}
          </dd>
          <dt className="text-fg-muted">{alone ? alone[0] : 'Manifestes'}</dt>
          <dd className="break-all">
            <span className="font-mono">{project.manifests.join(' · ') || '—'}</span>
            {alone && <span className="text-fg-muted"> ({alone[1]})</span>}
          </dd>
          <dt className="text-fg-muted">Lockfiles</dt>
          <dd className="font-mono break-all">{project.lockfiles.join(' · ') || 'aucun'}</dd>
          {project.runtimes.length > 0 && (
            <>
              <dt className="text-fg-muted">Runtimes</dt>
              <dd>
                <ul className="flex flex-col gap-0.5">
                  {runtimeLines(project).map((line) => (
                    <li key={`${line.label}|${line.version}|${line.approximate}`}>
                      {line.label} <span className="font-mono">{line.version}</span>
                      {line.approximate && ' et plus'}{' '}
                      <span className="font-mono break-all text-fg-muted">({line.files.join(', ')})</span>
                    </li>
                  ))}
                </ul>
              </dd>
            </>
          )}
        </dl>
      ))}
    </Card>
  )
}
