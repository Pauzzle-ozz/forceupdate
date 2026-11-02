import {
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CircleMinus,
  CircleX,
  FolderGit2,
  Info,
  GitPullRequest,
  LoaderCircle,
  Lock,
  RefreshCw,
  Send,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { cn } from 'cn'
import { ApiError, queryKeys } from '@/api/client'
import type { ForgeKind, LockJob, LockResult, Proposal, ProposedRepository } from '@/api/types'
import { Blade } from '@/components/Blade'
import { Command } from '@/components/Command'
import { Diff } from '@/components/Diff'
import { EmptyState } from '@/components/EmptyState'
import { ExternalLink } from '@/components/ExternalLink'
import { ForgeLogo } from '@/components/ForgeLogo'
import { GapBadge } from '@/components/badges'
import { Alert, AlertActions, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/choice'
import { Skeleton } from '@/components/ui/skeleton'
import { useCreateProposal, useProposal, useSendProposal } from '@/hooks/useProposals'
import { useOnline } from '@/hooks/useStatus'
import { NBSP, count, formatDate, fr } from '@/lib/format'
import {
  defaultChecked,
  finished,
  forgeLabel,
  keyOf,
  keyText,
  outcomeText,
  ready,
  requestCount,
  requestNumber,
  requestWord,
  requestWords,
  requestedRepositories,
  resultSummary,
  sent,
} from '@/lib/proposals'
import { lastLines } from '@/lib/update'
import { Breadcrumb, Container, Section, useDocumentTitle } from '@/shell/Page'
import { errorText } from '@/screens/accounts/ForgeCard'
import { PreparingPlan, REQUEST_STEPS, Stepper } from '@/screens/update/Layout'

/**
 * `/pr?depots=github:github.com/owner/a,gitlab:gitlab.com/groupe/b` (écran 7, « Préparer N PR et
 * M MR ») : prépare le récapitulatif de ces dépôts, de plusieurs forges au besoin, puis passe à son
 * adresse, `/pr/{id}`.
 */
export function NewProposalPage() {
  useDocumentTitle('PR')
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const create = useCreateProposal()
  const wanted = requestedRepositories(params)
  const started = useRef(false)

  useEffect(() => {
    // Une seule fois, même si React rejoue l'effet (mode strict).
    if (!wanted || started.current) return
    started.current = true
    create.mutate(
      { repositories: wanted.map((key) => ({ ...key, selection: null })) },
      { onSuccess: (proposal) => void navigate(`/pr/${proposal.id}`, { replace: true }) },
    )
  }, [wanted, create, navigate])

  if (!wanted) {
    return (
      <Container narrow>
        <ProposalHead words="PR" step={1} />
        <EmptyState
          icon={GitPullRequest}
          level="h2"
          title="Aucun dépôt sélectionné"
          actions={
            <Link to="/depots" className={buttonVariants({ variant: 'primary' })}>
              <FolderGit2 aria-hidden="true" />
              Mes dépôts
            </Link>
          }
        >
          <p>{fr('Sélectionner les dépôts à mettre à jour dans « Mes dépôts », puis « Préparer les PR » (les MR sur GitLab).')}</p>
        </EmptyState>
      </Container>
    )
  }
  if (create.isError) {
    return (
      <Container narrow>
        <ProposalHead words={requestWords(wanted.map((key) => key.forge))} step={1} />
        <Alert variant="danger" role="alert">
          <CircleX aria-hidden="true" />
          <AlertTitle>Le récapitulatif n'a pas pu être préparé</AlertTitle>
          <AlertDescription>
            <p>{errorText(create.error)}</p>
          </AlertDescription>
          <AlertActions>
            <Button
              size="sm"
              onClick={() =>
                create.mutate(
                  { repositories: wanted.map((key) => ({ ...key, selection: null })) },
                  { onSuccess: (proposal) => void navigate(`/pr/${proposal.id}`, { replace: true }) },
                )
              }
            >
              <RefreshCw aria-hidden="true" />
              Réessayer
            </Button>
            <Link to="/depots" className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
              Retour à mes dépôts
            </Link>
          </AlertActions>
        </Alert>
      </Container>
    )
  }
  return (
    <Container narrow>
      <ProposalHead words={requestWords(wanted.map((key) => key.forge))} step={1} />
      <PreparingPlan
        label="Préparation du récapitulatif"
        text={fr(
          `Préparation du récapitulatif de ${count(wanted.length, 'dépôt')} : réécriture à blanc sur les fichiers de l'analyse, recherche des ${requestWords(wanted.map((key) => key.forge))} déjà ouvertes…`,
        )}
      />
    </Container>
  )
}

/**
 * `/pr/{id}` : l'écran 8 (ECRANS.md). Le récapitulatif (rien n'est poussé), puis l'envoi suivi
 * dépôt par dépôt (relu chaque seconde), puis le résultat avec les liens des PR.
 */
export function ProposalPage() {
  const { id = '' } = useParams()
  const proposal = useProposal(id)
  const client = useQueryClient()
  const status = proposal.data?.status

  useEffect(() => {
    // Fini : la liste des dépôts montre les PR ouvertes.
    if (status === 'done') void client.invalidateQueries({ queryKey: queryKeys.repositories })
  }, [status, client])

  if (proposal.isPending) return <ProposalSkeleton />
  if (proposal.isError) {
    const gone = proposal.error instanceof ApiError && proposal.error.status === 404
    return (
      <Container narrow>
        <ProposalHead words="PR" step={1} />
        <EmptyState
          icon={gone ? GitPullRequest : CircleX}
          level="h2"
          title={gone ? 'Récapitulatif introuvable' : "Le récapitulatif n'a pas pu être lu"}
          actions={
            gone ? (
              <Link to="/depots" className={buttonVariants({ variant: 'primary' })}>
                Mes dépôts
              </Link>
            ) : (
              <Button onClick={() => void proposal.refetch()}>
                <RefreshCw aria-hidden="true" />
                Réessayer
              </Button>
            )
          }
        >
          <p>
            {gone
              ? fr("Les récapitulatifs ne vivent que le temps de la session : le serveur a peut-être redémarré. Le préparer de nouveau depuis « Mes dépôts ».")
              : errorText(proposal.error)}
          </p>
        </EmptyState>
      </Container>
    )
  }
  const data = proposal.data
  if (data.status === 'planned') return <Recap proposal={data} />
  return <Sending proposal={data} />
}

/** L'en-tête de l'écran 8 ; `words` : « PR », « MR » ou « PR et MR », selon les forges. */
function ProposalHead({ words, step, title }: { words: string; step: number; title?: string }) {
  const heading = title ?? `Préparer les ${words}`
  useDocumentTitle(heading)
  return (
    <>
      <Breadcrumb items={[{ label: 'Mes dépôts', to: '/depots' }, { label: words }]} />
      <div className="mb-6 flex flex-col gap-2">
        <h1 className="text-2xl" tabIndex={-1} id="pr-titre">
          {heading}
        </h1>
        <Stepper current={step} steps={REQUEST_STEPS} />
      </div>
    </>
  )
}

function ProposalSkeleton() {
  useDocumentTitle('PR')
  return (
    <Container narrow>
      <div className="mb-6 flex flex-col gap-2">
        <Skeleton className="h-3.5 w-40" />
        <Skeleton className="h-7 w-64 max-w-full" />
        <Skeleton className="h-6 w-80 max-w-full" />
      </div>
      <div className="flex flex-col gap-3" aria-busy="true" aria-label="Chargement du récapitulatif">
        {[0, 1].map((index) => (
          <Card key={index} className="flex flex-col gap-3">
            <Skeleton className="w-2/5" />
            <Skeleton />
            <Skeleton className="w-3/5" />
          </Card>
        ))}
      </div>
    </Container>
  )
}

// -- Le récapitulatif ----------------------------------------------------------------------

function Recap({ proposal }: { proposal: Proposal }) {
  const online = useOnline()
  const send = useSendProposal(proposal.id)
  const [checked, setChecked] = useState<ReadonlySet<string>>(() => defaultChecked(proposal))
  const prepared = ready(proposal)
  const words = requestWords(proposal.repositories.map((item) => item.forge))
  const skipped = proposal.repositories.filter((item) => item.state === 'skipped')
  const chosen = prepared.filter((item) => checked.has(keyText(item)))
  const several = new Set(proposal.repositories.map((item) => `${item.forge}:${item.host}`)).size > 1
  const updates = chosen.filter((item) => item.request !== null).length
  const blocked = !online ? fr("Hors ligne : l'envoi attendra le réseau.") : chosen.length === 0 ? `Aucun dépôt coché.` : null

  function check(name: string, on: boolean) {
    setChecked((current) => {
      const next = new Set(current)
      if (on) next.add(name)
      else next.delete(name)
      return next
    })
  }

  return (
    <Container narrow>
      <ProposalHead words={words} step={1} />
      <p className="mb-6 text-fg-muted" aria-live="polite">
        {fr(
          `${count(proposal.repositories.length, 'dépôt')}, ${requestCount(chosen.map((item) => item.forge))} à envoyer${
            updates > 0 ? ` (dont ${updates} ${updates >= 2 ? 'déjà ouvertes, mises à jour' : 'déjà ouverte, mise à jour'})` : ''
          }. Rien n'est poussé avant « Envoyer ».`,
        )}
      </p>

      {prepared.length === 0 ? (
        <EmptyState
          icon={CircleCheck}
          level="h2"
          title={`Aucune ${words} à préparer`}
          actions={
            <Link to="/depots" className={buttonVariants({ variant: 'primary' })}>
              Retour à mes dépôts
            </Link>
          }
        >
          <p>{fr('Aucun des dépôts demandés ne peut recevoir de mise à jour : voir pourquoi ci-dessous.')}</p>
        </EmptyState>
      ) : (
        <Section aria-labelledby="prets-titre">
          <h2 id="prets-titre" className="text-xl">
            {count(prepared.length, 'dépôt prêt', 'dépôts prêts')}
          </h2>
          <ul className="flex flex-col gap-4">
            {prepared.map((item) => (
              <li key={keyText(item)}>
                <RecapCard
                  item={item}
                  proposalId={proposal.id}
                  checked={checked.has(keyText(item))}
                  onCheck={(on) => check(keyText(item), on)}
                  showForge={several}
                />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {skipped.length > 0 && <SkippedList items={skipped} />}

      {send.error && (
        <Alert variant="danger" role="alert" className="mt-6">
          <CircleX aria-hidden="true" />
          <AlertTitle>Envoi refusé</AlertTitle>
          <AlertDescription>
            <p>{errorText(send.error)}</p>
          </AlertDescription>
        </Alert>
      )}

      {prepared.length > 0 && (
        <div
          role="region"
          aria-label="Envoi"
          className="sticky bottom-4 z-20 mt-6 flex flex-wrap items-center gap-3 rounded-md border border-control bg-surface px-4 py-3 shadow-raised max-sm:-mx-4 max-sm:bottom-0 max-sm:rounded-none max-sm:[&>button]:flex-auto"
        >
          <span className="grow text-sm">
            <b>{fr(`${chosen.length} sur ${count(prepared.length, 'dépôt prêt', 'dépôts prêts')}`)}</b>
            <span className="block text-fg-muted">
              {blocked ?? fr(`Branche ${prepared[0].branch}, jamais la branche par défaut.`)}
            </span>
          </span>
          <Button
            variant="primary"
            disabled={blocked !== null || send.isPending}
            onClick={() => send.mutate(chosen.map(keyOf))}
          >
            {send.isPending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Send aria-hidden="true" />}
            {chosen.length >= 2
              ? `Envoyer ${requestCount(chosen.map((item) => item.forge))}`
              : `Envoyer la ${requestWords(chosen.map((item) => item.forge))}`}
          </Button>
        </div>
      )}
    </Container>
  )
}

/** Un dépôt prêt : ce que sa PR fera, la PR existante, les diffs, les lockfiles. */
function RecapCard({
  item,
  proposalId,
  checked,
  onCheck,
  showForge,
}: {
  item: ProposedRepository
  proposalId: string
  checked: boolean
  onCheck: (on: boolean) => void
  /** Le récapitulatif mêle plusieurs comptes : dire la forge de chaque dépôt. */
  showForge: boolean
}) {
  const id = useId()
  const word = requestWord(item.forge)
  const fixes = new Set(item.applied.flatMap((update) => update.fixes)).size
  return (
    <Card className={cn('flex flex-col gap-4', checked && 'border-control bg-primary-soft')} aria-labelledby={`${id}-nom`}>
      <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2">
        <Checkbox
          checked={checked}
          onChange={(event) => onCheck(event.target.checked)}
          aria-label={`Envoyer la ${word} de ${item.full_name}`}
        />
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={`${id}-nom`} className="font-mono text-base break-all">
              {item.full_name}
            </h3>
            {showForge && <ForgeTag forge={item.forge} host={item.host} />}
            {item.request ? (
              <Badge variant="info">
                <GitPullRequest aria-hidden="true" />
                {fr(`met à jour la ${word} ${requestNumber(item.forge, item.request)}`)}
              </Badge>
            ) : (
              <Badge variant="outline">
                <GitPullRequest aria-hidden="true" />
                nouvelle {word}
              </Badge>
            )}
            {item.closed && (
              <Badge variant="warning">
                <TriangleAlert aria-hidden="true" />
                {fr(`${word} ${requestNumber(item.forge, item.closed)} fermée sans fusion`)}
              </Badge>
            )}
            {item.inconclusive && (
              <Badge variant="inconclusive">
                <CircleHelp aria-hidden="true" />
                analyse non concluante
              </Badge>
            )}
          </div>
          <p className="text-sm text-fg-muted">
            <span className="font-mono">{item.branch}</span> → <span className="font-mono">{item.default_branch}</span>
            {fr(' : la branche visée n\'est jamais poussée directement')}
            {item.commit && (
              <>
                {' · analyse du commit '}
                <code title={item.commit}>{item.commit.slice(0, 7)}</code>
              </>
            )}
          </p>
          {item.closed && (
            <div className="flex flex-col gap-1 text-sm">
              <p>
                {fr(
                  `La ${word} ${requestNumber(item.forge, item.closed)} a été fermée sans fusion${
                    item.closed.closed_at ? ` le ${formatDate(item.closed.closed_at)}` : ''
                  } : l'envoyer en ouvre une nouvelle. Pas cochée par défaut.`,
                )}
              </p>
              <p>
                <ExternalLink href={item.closed.url}>
                  {`Voir la ${word} ${requestNumber(item.forge, item.closed)} sur ${forgeLabel(item.forge, item.host)}`}
                </ExternalLink>
              </p>
            </div>
          )}
          {item.inconclusive && (
            <p className="text-sm">
              {fr(`Des paquets n'ont pas pu être vérifiés : la ${word} peut manquer des mises à jour. Pas cochée par défaut.`)}
            </p>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h4 className="text-sm font-semibold">
          {count(item.applied.length, 'mise à jour', 'mises à jour')}
          {fixes > 0 && <span className="font-normal text-fg-muted">{` · ${count(fixes, 'faille corrigée', 'failles corrigées')}`}</span>}
        </h4>
        <ul className="flex flex-col gap-1.5 text-sm">
          {item.applied.map((update) => (
            <li key={update.update} className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-mono font-semibold">{update.name}</span>
              <span className="font-mono text-fg-muted">
                {update.current ?? '?'} → {update.version}
              </span>
              {update.gap && <GapBadge gap={update.gap} />}
              {!update.direct && <Badge variant="outline">indirecte</Badge>}
              {update.fixes.length > 0 && <span className="text-fg-muted">{count(update.fixes.length, 'faille corrigée', 'failles corrigées')}</span>}
            </li>
          ))}
        </ul>
        {item.skipped.length > 0 && (
          <ul className="flex flex-col gap-1 text-sm">
            {item.skipped.map((skip) => (
              <li key={skip.update} className="flex items-start gap-2 text-warning">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <span>
                  <span className="font-mono">
                    {skip.name} {skip.version}
                  </span>
                  {`${NBSP}: pas appliquée, ${skip.reason}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {item.files.length > 0 && (
        <details className="group rounded-md border border-border">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium">
            {count(item.files.length, 'fichier réécrit', 'fichiers réécrits')}
            {' : '}
            <span className="font-mono text-fg-muted [overflow-wrap:anywhere]">{item.files.map((file) => file.path).join(', ')}</span>
          </summary>
          <div className="flex flex-col gap-3 p-3 pt-0">
            {item.files.map((file) => (
              <Diff key={file.path} path={file.path} diff={file.diff} />
            ))}
          </div>
        </details>
      )}

      {item.lockfiles.length > 0 && (
        <ul className="flex flex-col gap-2" aria-label={`Lockfiles de ${item.full_name}`}>
          {item.lockfiles.map((job) => (
            <LockLine key={job.lockfile} job={job} word={word} />
          ))}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        {item.scan && (
          <>
            <Link
              to={`/analyses/${item.scan}/mise-a-jour?pr=${proposalId}`}
              className={buttonVariants({ variant: 'secondary', size: 'sm' })}
              aria-label={`Modifier la sélection de ${item.full_name}`}
            >
              Modifier la sélection
            </Link>
            <Link
              to={`/analyses/${item.scan}`}
              className={buttonVariants({ variant: 'ghost', size: 'sm' })}
              aria-label={`Voir le rapport de ${item.full_name}`}
            >
              Voir le rapport
            </Link>
          </>
        )}
      </div>
    </Card>
  )
}

/** Un lockfile : régénéré sur le clone si l'outil est là ; sinon, la commande dans la description. */
function LockLine({ job, word }: { job: LockJob; word: string }) {
  return (
    <li className="flex flex-col gap-2 rounded-md border border-border bg-surface px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Lock className="size-4 shrink-0" aria-hidden="true" />
        <span className="font-mono break-all">{job.lockfile}</span>
        {job.available ? (
          <Badge variant="success">
            <CircleCheck aria-hidden="true" />
            {fr(`régénéré par ${job.tool}`)}
          </Badge>
        ) : (
          <Badge variant="warning">
            <TriangleAlert aria-hidden="true" />
            {job.program} absent
          </Badge>
        )}
      </div>
      {job.extra && job.accepted && (
        // Fait d'office pour une PR : c'est la CI du dépôt qui reçoit le lockfile (E32).
        <p className="flex items-start gap-2 text-sm">
          <Info className="mt-0.5 size-4 shrink-0 text-link" aria-hidden="true" />
          <span>
            <b className="font-medium">{job.extra.label}</b>
            {NBSP}: {fr(job.extra.detail)}
          </span>
        </p>
      )}
      {!job.available && (
        <>
          <p className="text-sm">
            {fr(
              `${job.program} n'est pas installé sur cet ordinateur : les manifestes seront réécrits, et la description de la ${word} donnera la commande à lancer :`,
            )}
          </p>
          <Command command={job.command} label={`la commande de ${job.lockfile}`} />
        </>
      )}
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
    </li>
  )
}

/** Les dépôts sans PR, et pourquoi. */
function SkippedList({ items, title = 'Sautés' }: { items: ProposedRepository[]; title?: string }) {
  const id = useId()
  return (
    <Section aria-labelledby={id}>
      <h2 id={id} className="text-xl">
        {title}
      </h2>
      <ul className="flex flex-col divide-y divide-border rounded-md border border-border bg-surface">
        {items.map((item) => (
          <li key={keyText(item)} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
            <CircleMinus className="size-4 shrink-0 text-fg-muted" aria-hidden="true" />
            <span className="font-mono font-semibold break-all">{item.full_name}</span>
            <ForgeTag forge={item.forge} host={item.host} />
            <span className="text-fg-muted">{item.reason}</span>
            {item.reason === 'pas encore analysé' && item.scan === null && (
              <Link to="/depots" className="text-link underline">
                l'analyser
              </Link>
            )}
          </li>
        ))}
      </ul>
    </Section>
  )
}

// -- L'envoi et le résultat ------------------------------------------------------------------

const STATE_ICON: Record<string, { icon: LucideIcon; className: string; spin?: boolean }> = {
  waiting: { icon: CircleDashed, className: 'text-fg-muted' },
  sending: { icon: LoaderCircle, className: 'text-link', spin: true },
  opened: { icon: CircleCheck, className: 'text-success' },
  updated: { icon: CircleCheck, className: 'text-success' },
  nothing: { icon: CircleMinus, className: 'text-fg-muted' },
  failed: { icon: CircleX, className: 'text-danger' },
}

function Sending({ proposal }: { proposal: Proposal }) {
  const running = proposal.status === 'running'
  const items = sent(proposal)
  const word = requestWords(items.map((item) => item.forge))
  const several = new Set(proposal.repositories.map((item) => `${item.forge}:${item.host}`)).size > 1
  const refused = items.filter((item) => item.state === 'failed' && item.error?.includes('token'))
  const done = items.filter(finished)
  const others = proposal.repositories.filter((item) => item.state === 'skipped')
  const announced = done.map((item) => `${item.full_name} : ${outcomeText(item)}.`).join(' ')

  useEffect(() => {
    // L'envoi qui commence, puis le résultat : le focus va au titre.
    document.getElementById('pr-titre')?.focus()
  }, [running])

  return (
    <Container narrow>
      <ProposalHead words={word} step={running ? 2 : 3} title={running ? `Envoi des ${word}` : `${word} envoyées`} />

      <Card className="mb-6 flex flex-col gap-3" role="region" aria-labelledby="envoi-titre">
        <h2 id="envoi-titre" className="flex items-center gap-2 text-base">
          {running ? (
            <LoaderCircle className="size-4 animate-spin text-link" aria-hidden="true" />
          ) : (
            <CircleCheck className="size-4 text-success" aria-hidden="true" />
          )}
          {running
            ? fr(`Envoi de ${count(items.length, 'dépôt')} : ${done.length} ${done.length >= 2 ? 'terminés' : 'terminé'}`)
            : fr(`Envoi terminé : ${resultSummary(proposal) || 'rien envoyé'}`)}
        </h2>
        {running && <Blade label="Dépôts envoyés" value={done.length} max={items.length} valueText={`${done.length} sur ${items.length}`} />}
        <p className="text-sm text-fg-muted">
          {running
            ? fr(
                `Un dépôt à la fois : clone, mise à jour, push de la branche, ${word}. Un envoi ne s'annule pas. Les outils de lockfile peuvent prendre plusieurs minutes.`,
              )
            : fr(`Relancer met à jour les mêmes ${word}, sans en ouvrir d'autres.`)}
        </p>
        <p className="sr-only" aria-live="polite">
          {announced}
        </p>
      </Card>

      {proposal.error && (
        <Alert variant="danger" role="alert" className="mb-6">
          <CircleX aria-hidden="true" />
          <AlertTitle>L'envoi n'a pas pu se faire</AlertTitle>
          <AlertDescription>
            <p>{proposal.error}</p>
          </AlertDescription>
        </Alert>
      )}

      {!running && refused.length > 0 && (
        <Alert variant="danger" role="alert" className="mb-6">
          <CircleX aria-hidden="true" />
          <AlertTitle>{fr('Un compte refuse son token')}</AlertTitle>
          <AlertDescription>
            <p>
              {fr(
                `${[...new Set(refused.map((item) => forgeLabel(item.forge, item.host)))].join(', ')} : se reconnecter, puis relancer.`,
              )}
            </p>
          </AlertDescription>
          <AlertActions>
            <Link to="/comptes" className={buttonVariants({ variant: 'primary', size: 'sm' })}>
              Comptes
            </Link>
          </AlertActions>
        </Alert>
      )}

      <Section aria-labelledby="envoyes-titre">
        <h2 id="envoyes-titre" className="text-xl">
          {count(items.length, 'dépôt envoyé', 'dépôts envoyés')}
        </h2>
        <ul className="flex flex-col gap-4">
          {items.map((item) => (
            <li key={keyText(item)}>
              <SentCard item={item} showForge={several} />
            </li>
          ))}
        </ul>
      </Section>

      {others.length > 0 && <SkippedList items={others} title="Pas envoyés" />}

      {!running && (
        <div className="mt-6 flex flex-wrap gap-2">
          <Link to="/depots" className={buttonVariants({ variant: 'primary' })}>
            <FolderGit2 aria-hidden="true" />
            Retour à mes dépôts
          </Link>
        </div>
      )}
    </Container>
  )
}

/** Un dépôt envoyé : où il en est, puis sa PR, ou l'erreur, et ce qui reste à faire. */
function SentCard({ item, showForge }: { item: ProposedRepository; showForge: boolean }) {
  const id = useId()
  const look = STATE_ICON[item.state] ?? STATE_ICON.waiting
  const Icon = look.icon
  const word = requestWord(item.forge)
  // À reprendre : ce qui n'est pas régénéré, et un lockfile que le npm du projet refuse (E32).
  const pending = item.results.filter((result) => result.status !== 'regenerated' || result.verified?.error)
  return (
    <Card className="flex flex-col gap-3" aria-labelledby={`${id}-nom`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Icon className={cn('size-5 shrink-0', look.className, look.spin && 'animate-spin')} aria-hidden="true" />
        <h3 id={`${id}-nom`} className="font-mono text-base break-all">
          {item.full_name}
        </h3>
        {showForge && <ForgeTag forge={item.forge} host={item.host} />}
        <span className={cn('text-sm', item.state === 'failed' ? 'text-danger' : 'text-fg-muted')}>{outcomeText(item)}</span>
      </div>
      {item.state === 'sending' && <Blade label={`Envoi de ${item.full_name}`} />}
      {item.request && (item.state === 'opened' || item.state === 'updated') && (
        <p className="text-sm">
          <ExternalLink href={item.request.url}>
            {`Voir la ${word} ${requestNumber(item.forge, item.request)} sur ${forgeLabel(item.forge, item.host)}`}
          </ExternalLink>
        </p>
      )}
      {item.state === 'failed' && item.error && (
        <Alert variant="danger">
          <CircleX aria-hidden="true" />
          <AlertTitle>{`Pas de ${word} pour ce dépôt`}</AlertTitle>
          <AlertDescription>
            <p>{item.error}</p>
          </AlertDescription>
        </Alert>
      )}
      {finished(item) && item.committed.length > 0 && (
        <p className="text-sm text-fg-muted">
          {fr(`Dans le commit : `)}
          <span className="font-mono [overflow-wrap:anywhere]">{item.committed.join(', ')}</span>
        </p>
      )}
      {finished(item) && pending.length > 0 && (
        <ul className="flex flex-col gap-2" aria-label={`Lockfiles de ${item.full_name} à reprendre`}>
          {pending.map((result) => (
            <ResultLine key={result.lockfile} result={result} job={item.lockfiles.find((job) => job.lockfile === result.lockfile)} word={word} />
          ))}
        </ul>
      )}
      {finished(item) && item.skipped.length > 0 && (
        <ul className="flex flex-col gap-1 text-sm">
          {item.skipped.map((skip) => (
            <li key={skip.update} className="flex items-start gap-2 text-warning">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              <span>
                <span className="font-mono">
                  {skip.name} {skip.version}
                </span>
                {`${NBSP}: pas appliquée, ${skip.reason}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/** Un lockfile qui n'a pas été régénéré sur le clone : la commande à lancer, ou l'erreur. */
function ResultLine({ result, job, word }: { result: LockResult; job: LockJob | undefined; word: string }) {
  if (result.status === 'regenerated' && result.verified?.error) {
    return (
      <li className="flex flex-col gap-2 rounded-md border border-border px-3 py-2 text-sm">
        <span className="flex flex-wrap items-center gap-2">
          <CircleX className="size-4 shrink-0 text-danger" aria-hidden="true" />
          <span className="font-mono">{result.lockfile}</span>
          {fr(`régénéré, mais refusé par la relecture (la description de la ${word} le dit) :`)}
        </span>
        <span lang="en" className="font-mono text-xs [overflow-wrap:anywhere]">
          {result.verified.error}
        </span>
        <Command command={result.verified.command} label={`la relecture de ${result.lockfile}`} />
      </li>
    )
  }
  if (result.status === 'tool_missing') {
    return (
      <li className="flex flex-col gap-2 rounded-md border border-border px-3 py-2 text-sm">
        <span className="flex flex-wrap items-center gap-2">
          <TriangleAlert className="size-4 shrink-0 text-warning" aria-hidden="true" />
          <span className="font-mono">{result.lockfile}</span>
          {fr(`pas régénéré (${job?.program ?? 'outil'} absent) : la commande est dans la description de la ${word}`)}
        </span>
        {job && <Command command={job.command} label={`la commande de ${result.lockfile}`} />}
      </li>
    )
  }
  return (
    <li className="flex flex-col gap-2 rounded-md border border-border px-3 py-2 text-sm">
      <span className="flex flex-wrap items-center gap-2">
        <CircleX className="size-4 shrink-0 text-danger" aria-hidden="true" />
        <span className="font-mono">{result.lockfile}</span>
        {fr(
          result.status === 'failed'
            ? `${job?.tool ?? "l'outil"} a échoué : ses fichiers sont remis comme avant, pas dans la ${word}`
            : `remis comme avant (${result.error ?? 'échec'}), pas dans la ${word}`,
        )}
      </span>
      {result.status === 'failed' && result.error && (
        <pre className="max-h-48 overflow-auto rounded-sm bg-surface-2 p-2 font-mono text-xs whitespace-pre-wrap [overflow-wrap:anywhere]">
          {lastLines(result.error)}
        </pre>
      )}
    </li>
  )
}

/** La forge d'un dépôt, quand le récapitulatif en mêle plusieurs : son logo et son nom. */
function ForgeTag({ forge, host }: { forge: ForgeKind; host: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-sm text-fg-muted">
      <ForgeLogo forge={forge} className="size-4" />
      {forgeLabel(forge, host)}
    </span>
  )
}
