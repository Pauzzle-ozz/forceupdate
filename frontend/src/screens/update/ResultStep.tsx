import {
  Check,
  CircleCheck,
  CircleHelp,
  CircleX,
  FileDiff,
  Info,
  Lock,
  RefreshCw,
  RotateCcw,
  Terminal,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'
import { Link } from 'react-router'
import type { InstalledVersion, LockJob, LockResult, LockStatus, UpdatePlan } from '@/api/types'
import { Command } from '@/components/Command'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { rescanRequest, useStartScan } from '@/hooks/useScanActions'
import { useOnline } from '@/hooks/useStatus'
import { NBSP, count, fr } from '@/lib/format'
import { commandDirectory, lastLines, listText, updatesById } from '@/lib/update'
import { Container } from '@/shell/Page'
import { VersionArrow } from '../report/cells'
import { UpdateHeader } from './Layout'
import type { StepProps } from './PlanPage'

const STATUS: Record<LockStatus, { label: string; variant: 'success' | 'warning' | 'danger'; icon: LucideIcon }> = {
  regenerated: { label: 'régénéré', variant: 'success', icon: CircleCheck },
  tool_missing: { label: 'commande à lancer', variant: 'warning', icon: Terminal },
  failed: { label: 'échec, fichiers remis', variant: 'danger', icon: CircleX },
  undone: { label: 'défait, fichiers remis', variant: 'warning', icon: RotateCcw },
}

/**
 * Étape Résultat (ECRANS.md, écran 5 ; pages/mise-a-jour.md, « Résultat ») : par lockfile, son
 * statut, les versions obtenues (exacte, plus haute, retenue), ce qui a changé d'autre, les
 * fichiers remis et ce qu'a dit l'outil en échec ; puis relancer l'analyse.
 */
export function ResultStep({ scan, plan, report, live }: StepProps) {
  const online = useOnline()
  const start = useStartScan()
  const outcome = useRef<HTMLDivElement>(null)
  const byId = useMemo(() => updatesById(report), [report])
  const jobs = new Map(plan.lockfiles.map((job) => [job.lockfile, job]))
  const failed = plan.results.some((result) => result.status === 'failed')

  useEffect(() => {
    if (live) outcome.current?.focus()
  }, [live])

  return (
    <Container>
      <UpdateHeader scan={scan} step={3} />
      <div className="flex max-w-215 flex-col gap-4">
        <Outcome plan={plan} jobs={jobs} outcomeRef={outcome} />
        {plan.results.map((result) => (
          <ResultCard
            key={result.lockfile}
            result={result}
            job={jobs.get(result.lockfile) ?? null}
            source={scan.source}
            selection={plan.selection}
            describe={(update) => byId.get(update)?.update ?? null}
          />
        ))}
        {plan.results.length === 0 && plan.files.length > 0 && (
          <Card className="flex flex-col gap-2 p-4">
            <h2 className="flex items-center gap-2 text-base">
              <FileDiff className="size-5" aria-hidden="true" />
              Fichiers réécrits
            </h2>
            <p className="font-mono text-sm [overflow-wrap:anywhere]">{plan.files.map((file) => file.path).join(', ')}</p>
            <p className="text-sm text-fg-muted">{fr("Pas de lockfile : relancer l'installation du projet pour prendre les nouvelles versions.")}</p>
          </Card>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            onClick={() => start.mutate(rescanRequest(scan, { offline: !online || scan.options.offline }))}
            disabled={start.isPending}
          >
            <RefreshCw aria-hidden="true" />
            Relancer l'analyse
          </Button>
          <Link to={`/analyses/${scan.id}`} className={buttonVariants({ variant: 'secondary' })}>
            Revoir l'ancien rapport
          </Link>
          {failed && (
            <Link to={`/analyses/${scan.id}/mise-a-jour?plan=${plan.id}`} className={buttonVariants({ variant: 'secondary' })}>
              Réessayer
            </Link>
          )}
        </div>
        {start.error && (
          <p role="alert" className="text-sm text-danger">
            {start.error.message}
          </p>
        )}
      </div>
    </Container>
  )
}

/** Ce qu'il en est, en une alerte : appliquée, une commande reste à lancer, ou un outil a échoué. */
function Outcome({
  plan,
  jobs,
  outcomeRef,
}: {
  plan: UpdatePlan
  jobs: Map<string, LockJob>
  outcomeRef: React.Ref<HTMLDivElement>
}) {
  const results = plan.results
  const failed = results.filter((result) => result.status === 'failed')
  const missing = results.filter((result) => result.status === 'tool_missing')
  const regenerated = results.filter((result) => result.status === 'regenerated')
  const installed = regenerated.flatMap((result) => result.installed)
  const elsewhere = installed.filter((version) => version.reach !== 'exact').length
  const tool = (result: LockResult) => jobs.get(result.lockfile)?.tool ?? "L'outil"

  if (failed.length > 0) {
    const restored = [...new Set(results.flatMap((result) => result.restored))]
    return (
      <Alert variant="danger" role="alert" ref={outcomeRef} tabIndex={-1}>
        <CircleX aria-hidden="true" />
        <AlertTitle>
          {fr(
            failed.length === 1
              ? `${tool(failed[0])} a échoué : ses fichiers sont remis comme avant`
              : `${failed.length} outils ont échoué : leurs fichiers sont remis comme avant`,
          )}
        </AlertTitle>
        <AlertDescription>
          {restored.length > 0 && (
            <p>
              <span className="font-mono">{listText(restored)}</span>{' '}
              {restored.length >= 2 ? "sont revenus à leur état d'avant." : "est revenu à son état d'avant."}
            </p>
          )}
          {regenerated.length > 0 && (
            <p>
              <span className="font-mono">{listText(regenerated.map((result) => result.lockfile))}</span>
              {fr(`, qui ne dépend pas d'eux, ${regenerated.length >= 2 ? 'sont bien mis' : 'est bien mis'} à jour.`)}
            </p>
          )}
        </AlertDescription>
      </Alert>
    )
  }
  if (missing.length > 0) {
    return (
      <Alert variant="warning" role="status" ref={outcomeRef} tabIndex={-1}>
        <Terminal aria-hidden="true" />
        <AlertTitle>
          {missing.length === 1 ? 'Appliquée, une commande reste à lancer' : `Appliquée, ${missing.length} commandes restent à lancer`}
        </AlertTitle>
        <AlertDescription>
          <p>
            {fr('Les manifestes sont réécrits ; ')}
            <span className="font-mono">{listText(missing.map((result) => result.lockfile))}</span>{' '}
            {fr(
              `${missing.length >= 2 ? 'attendent leur' : 'attend sa'} régénération (${listText(
                [...new Set(missing.map((result) => jobs.get(result.lockfile)?.program ?? "l'outil"))],
              )} ${missing.length >= 2 ? 'ne sont pas installés' : "n'est pas installé"}).`,
            )}
          </p>
        </AlertDescription>
      </Alert>
    )
  }
  const applied = plan.applied.length
  return (
    <Alert variant="success" role="status" ref={outcomeRef} tabIndex={-1}>
      <CircleCheck aria-hidden="true" />
      <AlertTitle>Mise à jour appliquée</AlertTitle>
      <AlertDescription>
        <p>
          {count(applied, 'mise à jour', 'mises à jour')}
          {installed.length === 0
            ? '.'
            : elsewhere === 0
              ? applied >= 2
                ? ', toutes à la version demandée.'
                : ', à la version demandée.'
              : fr(`, dont ${elsewhere} à une autre version que celle demandée : voir ci-dessous.`)}{' '}
          {plan.uncommitted === null
            ? 'Relire les fichiers réécrits, puis lancer les tests.'
            : 'Relire avec git diff, lancer les tests, puis commiter.'}
        </p>
      </AlertDescription>
    </Alert>
  )
}

/** Un lockfile, après : son statut, et selon lui les versions, la commande, ou l'erreur. */
function ResultCard({
  result,
  job,
  source,
  selection,
  describe,
}: {
  result: LockResult
  job: LockJob | null
  source: string
  selection: Record<string, string>
  describe: (update: string) => { name: string; current_version: string | null } | null
}) {
  const status = STATUS[result.status]
  const StatusIcon = status.icon
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Lock className="size-5 shrink-0" aria-hidden="true" />
          <h2 className="font-mono text-base break-all">{result.lockfile}</h2>
          {job && <span className="text-sm text-fg-muted">{job.tool}</span>}
        </div>
        <Badge variant={status.variant}>
          <StatusIcon aria-hidden="true" />
          {status.label}
        </Badge>
      </div>

      {result.status === 'regenerated' && (
        <>
          {result.installed.length > 0 && (
            <ul className="flex flex-col gap-2 text-sm">
              {result.installed.map((installed) => {
                const update = describe(installed.update)
                return (
                  <li key={installed.update} className="flex flex-wrap items-center justify-between gap-2">
                    <span className="flex flex-wrap items-center gap-2">
                      <b className="font-mono">{update?.name ?? installed.update}</b>
                      <VersionArrow from={update?.current_version ?? null} to={installed.version} />
                      {installed.versions.length > 1 && (
                        <span className="text-fg-muted">
                          {fr(`(installées : ${installed.versions.join(', ')})`)}
                        </span>
                      )}
                    </span>
                    <ReachBadge installed={installed} chosen={selection[installed.update]} />
                  </li>
                )
              })}
            </ul>
          )}
          {result.changed.length > 0 ? (
            <div className="flex flex-col gap-1 text-sm">
              <p>{fr('Aussi changé dans le lockfile :')}</p>
              <ul className="flex flex-col gap-0.5 font-mono text-fg-muted">
                {result.changed.map((change) => (
                  <li key={change}>{change}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-fg-muted">Rien d'autre n'a changé dans le lockfile.</p>
          )}
        </>
      )}

      {result.status === 'tool_missing' && job && (
        <div className="flex flex-col gap-2">
          <p className="text-sm">
            Dans <span className="font-mono [overflow-wrap:anywhere]">{commandDirectory(source, job.directory)}</span>, lancer
            {NBSP}:
          </p>
          <Command command={job.command} label={`la commande de ${result.lockfile}`} />
        </div>
      )}

      {result.status === 'failed' && result.error && (
        <div className="flex flex-col gap-2">
          <p className="text-sm">{fr("Ce qu'a dit l'outil (dernières lignes) :")}</p>
          <pre
            role="region"
            aria-label={`Sortie de ${job?.tool ?? "l'outil"}`}
            // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- défilement horizontal au clavier
            tabIndex={0}
            className="max-h-72 overflow-auto rounded-sm border border-border bg-surface-2 p-3 font-mono text-[13px] leading-[1.55]"
          >
            <code className="whitespace-pre">{lastLines(result.error)}</code>
          </pre>
        </div>
      )}

      {result.status === 'undone' && result.error && <p className="text-sm">{result.error}</p>}

      {result.restored.length > 0 && (
        <p className="text-sm">
          {fr('Fichiers remis comme avant : ')}
          <span className="font-mono">{result.restored.join(', ')}</span>
        </p>
      )}

      {result.warnings.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm">
          {result.warnings.map((warning) => (
            <li key={warning} className="flex items-start gap-2 text-warning">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {warning}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/** La version obtenue : exacte, plus haute que choisie, retenue par un autre paquet, ou inconnue. */
function ReachBadge({ installed, chosen }: { installed: InstalledVersion; chosen: string | undefined }) {
  switch (installed.reach) {
    case 'exact':
      return (
        <Badge variant="success">
          <Check aria-hidden="true" />
          version exacte
        </Badge>
      )
    case 'above':
      return (
        <Badge variant="info">
          <Info aria-hidden="true" />
          plus haute que choisie{chosen ? ` (${chosen})` : ''}
        </Badge>
      )
    case 'below':
      return (
        <Badge variant="warning" className="whitespace-normal">
          <TriangleAlert aria-hidden="true" />
          {installed.held_by.length > 0 ? `retenue par ${installed.held_by.join(', ')}` : 'plus basse que choisie'}
        </Badge>
      )
    default:
      return (
        <Badge variant="inconclusive">
          <CircleHelp aria-hidden="true" />
          version non relue
        </Badge>
      )
  }
}
