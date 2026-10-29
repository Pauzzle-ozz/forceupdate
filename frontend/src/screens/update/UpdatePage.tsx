import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CircleCheck, CircleHelp, CircleX, GitPullRequest, LoaderCircle, RefreshCw, RotateCcw, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { cn } from 'cn'
import { api, queryKeys } from '@/api/client'
import type { Proposal, ProposedSelection, Report, ScanDetail, Selection } from '@/api/types'
import { EmptyState } from '@/components/EmptyState'
import { Alert, AlertActions, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useCreateProposal, useProposal } from '@/hooks/useProposals'
import { usePlan, useScan } from '@/hooks/useScan'
import { useRescan } from '@/hooks/useScanActions'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { NBSP, count, fr } from '@/lib/format'
import { choose, defaultSelection, groups, recap, toggle, type Group, type Recap } from '@/lib/update'
import { Container } from '@/shell/Page'
import { ScanError } from '../ScanPage'
import { PreparingPlan, UpdateHeader, UpdateSkeleton } from './Layout'
import { UpdateCard } from './UpdateCard'

/**
 * `/analyses/{id}/mise-a-jour` : l'écran 5, étape Choisir (ECRANS.md, pages/mise-a-jour.md,
 * maquette mise-a-jour.html). Avec `?plan=<id>` (« Modifier la sélection », ou le retour du
 * navigateur depuis le plan), la sélection de ce plan revient ; avec `?paquet=<Update.id>`
 * (le panneau de détail du rapport), la carte de ce paquet reçoit le focus.
 *
 * Un dépôt d'une forge se met à jour par une PR (E18) : la sélection prépare son récapitulatif
 * (écran 8). Avec `?pr=<id>` (« Modifier la sélection » d'un récapitulatif), la sélection de ce
 * dépôt dans ce récapitulatif revient, et le nouveau récapitulatif garde les autres dépôts.
 */
export function UpdatePage() {
  const { id = '' } = useParams()
  const [params] = useSearchParams()
  const from = params.get('plan')
  const fromProposal = params.get('pr')
  const scan = useScan(id)
  const previous = usePlan(from ?? '', from !== null)
  const proposal = useProposal(fromProposal ?? '', fromProposal !== null)

  if (scan.isPending || (from !== null && previous.isPending) || (fromProposal !== null && proposal.isPending)) {
    return <UpdateSkeleton />
  }
  if (scan.isError) return <ScanError error={scan.error} retry={() => void scan.refetch()} title="Mise à jour" />

  const data = scan.data
  if (data.status !== 'done' || !data.report) return <NoReport scan={data} />
  const proposed = proposal.data?.repositories.find((item) => item.scan === id && item.state === 'ready')
  let initial = defaultSelection(data.report)
  if (previous.data?.scan === id) initial = previous.data.selection
  else if (proposed) initial = proposed.selection
  return <SelectStep scan={data} report={data.report} initial={initial} proposal={proposal.data ?? null} />
}

/** L'analyse tourne encore, ou n'a pas abouti : pas de rapport, donc rien à choisir. */
function NoReport({ scan }: { scan: ScanDetail }) {
  const running = scan.status === 'running'
  return (
    <Container narrow>
      <UpdateHeader scan={scan} step={0} />
      <EmptyState
        icon={running ? LoaderCircle : CircleX}
        level="h2"
        title={running ? "L'analyse n'est pas finie" : "Cette analyse n'a pas de rapport"}
        actions={
          <Link to={`/analyses/${scan.id}`} className={buttonVariants({ variant: 'primary' })}>
            {running ? "Suivre l'analyse" : "Revoir l'analyse"}
          </Link>
        }
      >
        <p>{fr("Les mises à jour se choisissent sur le rapport : il arrive à la fin de l'analyse.")}</p>
      </EmptyState>
    </Container>
  )
}

function SelectStep({
  scan,
  report,
  initial,
  proposal,
}: {
  scan: ScanDetail
  report: Report
  initial: Selection
  /** Le récapitulatif d'où l'on vient (« Modifier la sélection »), pour un dépôt. */
  proposal: Proposal | null
}) {
  const [selection, setSelection] = useState<Selection>(initial)
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const client = useQueryClient()
  const wide = useMediaQuery('(min-width: 1024px)')
  const rescan = useRescan()
  const prepare = useCreateProposal()
  const upload = scan.kind === 'upload'
  const repository = scan.repository
  const all = useMemo(() => groups(report), [report])
  const proposed = useMemo(() => defaultSelection(report), [report])
  const sums = recap(report, selection)
  const target = params.get('paquet')
  const targetRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!target) return
    targetRef.current?.scrollIntoView({ block: 'center' })
    targetRef.current?.focus({ preventScroll: true })
  }, [target])

  const plan = useMutation({
    mutationFn: () => api.planUpdate({ scan: scan.id, selection }),
    onSuccess: (document) => {
      client.setQueryData(queryKeys.plan(document.id), document)
      // Le retour du navigateur retrouvera cette sélection (`?plan=`).
      void navigate(`/analyses/${scan.id}/mise-a-jour?plan=${document.id}`, { replace: true })
      void navigate(`/plans/${document.id}`)
    },
  })

  /** Un dépôt : le récapitulatif de sa PR, avec les autres dépôts du récapitulatif d'où l'on vient. */
  function propose() {
    if (!repository) return
    const others: ProposedSelection[] = (proposal?.repositories ?? [])
      .filter((item) => item.full_name.toLowerCase() !== repository.full_name.toLowerCase())
      .map((item) => ({ repository: item.full_name, selection: item.state === 'ready' ? item.selection : null }))
    prepare.mutate(
      { forge: repository.forge, repositories: [...others, { repository: repository.full_name, selection }] },
      { onSuccess: (document) => void navigate(`/pr/${document.id}`) },
    )
  }

  if (plan.isPending || prepare.isPending) {
    return (
      <Container>
        <UpdateHeader scan={scan} step={1} />
        {repository ? (
          <PreparingPlan
            label="Préparation du récapitulatif"
            text={fr('Préparation du récapitulatif : réécriture à blanc, recherche de la PR déjà ouverte…')}
          />
        ) : (
          <PreparingPlan />
        )}
      </Container>
    )
  }

  if (all.length === 0) {
    return (
      <Container>
        <UpdateHeader scan={scan} step={0} />
        <EmptyState
          icon={CircleCheck}
          level="h2"
          title="Rien à mettre à jour"
          actions={
            <Link to={`/analyses/${scan.id}`} className={buttonVariants({ variant: 'secondary' })}>
              Retour au rapport
            </Link>
          }
        >
          <p>{fr('Ce rapport ne propose aucune mise à jour : pas de faille connue, pas de version plus récente.')}</p>
        </EmptyState>
      </Container>
    )
  }

  const verify = repository ? (
    <Button variant="primary" className={cn(wide && 'w-full')} disabled={sums.chosen === 0} onClick={propose}>
      <GitPullRequest aria-hidden="true" />
      Préparer la PR
      <ArrowRight aria-hidden="true" />
    </Button>
  ) : (
    <Button variant="primary" className={cn(wide && 'w-full')} disabled={sums.chosen === 0} onClick={() => plan.mutate()}>
      Vérifier le plan
      <ArrowRight aria-hidden="true" />
    </Button>
  )
  const failed = repository ? prepare.error : plan.error

  return (
    <Container>
      <UpdateHeader scan={scan} step={0} />
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-6">
          <Inconclusive
            report={report}
            onRescan={upload ? null : () => rescan.mutate({ scan })}
            pending={rescan.isPending}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-fg-muted">
              Correctifs, mineures et corrections de failles sont pré-cochés. Les majeures sont proposées, jamais cochées
              d'office.
            </p>
            <div className="flex flex-wrap gap-1">
              <Button variant="ghost" size="sm" onClick={() => setSelection(proposed)}>
                <RotateCcw aria-hidden="true" />
                Sélection proposée
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setSelection({})}>
                Tout décocher
              </Button>
            </div>
          </div>
          {all.map((group) => (
            <GroupSection key={group.key} group={group} several={report.projects.length > 1}>
              {group.updates.map((update) => (
                <UpdateCard
                  key={update.id}
                  project={group.project}
                  update={update}
                  chosen={selection[update.id]}
                  onToggle={(on) => setSelection((current) => toggle(current, update, on))}
                  onChoose={(version) => setSelection((current) => choose(current, update, version))}
                  cardRef={update.id === target ? targetRef : undefined}
                />
              ))}
            </GroupSection>
          ))}
          {rescan.error && (
            <p role="alert" className="text-sm text-danger">
              {rescan.error.message}
            </p>
          )}
        </div>

        <aside aria-labelledby="recap-titre" className="lg:sticky lg:top-[calc(var(--header-h)+16px)]">
          <Card className="flex flex-col gap-4">
            <h2 id="recap-titre" className="text-lg">
              Récapitulatif
            </h2>
            <RecapList sums={sums} upload={upload} />
            {sums.majors > 0 && (
              <Alert variant="warning">
                <TriangleAlert aria-hidden="true" />
                <AlertTitle>{sums.majors === 1 ? 'Une majeure est cochée' : `${sums.majors} majeures sont cochées`}</AlertTitle>
                <AlertDescription>
                  <p>{fr('Relire leurs notes de version : le code devra peut-être changer.')}</p>
                </AlertDescription>
              </Alert>
            )}
            {failed && (
              <Alert variant="danger" role="alert">
                <CircleX aria-hidden="true" />
                <AlertTitle>
                  {repository ? "Le récapitulatif n'a pas pu être préparé" : "Le plan n'a pas pu être préparé"}
                </AlertTitle>
                <AlertDescription>
                  <p>{failed.message}</p>
                  <p className="text-fg-muted">
                    {fr(
                      `Revoir la sélection ; si le ${repository ? 'dépôt' : 'dossier'} a changé depuis l'analyse, la relancer.`,
                    )}
                  </p>
                </AlertDescription>
              </Alert>
            )}
            {wide && verify}
            <p className="text-sm text-fg-muted">
              {upload
                ? fr("Rien ne s'écrit sur le disque : le fichier mis à jour se télécharge à l'étape suivante.")
                : repository
                  ? fr("Rien n'est poussé à cette étape : le récapitulatif montre d'abord le diff et la PR déjà ouverte.")
                  : fr("Rien n'est écrit à cette étape : le plan montre d'abord le diff.")}
            </p>
          </Card>
        </aside>

        {!wide && (
          <div
            role="region"
            aria-label="Sélection"
            className="sticky bottom-4 z-20 flex flex-wrap items-center gap-3 rounded-md border border-control bg-surface px-4 py-3 shadow-raised max-sm:-mx-4 max-sm:bottom-0 max-sm:rounded-none max-sm:[&>button]:flex-auto"
          >
            <span className="grow text-sm">
              <b>{count(sums.chosen, 'cochée', 'cochées')}</b>
              {sums.vulnerabilities > 0 && ` · ${count(sums.fixed, 'faille corrigée', 'failles corrigées')}`}
            </span>
            {verify}
          </div>
        )}
      </div>
    </Container>
  )
}

/** Un groupe de cartes : un lockfile (régénéré une fois pour toutes ses mises à jour). */
function GroupSection({ group, several, children }: { group: Group; several: boolean; children: React.ReactNode }) {
  const id = `groupe-${group.key.replace(/[^a-zA-Z0-9_-]/g, '_')}`
  const ecosystems = [...new Set(group.updates.map((update) => update.ecosystem))]
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="flex flex-wrap items-center gap-2 text-base">
        {ecosystems.map((ecosystem) => (
          <Badge key={ecosystem}>{ecosystem}</Badge>
        ))}
        {/* Le chemin d'un lockfile part de la source : il dit déjà le projet. */}
        {group.lockfile ? (
          <span className="font-mono text-sm">{group.lockfile}</span>
        ) : (
          <span className="text-sm font-normal text-fg-muted">
            sans lockfile
            {several && (
              <>
                {' · projet '}
                <span className="font-mono">{group.project.path === '.' ? 'racine' : group.project.path}</span>
              </>
            )}
          </span>
        )}
      </h2>
      {children}
    </section>
  )
}

/** Le récapitulatif, compté sur la sélection affichée (annoncé quand il change). */
function RecapList({ sums, upload }: { sums: Recap; upload: boolean }) {
  const line = 'flex justify-between gap-3'
  return (
    <ul className="flex flex-col gap-2 text-sm" aria-live="polite">
      <li className={line}>
        <span>Mises à jour cochées</span>
        <b className="tabular-nums">
          {sums.chosen} sur {sums.total}
        </b>
      </li>
      {sums.vulnerabilities > 0 && (
        <>
          <li className={line}>
            <span>Failles corrigées</span>
            <b className="tabular-nums">
              {sums.fixed} sur {sums.vulnerabilities}
            </b>
          </li>
          <li className={line}>
            <span>Failles laissées</span>
            <b className="tabular-nums">{sums.vulnerabilities - sums.fixed}</b>
          </li>
        </>
      )}
      {sums.introduced > 0 && (
        <li className={cn(line, 'text-danger')}>
          <span>Failles apportées</span>
          <b className="tabular-nums">{sums.introduced}</b>
        </li>
      )}
      <li className={line}>
        <span>Majeures cochées</span>
        <b className="tabular-nums">{sums.majors}</b>
      </li>
      <li className={line}>
        <span>Fichiers réécrits</span>
        <b className="tabular-nums">{sums.files.length}</b>
      </li>
      {sums.files.length > 0 && <li className="font-mono text-fg-muted [overflow-wrap:anywhere]">{sums.files.join(', ')}</li>}
      {upload ? (
        <li className="text-fg-muted">{fr('Aucun lockfile régénéré : fichier envoyé.')}</li>
      ) : (
        <>
          <li className={line}>
            <span>Lockfiles régénérés</span>
            <b className="tabular-nums">{sums.lockfiles.length}</b>
          </li>
          {sums.lockfiles.length > 0 && (
            <li className="font-mono text-fg-muted [overflow-wrap:anywhere]">{sums.lockfiles.join(', ')}</li>
          )}
        </>
      )}
    </ul>
  )
}

/**
 * Non concluant (ECRANS.md, écran 5) : des paquets sans mise à jour faute de données, des
 * versions proposées qu'OSV n'a pas vérifiées, des fichiers non lus (`notices`).
 */
function Inconclusive({ report, onRescan, pending }: { report: Report; onRescan: (() => void) | null; pending: boolean }) {
  const findings = report.projects.flatMap((project) => project.findings.filter((finding) => finding.kind === 'inconclusive'))
  const notices = report.projects.flatMap((project) => project.notices)
  if (findings.length === 0 && notices.length === 0) return null
  return (
    <Alert variant="inconclusive" role="status">
      <CircleHelp aria-hidden="true" />
      <AlertTitle>Analyse en partie non concluante</AlertTitle>
      <AlertDescription>
        <ul className="flex flex-col gap-1">
          {findings.slice(0, 5).map((finding, index) => (
            <li key={`f${index}`}>
              {finding.dependency && <span className="font-mono font-semibold">{finding.dependency.name}</span>}
              {finding.dependency && `${NBSP}: `}
              {finding.message}
            </li>
          ))}
          {findings.length > 5 && <li>et {findings.length - 5} autres paquets.</li>}
          {notices.map((notice, index) => (
            <li key={`n${index}`}>
              <span className="font-mono">{notice.file}</span>
              {`${NBSP}: `}
              {notice.message}
            </li>
          ))}
        </ul>
        <p>{fr("Ces paquets n'ont pas de mise à jour proposée, ou une version proposée pourrait avoir une faille connue.")}</p>
      </AlertDescription>
      {onRescan && (
        <AlertActions>
          <Button size="sm" onClick={onRescan} disabled={pending}>
            <RefreshCw aria-hidden="true" />
            Relancer l'analyse d'abord
          </Button>
        </AlertActions>
      )}
    </Alert>
  )
}

