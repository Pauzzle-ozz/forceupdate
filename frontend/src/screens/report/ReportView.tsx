import {
  CircleCheck,
  CircleHelp,
  FileCode,
  FolderGit2,
  FolderOpen,
  GitPullRequest,
  Info,
  ListChecks,
  PinOff,
  RefreshCw,
  SlidersHorizontal,
  TriangleAlert,
  Upload,
  WifiOff,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import type { CodeFile, Configuration, FindingKind, ForgeKind, Report, ReportOptions, ScanDetail } from '@/api/types'
import { EmptyState } from '@/components/EmptyState'
import { OptionBadges } from '@/components/OptionBadges'
import { Alert, AlertActions, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { ExternalLink } from '@/components/ExternalLink'
import { useRescan } from '@/hooks/useScanActions'
import { useOnline } from '@/hooks/useStatus'
import {
  NBSP,
  basename,
  count,
  formatDate,
  formatDateTime,
  formatDuration,
  formatRelative,
  formatTime,
  fr,
} from '@/lib/format'
import { forgeLabel, requestWord } from '@/lib/proposals'
import {
  DEFAULT_SORT,
  NO_FILTERS,
  filterRows,
  rows as reportRows,
  selectedCount,
  sortRows,
  type Filters,
  type Row,
  type Sort,
} from '@/lib/report'
import { Breadcrumb, Container, PageHead, useDocumentTitle } from '@/shell/Page'
import { Dependencies } from './Dependencies'
import { DependencyDetail } from './DependencyDetail'
import { Ignored, Notices } from './Extras'
import { Lifecycles } from './Lifecycles'
import { Overview } from './Overview'
import { Synthesis } from './Synthesis'

/** Le paquet ouvert dans l'adresse : `?paquet=PyPI:flask` (et `&projet=` s'il y a plusieurs projets). */
function packageParam(row: Row): string {
  return `${row.dependency.ecosystem}:${row.dependency.name}`
}

/** Pourquoi une forge n'a pas rendu toute l'arborescence d'un dépôt. */
const TRUNCATED: Record<ForgeKind, string> = {
  github: 'plus de 100 000 fichiers',
  gitlab: 'trop de fichiers',
  bitbucket: 'trop de fichiers, ou de dossiers imbriqués',
}

/**
 * Écran 4 : le rapport (ECRANS.md, pages/rapport.md, maquette rapport.html) : comprendre ce
 * qui est à mettre à jour, du plus grave au moins grave.
 */
export function ReportView({ scan, report, focusTitle }: { scan: ScanDetail; report: Report; focusTitle: boolean }) {
  const upload = scan.kind === 'upload'
  const repository = scan.repository
  const name = upload || repository ? scan.source : basename(scan.source)
  useDocumentTitle(`Rapport · ${name}`)
  const online = useOnline()
  const start = useRescan()
  const title = useRef<HTMLHeadingElement>(null)
  const table = useRef<HTMLElement>(null)
  const lifecycles = useRef<HTMLElement>(null)
  const [params, setParams] = useSearchParams()
  const [filters, setFilters] = useState<Filters>(NO_FILTERS)
  const [sort, setSort] = useState<Sort>(DEFAULT_SORT)

  useEffect(() => {
    if (focusTitle) title.current?.focus()
  }, [focusTitle])

  const all = useMemo(() => reportRows(report), [report])
  const shown = useMemo(() => sortRows(filterRows(all, filters), sort), [all, filters, sort])
  const summary = report.summary
  const options = report.options
  const selected = selectedCount(report)
  const updates = report.projects.some((project) => project.updates.length > 0)
  const inconclusive = summary.findings.inconclusive ?? 0
  const unpinned = summary.findings.unpinned ?? 0

  const paquet = params.get('paquet')
  const projet = params.get('projet')
  const opened = paquet
    ? all.filter((row) => packageParam(row) === paquet && (!projet || row.project.path === projet))
    : []

  function openDetail(row: Row) {
    const next = new URLSearchParams(params)
    next.set('paquet', packageParam(row))
    if (report.projects.length > 1) next.set('projet', row.project.path)
    setParams(next)
  }

  function closeDetail() {
    const next = new URLSearchParams(params)
    next.delete('paquet')
    next.delete('projet')
    setParams(next, { replace: true })
  }

  function filterKind(kind: FindingKind) {
    setFilters((current) => ({ ...NO_FILTERS, kind: current.kind === kind ? 'all' : kind }))
    // Les fins de vie des runtimes ne sont pas dans le tableau : leur section d'abord.
    const target = kind === 'eol' && lifecycles.current ? lifecycles.current : table.current
    target?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const rescan = (overrides = {}) => start.mutate({ scan, overrides: { offline: !online || scan.options.offline, ...overrides } })
  const rescanOnline = () => start.mutate({ scan, overrides: { offline: false } })

  const actions = (
    <>
      {upload ? (
        <Link to="/choisir?mode=fichier" className={buttonVariants({ variant: 'secondary' })}>
          <Upload aria-hidden="true" />
          Redéposer le fichier
        </Link>
      ) : (
        <Button onClick={() => rescan()} disabled={start.isPending}>
          <RefreshCw aria-hidden="true" />
          Relancer l'analyse
        </Button>
      )}
      {updates && (
        <Link to={`/analyses/${scan.id}/mise-a-jour`} className={buttonVariants({ variant: 'primary' })}>
          {repository ? <GitPullRequest aria-hidden="true" /> : <ListChecks aria-hidden="true" />}
          {repository ? `Préparer la ${requestWord(repository.forge)}` : 'Mettre à jour'}
          <Badge variant="primary" className="ml-1">
            {selected === 0 ? 'aucune cochée' : `${selected} ${selected >= 2 ? 'cochées' : 'cochée'}`}
          </Badge>
        </Link>
      )}
    </>
  )

  const offline = options?.offline ?? false
  const when = report.scanned_at ?? scan.started_at
  const duration = scan.finished_at ? new Date(scan.finished_at).getTime() - new Date(scan.started_at).getTime() : null

  return (
    <Container>
      <Breadcrumb
        items={[repository ? { label: 'Mes dépôts', to: '/depots' } : { label: 'Analyser', to: '/' }, { label: name, mono: true }]}
      />
      <PageHead actions={report.projects.length > 0 ? actions : undefined}>
        <h1 ref={title} tabIndex={-1} className="font-mono text-2xl break-all">
          {name}
        </h1>
        {repository ? (
          <p className="flex flex-wrap items-center gap-x-2 text-sm text-fg-muted">
            <span>
              dépôt {forgeLabel(repository.forge, repository.host)},{' '}
              {repository.cloned ? "cloné : l'API n'en rendait pas toute l'arborescence" : "lu par l'API sans le cloner"}
            </span>
            {repository.commit && (
              <>
                <span aria-hidden="true">·</span>
                <span>
                  commit <code title={repository.commit}>{repository.commit.slice(0, 7)}</code>
                </span>
              </>
            )}
            <span aria-hidden="true">·</span>
            <ExternalLink href={repository.url}>Voir sur {forgeLabel(repository.forge, repository.host)}</ExternalLink>
          </p>
        ) : (
          <p className="font-mono text-sm break-all text-fg-muted">{upload ? 'fichier envoyé' : report.source}</p>
        )}
        {report.code && <CodeReading code={report.code} source={upload ? null : report.source} />}
        <Configured config={report.config} options={report.options} />
        <p className="text-sm text-fg-muted">
          {offline
            ? fr(
                `Analysé hors ligne le ${formatDateTime(when)} · données du cache${
                  report.oldest_data ? `, la plus ancienne du ${formatDate(report.oldest_data)}` : ''
                }`,
              )
            : `Analysé le ${formatDateTime(when)}${duration !== null ? `, en ${formatDuration(duration)}` : ''}${
                report.oldest_data ? ` · registres et OSV interrogés à ${formatTime(report.oldest_data)}` : ''
              }`}
        </p>
        {options && <OptionBadges options={options} />}
      </PageHead>

      {start.error && (
        <p role="alert" className="mb-4 text-sm text-danger">
          {start.error.message}
        </p>
      )}

      {(offline ||
        inconclusive > 0 ||
        unpinned > 0 ||
        repository?.truncated ||
        report.projects.some((project) => project.notices.length > 0)) && (
        <div className="mb-6 flex flex-col gap-4">
          {repository?.truncated && (
            <Alert variant="warning" role="status">
              <TriangleAlert aria-hidden="true" />
              <AlertTitle>Analyse partielle : arborescence incomplète</AlertTitle>
              <AlertDescription>
                <p>
                  {fr(
                    `${forgeLabel(repository.forge, repository.host)} n'a pas rendu toute l'arborescence du dépôt (${TRUNCATED[repository.forge]}) : des fichiers de dépendances peuvent manquer. Ce n'est pas « à jour ».`,
                  )}
                </p>
              </AlertDescription>
            </Alert>
          )}
          {offline && (
            <Alert variant="warning" role="status">
              <WifiOff aria-hidden="true" />
              <AlertTitle>{fr('Analyse hors ligne : données du cache')}</AlertTitle>
              <AlertDescription>
                <p>
                  {report.oldest_data
                    ? fr(
                        `Les versions et les failles viennent du cache ; la plus ancienne donnée date du ${formatDateTime(
                          report.oldest_data,
                        )} (${formatRelative(report.oldest_data)}). Des versions ou des failles publiées depuis peuvent manquer.`,
                      )
                    : fr('Les versions et les failles viennent du cache. Des versions ou des failles publiées depuis peuvent manquer.')}
                </p>
              </AlertDescription>
              {!upload && (
                <AlertActions>
                  <Button size="sm" onClick={rescanOnline} disabled={!online || start.isPending}>
                    Relancer en ligne
                  </Button>
                </AlertActions>
              )}
            </Alert>
          )}
          {inconclusive > 0 && (
            <InconclusiveAlert
              report={report}
              count={inconclusive}
              onShow={() => filterKind('inconclusive')}
              onRescan={upload ? null : () => rescan()}
              pending={start.isPending}
            />
          )}
          {unpinned > 0 && <UnpinnedAlert count={unpinned} onShow={() => filterKind('unpinned')} />}
          {report.projects.some((project) => project.notices.length > 0) && (
            <Alert variant="info" role="status">
              <Info aria-hidden="true" />
              <AlertTitle>{count(report.projects.reduce((n, p) => n + p.notices.length, 0), 'remarque')}</AlertTitle>
              <AlertDescription>
                <p>
                  Des fichiers n'ont pas pu être lus, ou des dépendances vérifiées : <a href="#remarques" className="underline">voir les remarques</a>.
                </p>
              </AlertDescription>
            </Alert>
          )}
        </div>
      )}

      {report.projects.length === 0 ? (
        <EmptyState
          icon={repository ? FolderGit2 : FolderOpen}
          level="h2"
          title={repository ? 'Aucun fichier de dépendances dans ce dépôt' : 'Aucun fichier de dépendances dans ce dossier'}
          actions={
            <>
              {!upload && !options?.include_tests && (
                <Button variant="primary" onClick={() => rescan({ include_tests: true })} disabled={start.isPending}>
                  Analyser aussi les dossiers de tests
                </Button>
              )}
              {repository ? (
                <Link to="/depots" className={buttonVariants({ variant: 'secondary' })}>
                  Revenir aux dépôts
                </Link>
              ) : (
                <Link to="/choisir?mode=dossier" className={buttonVariants({ variant: 'secondary' })}>
                  Choisir un autre dossier
                </Link>
              )}
            </>
          }
        >
          <p>
            forceupdate cherche des manifestes et des lockfiles (<code>package.json</code>, <code>pyproject.toml</code>,{' '}
            <code>requirements.txt</code>, <code>uv.lock</code>…).
            {report.ignored_manifests.length > 0 &&
              ` ${count(report.ignored_manifests.length, 'manifeste rangé', 'manifestes rangés')} dans des dossiers de tests ${
                report.ignored_manifests.length >= 2 ? 'ont été écartés' : 'a été écarté'
              }.`}
          </p>
        </EmptyState>
      ) : (
        <>
          {summary.to_update === 0 && inconclusive === 0 && unpinned === 0 && (
            <UpToDate report={report} onTransitive={upload || options?.transitive ? null : () => rescan({ transitive: true })} pending={start.isPending} />
          )}
          <div>
            <Synthesis summary={summary} kind={filters.kind === 'all' || filters.kind === 'none' ? null : filters.kind} onKind={filterKind} />
            <Overview report={report} />
            <Lifecycles report={report} all={all} onOpen={openDetail} sectionRef={lifecycles} />
            <Dependencies
              report={report}
              all={all}
              shown={shown}
              filters={filters}
              onFilters={setFilters}
              sort={sort}
              onSort={setSort}
              onOpen={openDetail}
              sectionRef={table}
            />
            <Ignored
              report={report}
              onIncludeTests={upload || options?.include_tests ? null : () => rescan({ include_tests: true })}
              pending={start.isPending}
            />
            <Notices report={report} />
          </div>
        </>
      )}

      <DependencyDetail rows={opened} report={report} scanId={scan.id} onClose={closeDetail} />
    </Container>
  )
}

/** La racine de la source : le chemin choisi, sans le chemin du fichier de code relatif à elle. */
function rootOf(source: string, code: CodeFile): string | null {
  return source.endsWith(`/${code.path}`) ? source.slice(0, -code.path.length - 1) : null
}

/** Comment un fichier de code choisi seul a été analysé (E28). */
function CodeReading({ code, source }: { code: CodeFile; source: string | null }) {
  const root = source ? rootOf(source, code) : null
  let text: React.ReactNode
  if (code.reading === 'project') {
    text = (
      <>
        Fichier de code dans un projet{NBSP}: analysé via{' '}
        {code.via.map((path, index) => (
          <span key={path}>
            {index > 0 && (index === code.via.length - 1 ? ' et ' : ', ')}
            <code className="font-mono">{path}</code>
          </span>
        ))}
        {root && (
          <>
            {' '}
            (dans <span className="font-mono break-all">{root}</span>)
          </>
        )}
        , le premier manifeste {code.language ? `${code.language} ` : ''}au-dessus de lui.
      </>
    )
  } else if (code.reading === 'script') {
    text = (
      <>
        Script à bloc PEP 723{NBSP}: son bloc <code className="font-mono">{'# /// script'}</code> tient lieu de manifeste, comme
        pour <code className="font-mono">uv run</code>.
      </>
    )
  } else {
    text = fr('Fichier de code sans projet autour : ses imports, sans version.')
  }
  return (
    <p className="flex items-start gap-2 text-sm">
      <FileCode className="mt-0.5 size-4 shrink-0 text-fg-muted" aria-hidden="true" />
      <span>{text}</span>
    </p>
  )
}

/**
 * Ce que la configuration du projet (`forceupdate.toml`, `[tool.forceupdate]`) et les réglages de
 * la personne ont changé à l'analyse (E29) ; ce que le fichier du projet a d'illisible.
 */
function Configured({ config, options }: { config: Configuration | null; options: ReportOptions | null }) {
  const mine = options !== null && (options.ignore.length > 0 || options.selection.length > 0)
  if (config === null && !mine) return null
  return (
    <>
      {config && (
        <p className="flex items-start gap-2 text-sm">
          <SlidersHorizontal className="mt-0.5 size-4 shrink-0 text-fg-muted" aria-hidden="true" />
          <span>
            {fr('Configuration du projet : ')}
            <code className="font-mono">{config.file}</code>
            {configured(config.ignore, config.selection.length > 0, config.exclude, config.include_tests)}
          </span>
        </p>
      )}
      {config && config.problems.length > 0 && (
        <Alert variant="warning" role="status">
          <TriangleAlert aria-hidden="true" />
          <AlertTitle>{fr(`${config.file} : des valeurs écartées`)}</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-5">
              {config.problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {mine && options && (
        <p className="flex items-start gap-2 text-sm">
          <SlidersHorizontal className="mt-0.5 size-4 shrink-0 text-fg-muted" aria-hidden="true" />
          <span>
            {/* Un lien dans une phrase se distingue autrement que par sa couleur : souligné. */}
            <Link to="/reglages" className="underline">
              Réglages
            </Link>
            {configured(options.ignore, options.selection.length > 0, [], false)}
          </span>
        </p>
      )}
    </>
  )
}

/** « : ignorés : lodash, django@>=5 ; dossiers exclus : legacy ; sélection par défaut réglée. » */
function configured(ignore: string[], selection: boolean, exclude: string[], tests: boolean): React.ReactNode {
  const parts: React.ReactNode[] = []
  if (ignore.length) parts.push(<Listed key="ignore" label="ignorés" values={ignore} />)
  if (exclude.length) parts.push(<Listed key="exclude" label="dossiers exclus" values={exclude} />)
  if (tests) parts.push('dossiers de tests analysés')
  if (selection) parts.push('sélection par défaut réglée')
  if (!parts.length) return '.'
  return (
    <>
      {`${NBSP}: `}
      {parts.map((part, index) => (
        <span key={index}>
          {index > 0 && `${NBSP}; `}
          {part}
        </span>
      ))}
      .
    </>
  )
}

function Listed({ label, values }: { label: string; values: string[] }) {
  return (
    <>
      {`${label}${NBSP}: `}
      {values.map((value, index) => (
        <span key={value}>
          {index > 0 && ', '}
          <code className="font-mono break-all">{value}</code>
        </span>
      ))}
    </>
  )
}

function UnpinnedAlert({ count: total, onShow }: { count: number; onShow: () => void }) {
  return (
    <Alert variant="info" role="status">
      <PinOff aria-hidden="true" />
      <AlertTitle>{count(total, 'version non fixée', 'versions non fixées')}</AlertTitle>
      <AlertDescription>
        <p>
          {fr(
            `Rien ne fixe ${total >= 2 ? 'leur' : 'sa'} version (un import, une dépendance écrite sans version) : seule la dernière publiée est donnée, et les failles ne sont pas vérifiables. Fixer les versions dans un manifeste, un lockfile ou un bloc PEP 723 pour qu'elles le soient.`,
          )}
        </p>
      </AlertDescription>
      <AlertActions>
        <Button size="sm" variant="ghost" onClick={onShow}>
          Voir les versions non fixées
        </Button>
      </AlertActions>
    </Alert>
  )
}

function UpToDate({ report, onTransitive, pending }: { report: Report; onTransitive: (() => void) | null; pending: boolean }) {
  const { summary } = report
  const indirect = report.options && !report.options.transitive && summary.transitive > 0
  return (
    <Alert variant="success" role="status" className="mb-6">
      <CircleCheck aria-hidden="true" />
      <AlertTitle>Rien à mettre à jour</AlertTitle>
      <AlertDescription>
        <p>
          {count(summary.checked, 'dépendance vérifiée', 'dépendances vérifiées')} auprès des registres, à{' '}
          {summary.checked >= 2 ? 'leur' : 'sa'} dernière version ; aucune des {count(summary.audited, 'dépendance auditée', 'dépendances auditées')}{' '}
          n'a de faille connue d'OSV.
          {indirect &&
            ` Les versions des ${count(summary.transitive, 'indirecte')} n'ont pas été comparées aux registres (option « indirectes »).`}
        </p>
      </AlertDescription>
      {indirect && onTransitive && (
        <AlertActions>
          <Button size="sm" onClick={onTransitive} disabled={pending}>
            Relancer avec les indirectes
          </Button>
        </AlertActions>
      )}
    </Alert>
  )
}

function InconclusiveAlert({
  report,
  count: total,
  onShow,
  onRescan,
  pending,
}: {
  report: Report
  count: number
  onShow: () => void
  onRescan: (() => void) | null
  pending: boolean
}) {
  const findings = report.projects.flatMap((project) => project.findings.filter((finding) => finding.kind === 'inconclusive'))
  const shown = findings.slice(0, 5)
  return (
    <Alert variant="inconclusive" role="status">
      <CircleHelp aria-hidden="true" />
      <AlertTitle>
        {total} {total >= 2 ? 'constats non concluants' : 'constat non concluant'}
      </AlertTitle>
      <AlertDescription>
        <ul className="flex flex-col gap-1">
          {shown.map((finding, index) => (
            <li key={index}>
              {finding.dependency && <span className="font-mono font-semibold">{finding.dependency.name}</span>}
              {finding.dependency && `${NBSP}: `}
              {finding.message}
            </li>
          ))}
          {findings.length > shown.length && <li>et {findings.length - shown.length} autres.</li>}
        </ul>
        <p>
          {fr("Ce n'est pas « à jour » : relancer l'analyse quand le réseau ou le registre répondra.")}
        </p>
      </AlertDescription>
      <AlertActions>
        {onRescan && (
          <Button size="sm" onClick={onRescan} disabled={pending}>
            <RefreshCw aria-hidden="true" />
            Relancer l'analyse
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onShow}>
          Voir les non concluants
        </Button>
      </AlertActions>
    </Alert>
  )
}
