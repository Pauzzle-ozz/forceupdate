import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  CircleCheck,
  CircleX,
  Download,
  File,
  GitCommitHorizontal,
  History,
  LoaderCircle,
  Lock,
  Play,
  RefreshCw,
  ServerOff,
  TriangleAlert,
  WifiOff,
} from 'lucide-react'
import { cn } from 'cn'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError, api, queryKeys } from '@/api/client'
import type { LockJob, Report, ScanDetail, UpdatePlan } from '@/api/types'
import { Command } from '@/components/Command'
import { Diff } from '@/components/Diff'
import { EmptyState } from '@/components/EmptyState'
import { Alert, AlertActions, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/choice'
import { ConfirmDialog } from '@/components/ui/dialog'
import { usePlan, useScan } from '@/hooks/useScan'
import { rescanRequest, useStartScan } from '@/hooks/useScanActions'
import { useOnline } from '@/hooks/useStatus'
import { NBSP, basename, count, fr } from '@/lib/format'
import { commandDirectory, listText, plannedFiles, runnableTools, updatesById } from '@/lib/update'
import { Container, Section } from '@/shell/Page'
import { VersionArrow } from '../report/cells'
import { ScanError } from '../ScanPage'
import { ApplyStep } from './ApplyStep'
import { UpdateHeader, UpdateSkeleton } from './Layout'
import { ResultStep } from './ResultStep'

/**
 * `/plans/{id}` : l'écran 5, étapes Vérifier, Appliquer et Résultat, selon où en est le plan ;
 * il se retrouve après un rechargement. Quand l'application avance sous les yeux, le focus
 * suit (titre de l'application, puis le résultat).
 */
export function PlanPage() {
  const { id = '' } = useParams()
  const plan = usePlan(id)
  const scanId = plan.data?.scan ?? ''
  const scan = useScan(scanId, scanId !== '')
  const [live, setLive] = useState(false)

  if (plan.isPending) return <UpdateSkeleton />
  if (plan.isError) return <PlanError error={plan.error} retry={() => void plan.refetch()} />
  // L'analyse se lit une fois le plan connu.
  if (scan.isPending) return <UpdateSkeleton />
  if (scan.isError) return <ScanError error={scan.error} retry={() => void scan.refetch()} title="Mise à jour" />

  const report = scan.data.report
  if (!report) return <ScanError error={new Error("L'analyse de ce plan n'a pas de rapport.")} retry={() => void scan.refetch()} title="Mise à jour" />
  const props = { scan: scan.data, plan: plan.data, report, live }
  switch (plan.data.status) {
    case 'running':
      return <ApplyStep {...props} />
    case 'done':
      return <ResultStep {...props} />
    default:
      return <ReviewStep {...props} onStarted={() => setLive(true)} />
  }
}

function PlanError({ error, retry }: { error: Error; retry: () => void }) {
  if (error instanceof ApiError && error.status === 404) {
    return (
      <Container narrow>
        <EmptyState
          icon={History}
          level="h1"
          title="Ce plan n'existe plus"
          actions={
            <Link to="/" className={buttonVariants({ variant: 'primary' })}>
              Retour à l'accueil
            </Link>
          }
        >
          <p>
            {fr(
              "Le serveur ne garde les plans que le temps de sa session, avec leur analyse. Il a peut-être redémarré : relancer l'analyse depuis l'accueil.",
            )}
          </p>
        </EmptyState>
      </Container>
    )
  }
  return (
    <Container narrow>
      <EmptyState
        icon={ServerOff}
        level="h1"
        title="Plan indisponible"
        actions={
          <Button onClick={retry}>
            <RefreshCw aria-hidden="true" />
            Réessayer
          </Button>
        }
      >
        <p>{error.message}</p>
      </EmptyState>
    </Container>
  )
}

export interface StepProps {
  scan: ScanDetail
  plan: UpdatePlan
  report: Report
  /** L'application a commencé dans cette page (pas un rechargement) : le focus suit. */
  live: boolean
}

/**
 * Étape Vérifier (ECRANS.md, écran 5) : ce qui sera fait, ce qui ne le sera pas et pourquoi,
 * les diffs, les lockfiles (outil trouvé ou commande à lancer), le garde-fou git ; puis
 * appliquer. Un fichier envoyé se télécharge au lieu de s'appliquer. Un plan échoué (fichier
 * changé depuis le diff : rien n'est écrit) reste ici, avec ce qui s'est passé.
 */
function ReviewStep({ scan, plan, report, live, onStarted }: StepProps & { onStarted: () => void }) {
  const client = useQueryClient()
  const online = useOnline()
  const start = useStartScan()
  const upload = scan.kind === 'upload'
  const [confirming, setConfirming] = useState(false)
  // Les cases « en plus » décochées (le npm du projet, go mod vendor) : cochées d'office (E32).
  const [declined, setDeclined] = useState<ReadonlySet<string>>(
    () => new Set(plan.lockfiles.filter((job) => job.extra && !job.accepted).map((job) => job.lockfile)),
  )
  const failedRef = useRef<HTMLDivElement>(null)
  const byId = useMemo(() => updatesById(report), [report])

  const apply = useMutation({
    mutationFn: (force: boolean) =>
      api.applyUpdate({ plan: plan.id, force, ...(declined.size > 0 ? { declined: [...declined] } : {}) }),
    onSuccess: (document) => {
      onStarted()
      client.setQueryData(queryKeys.plan(plan.id), document)
    },
    onError: (error) => {
      // Garde-fou revérifié, ou plan déjà appliqué ailleurs : le plan relu le montre.
      if (error instanceof ApiError && error.status === 409) {
        void client.invalidateQueries({ queryKey: queryKeys.plan(plan.id) })
      }
    },
  })

  const failed = plan.status === 'failed'
  useEffect(() => {
    if (live && failed) failedRef.current?.focus()
  }, [live, failed])

  const dirty = plan.uncommitted !== null && plan.uncommitted.length > 0
  const tools = runnableTools(plan.lockfiles)
  const runnable = plan.lockfiles.filter((job) => job.available).length
  const commands = plan.lockfiles.length - runnable
  const name = (update: string) => byId.get(update)?.update.name ?? update
  const rescan = () => start.mutate(rescanRequest(scan, { offline: !online || scan.options.offline }))

  return (
    <Container>
      <UpdateHeader scan={scan} step={1} />
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col">
          {(failed || (!upload && !online && tools.length > 0) || upload) && (
            <div className="flex flex-col gap-4">
              {failed && (
                <Alert variant="danger" role="alert" ref={failedRef} tabIndex={-1}>
                  <CircleX aria-hidden="true" />
                  <AlertTitle>Rien n'a été écrit</AlertTitle>
                  <AlertDescription>
                    <p>{plan.error ?? "Le serveur n'a pas donné de raison."}</p>
                    <p>{fr("Relancer l'analyse pour repartir des fichiers actuels.")}</p>
                  </AlertDescription>
                  <AlertActions>
                    <Button variant="primary" size="sm" onClick={rescan} disabled={start.isPending}>
                      <RefreshCw aria-hidden="true" />
                      Relancer l'analyse
                    </Button>
                  </AlertActions>
                </Alert>
              )}
              {!upload && !online && tools.length > 0 && (
                <Alert variant="warning" role="status">
                  <WifiOff aria-hidden="true" />
                  <AlertTitle>Pas de réseau</AlertTitle>
                  <AlertDescription>
                    <p>
                      {fr(
                        `${listText(tools)} ${tools.length >= 2 ? 'en ont' : 'en a'} besoin pour régénérer les lockfiles : ${
                          tools.length >= 2 ? 'ils échoueront' : 'il échouera'
                        }, et leurs fichiers seront remis comme avant (manifestes compris). Attendre le réseau pour appliquer.`,
                      )}
                    </p>
                  </AlertDescription>
                </Alert>
              )}
              {upload && (
                <Alert variant="info" role="status">
                  <File aria-hidden="true" />
                  <AlertTitle>{fr("Fichier envoyé : rien ne s'écrit sur le disque")}</AlertTitle>
                  <AlertDescription>
                    <p>
                      {fr(
                        "Le navigateur ne laisse pas réécrire le fichier d'origine : sa version mise à jour se télécharge. Aucun lockfile n'est régénéré ; après avoir remplacé le fichier, relancer l'outil du projet (npm install, uv lock…).",
                      )}
                    </p>
                  </AlertDescription>
                </Alert>
              )}
            </div>
          )}

          <Section aria-labelledby="plan-quoi">
            <h2 id="plan-quoi" className="text-lg">
              Ce qui sera fait
            </h2>
            {plan.applied.length === 0 ? (
              <p className="text-sm text-fg-muted">{fr('Rien : aucune des options choisies ne peut être appliquée.')}</p>
            ) : (
              <ul className="rounded-md border border-border bg-surface">
                {plan.applied.map((chosen) => {
                  const found = byId.get(chosen.update)
                  const touched = found ? plannedFiles(plan, found.update, chosen.version) : null
                  return (
                    <li
                      key={chosen.update}
                      className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1 border-border px-4 py-3 not-first:border-t md:grid-cols-[auto_minmax(0,1fr)_auto]"
                    >
                      <Check className="size-5 text-success" aria-hidden="true" />
                      <span className="flex flex-wrap items-center gap-2">
                        <b className="font-mono">{name(chosen.update)}</b>
                        <VersionArrow from={found?.update.current_version ?? null} to={chosen.version} />
                      </span>
                      {touched && touched.files.length > 0 && (
                        <span className="col-start-2 font-mono text-sm text-fg-muted [overflow-wrap:anywhere] md:col-start-3">
                          {touched.lockfileOnly ? `${touched.files.join(', ')} seul` : touched.files.join(', ')}
                        </span>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </Section>

          {plan.skipped.length > 0 && (
            <Section aria-labelledby="plan-saute">
              <h2 id="plan-saute" className="text-lg">
                Pas appliqué
              </h2>
              <ul className="flex flex-col gap-2">
                {plan.skipped.map((skipped) => (
                  <li key={`${skipped.update}|${skipped.version}`} className="flex items-start gap-2 text-sm">
                    <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
                    <span>
                      <b className="font-mono">{name(skipped.update)}</b> <span className="font-mono">{skipped.version}</span>
                      {`${NBSP}: `}
                      {skipped.reason}
                    </span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          <Section aria-labelledby="plan-diffs">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 id="plan-diffs" className="text-lg">
                Fichiers réécrits
              </h2>
              {plan.files.length > 0 && (
                <span className="text-sm text-fg-muted">
                  {count(plan.files.length, 'fichier')} · seules les contraintes changent
                </span>
              )}
            </div>
            {plan.files.length === 0 ? (
              <p className="text-sm text-fg-muted">
                {fr('Aucun manifeste réécrit : les versions choisies sont déjà permises, seuls les lockfiles changent.')}
              </p>
            ) : (
              plan.files.map((file) => <Diff key={file.path} path={file.path} diff={file.diff} />)
            )}
          </Section>

          {!upload && plan.lockfiles.length > 0 && (
            <Section aria-labelledby="plan-lockfiles">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 id="plan-lockfiles" className="text-lg">
                  Lockfiles régénérés
                </h2>
                <span className="text-sm text-fg-muted">dans l'ordre, après la réécriture, sans les scripts du projet</span>
              </div>
              {plan.lockfiles.map((job) => (
                <LockJobCard
                  key={job.lockfile}
                  job={job}
                  source={scan.source}
                  name={name}
                  accepted={!declined.has(job.lockfile)}
                  editable={plan.applicable && !apply.isPending}
                  onAccept={(accepted) =>
                    setDeclined((current) => {
                      const next = new Set(current)
                      if (accepted) next.delete(job.lockfile)
                      else next.add(job.lockfile)
                      return next
                    })
                  }
                />
              ))}
            </Section>
          )}
        </div>

        <aside aria-labelledby="plan-action" className="lg:sticky lg:top-[calc(var(--header-h)+16px)]">
          <Card className="flex flex-col gap-4">
            <h2 id="plan-action" className="text-lg">
              {upload ? 'Télécharger' : 'Appliquer'}
            </h2>
            {!upload && <GitGuard uncommitted={plan.uncommitted} />}
            {!upload && (
              <ul className="flex flex-col gap-2 text-sm">
                <li className="flex justify-between gap-3">
                  <span>Mises à jour</span>
                  <b className="tabular-nums">{plan.applied.length}</b>
                </li>
                <li className="flex justify-between gap-3">
                  <span>Fichiers réécrits</span>
                  <b className="tabular-nums">{plan.files.length}</b>
                </li>
                <li className="flex justify-between gap-3">
                  <span>Lockfiles régénérés</span>
                  <b className="tabular-nums">
                    {runnable}
                    {commands > 0 && ` (et ${count(commands, 'commande')})`}
                  </b>
                </li>
              </ul>
            )}

            {upload ? (
              plan.files.length > 0 ? (
                plan.files.map((file, index) => (
                  <a
                    key={file.path}
                    href={api.planFileUrl(plan.id, file.path)}
                    download={basename(file.path)}
                    className={buttonVariants({ variant: index === 0 ? 'primary' : 'secondary', className: 'w-full' })}
                  >
                    <Download aria-hidden="true" />
                    Télécharger <span className="font-mono">{basename(file.path)}</span>
                  </a>
                ))
              ) : (
                <p className="text-sm text-fg-muted">{fr('Rien à télécharger : aucune option choisie ne réécrit le fichier.')}</p>
              )
            ) : (
              <>
                {!failed && !plan.applicable && (
                  <p className="text-sm text-fg-muted">{fr('Rien à écrire ni à lancer : revoir la sélection.')}</p>
                )}
                {dirty && !failed ? (
                  <Button variant="danger" className="w-full" onClick={() => setConfirming(true)} disabled={apply.isPending}>
                    Appliquer quand même…
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    className="w-full"
                    onClick={() => apply.mutate(false)}
                    disabled={failed || !plan.applicable || apply.isPending}
                  >
                    {apply.isPending ? (
                      <LoaderCircle className="animate-spin" aria-hidden="true" />
                    ) : (
                      <Play aria-hidden="true" />
                    )}
                    Appliquer
                  </Button>
                )}
              </>
            )}
            {apply.error && (
              <p role="alert" className="text-sm text-danger">
                {apply.error.message}
              </p>
            )}
            <Link
              to={`/analyses/${scan.id}/mise-a-jour?plan=${plan.id}`}
              className={buttonVariants({ variant: 'secondary', className: 'w-full' })}
            >
              Modifier la sélection
            </Link>
            {!upload && (
              <p className="text-sm text-fg-muted">
                {fr("Une mise à jour lancée ne s'interrompt pas. Si un outil échoue, ses fichiers sont remis comme avant.")}
              </p>
            )}
          </Card>
        </aside>
      </div>

      <ConfirmDialog
        open={confirming}
        title={fr('Appliquer malgré les changements non commités ?')}
        confirm="Appliquer quand même"
        onCancel={() => setConfirming(false)}
        onConfirm={() => {
          setConfirming(false)
          apply.mutate(true)
        }}
      >
        <p>
          La mise à jour s'écrira par-dessus les changements en attente de{' '}
          <span className="font-mono">{listText(plan.uncommitted ?? [])}</span>. Git ne permettra plus de séparer les deux.
        </p>
      </ConfirmDialog>
    </Container>
  )
}

/** Le garde-fou git (pages/mise-a-jour.md, « Garde-fou et confirmation »). */
function GitGuard({ uncommitted }: { uncommitted: string[] | null }) {
  if (uncommitted === null) {
    return (
      <Alert variant="warning" role="status">
        <TriangleAlert aria-hidden="true" />
        <AlertTitle>Hors d'un dépôt git</AlertTitle>
        <AlertDescription>
          <p>{fr("Rien ne permettra de revenir en arrière. Faire une copie du dossier avant d'appliquer.")}</p>
        </AlertDescription>
      </Alert>
    )
  }
  if (uncommitted.length > 0) {
    return (
      <Alert variant="warning" role="status">
        <TriangleAlert aria-hidden="true" />
        <AlertTitle>Changements pas encore commités</AlertTitle>
        <AlertDescription>
          <p>
            <span className="font-mono">{listText(uncommitted)}</span>{' '}
            {fr(
              `${uncommitted.length >= 2 ? 'ont' : 'a'} des changements que git n'a pas en commit : la mise à jour s'y mêlerait. Les commiter d'abord, puis appliquer.`,
            )}
          </p>
        </AlertDescription>
      </Alert>
    )
  }
  return (
    <Alert variant="success" role="status">
      <GitCommitHorizontal aria-hidden="true" />
      <AlertTitle>Git peut tout défaire</AlertTitle>
      <AlertDescription>
        <p>Les fichiers à écrire n'ont pas de changements en attente.</p>
      </AlertDescription>
    </Alert>
  )
}

/**
 * Un lockfile à régénérer : l'outil trouvé ou absent, ce que forceupdate propose en plus (une case
 * cochée d'office : le npm du projet, `go mod vendor`), la commande, ses avertissements.
 */
function LockJobCard({
  job,
  source,
  name,
  accepted,
  editable,
  onAccept,
}: {
  job: LockJob
  source: string
  name: (update: string) => string
  accepted: boolean
  editable: boolean
  onAccept: (accepted: boolean) => void
}) {
  const id = useId()
  const command = job.extra && !accepted ? job.extra.declined : job.command
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Lock className="size-5 shrink-0" aria-hidden="true" />
          <h3 className="font-mono text-base break-all">{job.lockfile}</h3>
          {job.updates.length > 0 && (
            <span className="text-sm text-fg-muted">
              {job.updates.map((chosen) => `${name(chosen.update)} ${chosen.version}`).join(', ')}
            </span>
          )}
          {job.workspace && <Badge variant="outline">workspace</Badge>}
        </div>
        {job.available ? (
          <Badge variant="success">
            <CircleCheck aria-hidden="true" />
            {job.program} trouvé
          </Badge>
        ) : (
          <Badge variant="warning">
            <TriangleAlert aria-hidden="true" />
            {job.program} absent
          </Badge>
        )}
      </div>
      {job.reason && <p className="text-sm">{fr(`Régénéré sans mise à jour à lui : ${job.reason}.`)}</p>}
      {job.extra && (
        <div
          className={cn(
            'flex items-start gap-3 rounded-sm border p-3 transition-colors duration-150',
            accepted ? 'border-primary/50 bg-primary-soft' : 'border-border',
          )}
        >
          <Checkbox
            id={`${id}-case`}
            checked={accepted}
            disabled={!editable}
            onChange={(event) => onAccept(event.target.checked)}
            aria-describedby={`${id}-detail`}
            className="mt-0.5 shrink-0"
          />
          <div className="flex min-w-0 flex-col gap-1">
            <label htmlFor={`${id}-case`} className={cn('font-medium', editable && 'cursor-pointer')}>
              {job.extra.label}
            </label>
            <p id={`${id}-detail`} className="text-sm text-fg-muted">
              {fr(job.extra.detail)}
            </p>
          </div>
        </div>
      )}
      {!job.available && (
        <p className="text-sm">
          {job.program} n'est pas installé{NBSP}: <span className="font-mono">{job.lockfile}</span> ne sera pas régénéré.
          Les manifestes seront quand même réécrits{NBSP}; lancer ensuite cette commande dans{' '}
          <span className="font-mono [overflow-wrap:anywhere]">{commandDirectory(source, job.directory)}</span>
          {NBSP}:
        </p>
      )}
      <Command command={command} label={`la commande de ${job.lockfile}`} />
      {job.warnings.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm">
          {job.warnings.map((warning) => (
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
