import {
  CircleCheck,
  CircleHelp,
  CircleStop,
  CircleX,
  FolderGit2,
  GitPullRequest,
  KeyRound,
  ListChecks,
  LoaderCircle,
  Lock,
  Play,
  Plug,
  RefreshCw,
  ServerOff,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  WifiOff,
  type LucideIcon,
} from 'lucide-react'
import { useId, useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { cn } from 'cn'
import type { Access, RepositoryAccount, RepositoryBatch, RepositoryList as List, RepositoryRow } from '@/api/types'
import { Blade } from '@/components/Blade'
import { EmptyState } from '@/components/EmptyState'
import { ForgeLogo } from '@/components/ForgeLogo'
import { Alert, AlertActions, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { analyzing, useCancelBatch, useReloadRepositories, useRepositories, useStartBatch } from '@/hooks/useRepositories'
import { REPOSITORY_OPTIONS, useScanRepository } from '@/hooks/useScanActions'
import { useOnline } from '@/hooks/useStatus'
import { count, formatDateTime, formatNumber, formatRelative, formatTime, fr } from '@/lib/format'
import { forgeLabel, proposalPath, requestWord, requestWords } from '@/lib/proposals'
import {
  DEFAULT_REPOSITORY_SORT,
  NO_REPOSITORY_FILTERS,
  keysOf,
  filterRepositories,
  rateLow,
  rateText,
  sortRepositories,
  type RepositoryFilters,
  type RepositorySort,
  type StateFilter,
} from '@/lib/repositories'
import { Container, PageHead, Section, useDocumentTitle } from '@/shell/Page'
import { errorText } from '@/screens/accounts/ForgeCard'
import { RepositoryList } from './RepositoryList'

/** Les droits d'un compte en un badge ; « PR » se lit « MR » sur GitLab. */
const ACCESS: Record<Access, { label: string; variant: 'success' | 'warning' | 'inconclusive'; icon: LucideIcon }> = {
  write: { label: 'lecture et PR', variant: 'success', icon: CircleCheck },
  public: { label: 'dépôts publics seulement', variant: 'warning', icon: TriangleAlert },
  read: { label: 'lecture seule', variant: 'warning', icon: TriangleAlert },
  unknown: { label: 'droits non vérifiés', variant: 'inconclusive', icon: CircleHelp },
}

/**
 * Écran 7 : les dépôts des comptes connectés, analysés sans les cloner (ECRANS.md,
 * pages/depots.md, maquette depots.html). L'état de chaque dépôt et la synthèse viennent du
 * serveur ; la liste est relue chaque seconde tant qu'une analyse tourne.
 */
export function RepositoriesPage() {
  useDocumentTitle('Mes dépôts')
  const list = useRepositories()

  if (list.isPending) return <Loading />
  if (list.isError) {
    return (
      <Container>
        <EmptyState
          icon={ServerOff}
          level="h1"
          title="Dépôts indisponibles"
          actions={
            <Button onClick={() => void list.refetch()}>
              <RefreshCw aria-hidden="true" />
              Réessayer
            </Button>
          }
        >
          <p>{errorText(list.error)}</p>
        </EmptyState>
      </Container>
    )
  }
  if (list.data.accounts.length === 0) return <NoAccount />
  return <Repositories data={list.data} />
}

function Loading() {
  return (
    <Container>
      <PageHead>
        <h1 className="text-2xl">Mes dépôts</h1>
        <p className="text-fg-muted">Liste des dépôts demandée aux forges…</p>
      </PageHead>
      <div className="flex flex-col gap-6" aria-busy="true" aria-label="Chargement des dépôts">
        <Skeleton className="h-10 w-72" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(170px,1fr))]">
          {[1, 2, 3, 4, 5].map((n) => (
            <Skeleton key={n} className="h-24" />
          ))}
        </div>
        <div className="flex flex-col gap-2 rounded-md border border-border bg-surface p-4">
          <Skeleton />
          <Skeleton />
          <Skeleton className="w-[85%]" />
          <Skeleton className="w-[70%]" />
        </div>
      </div>
    </Container>
  )
}

function NoAccount() {
  return (
    <Container>
      <PageHead>
        <h1 className="text-2xl">Mes dépôts</h1>
      </PageHead>
      <EmptyState
        icon={Plug}
        level="h2"
        title="Aucun compte connecté"
        actions={
          <Link to="/comptes" className={buttonVariants({ variant: 'primary' })}>
            <Plug aria-hidden="true" />
            Connecter un compte
          </Link>
        }
      >
        <p>
          {fr(
            "Connecter un compte GitHub : forceupdate liste alors tous ses dépôts (les siens, ceux où il collabore, ceux de ses organisations) et les analyse sans les cloner. Le token reste dans le trousseau de l'ordinateur.",
          )}
        </p>
      </EmptyState>
      <PublicRepository connected={false} />
    </Container>
  )
}

function Repositories({ data }: { data: List }) {
  const online = useOnline()
  const navigate = useNavigate()
  const reload = useReloadRepositories()
  const start = useStartBatch()
  const cancel = useCancelBatch()
  const [filters, setFilters] = useState<RepositoryFilters>(NO_REPOSITORY_FILTERS)
  const [sort, setSort] = useState<RepositorySort>(DEFAULT_REPOSITORY_SORT)
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())

  const all = data.repositories
  const shown = useMemo(() => sortRepositories(filterRepositories(all, filters), sort), [all, filters, sort])
  const synthesis = data.synthesis
  const running = analyzing(data)
  const blocked = !online ? 'Hors ligne : les analyses attendront le réseau.' : running ? 'Une analyse est en cours.' : null
  const visible = all.filter((row) => !row.hidden)
  const inconclusive = all.filter((row) => row.state === 'inconclusive')

  function analyze(rows: RepositoryRow[]) {
    if (rows.length > 0) start.mutate({ repositories: keysOf(rows), ...REPOSITORY_OPTIONS })
    setSelected(new Set())
  }

  /** L'écran 8, pour les dépôts sélectionnés : un récapitulatif, de toutes leurs forges. */
  function propose(rows: RepositoryRow[]) {
    if (rows.length > 0) void navigate(proposalPath(keysOf(rows)))
  }

  function select(keys: string[], checked: boolean) {
    setSelected((current) => {
      const next = new Set(current)
      for (const key of keys) {
        if (checked) next.add(key)
        else next.delete(key)
      }
      return next
    })
  }

  function filterState(state: StateFilter) {
    setFilters((current) => ({ ...current, state: current.state === state ? 'all' : state }))
  }

  const accounts = data.accounts
  return (
    <>
      {!online && (
        <Alert variant="warning" banner role="status">
          <WifiOff aria-hidden="true" />
          <AlertTitle>Pas de réseau</AlertTitle>
          <AlertDescription>
            <p>
              {fr(
                `La liste affichée est celle du dernier chargement${
                  accounts[0]?.listed_at ? ` (${formatRelative(accounts[0].listed_at)})` : ''
                }. Les analyses attendront le réseau.`,
              )}
            </p>
          </AlertDescription>
        </Alert>
      )}
      <Container>
        <PageHead
          actions={
            <>
              <Link to="/comptes" className={buttonVariants({ variant: 'secondary' })}>
                <KeyRound aria-hidden="true" />
                Comptes
              </Link>
              <Button onClick={() => reload.mutate()} disabled={!online || reload.isPending}>
                <RefreshCw className={cn(reload.isPending && 'animate-spin')} aria-hidden="true" />
                Recharger la liste
              </Button>
              <Button onClick={() => analyze(visible)} disabled={blocked !== null || start.isPending || visible.length === 0}>
                <Play aria-hidden="true" />
                Analyser tous les dépôts
              </Button>
            </>
          }
        >
          <h1 className="text-2xl">Mes dépôts</h1>
          <p className="text-fg-muted">
            {fr(
              `${count(synthesis.repositories, 'dépôt')} sur ${count(accounts.length, 'compte')}. Analysés par l'API, sans les cloner.`,
            )}
          </p>
        </PageHead>

        <div className="mb-6 flex flex-col gap-4 empty:hidden">
          {accounts.map((account) => (
            <AccountAlert key={`${account.forge}:${account.host}`} account={account} />
          ))}
          {reload.error && (
            <Alert variant="danger" role="alert">
              <CircleX aria-hidden="true" />
              <AlertTitle>Liste non rechargée</AlertTitle>
              <AlertDescription>
                <p>{errorText(reload.error)}</p>
              </AlertDescription>
            </Alert>
          )}
          {start.error && (
            <Alert variant="danger" role="alert">
              <CircleX aria-hidden="true" />
              <AlertTitle>Analyse refusée</AlertTitle>
              <AlertDescription>
                <p>{errorText(start.error)}</p>
              </AlertDescription>
            </Alert>
          )}
          {inconclusive.length > 0 && !running && (
            <Alert variant="inconclusive" role="status">
              <CircleHelp aria-hidden="true" />
              <AlertTitle>{count(inconclusive.length, 'dépôt non concluant', 'dépôts non concluants')}</AlertTitle>
              <AlertDescription>
                <p>
                  {fr(
                    "Leur analyse n'a pas pu tout vérifier (registre ou forge injoignables, limite d'API atteinte, arborescence incomplète). Ils ne sont pas « à jour » : les relancer.",
                  )}
                </p>
              </AlertDescription>
              <AlertActions>
                <Button size="sm" onClick={() => analyze(inconclusive)} disabled={blocked !== null || start.isPending}>
                  {inconclusive.length >= 2 ? `Relancer ces ${inconclusive.length} dépôts` : 'Relancer ce dépôt'}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => filterState('inconclusive')}>
                  Les voir
                </Button>
              </AlertActions>
            </Alert>
          )}
          {accounts.flatMap((account) =>
            account.restrictions.map((restriction) => (
              <Alert key={`${account.forge}:${restriction.organization}`} variant="info" role="status">
                <Lock aria-hidden="true" />
                <AlertTitle>
                  {restriction.kind === 'sso'
                    ? `L'organisation ${restriction.organization} exige d'autoriser le token pour son SSO`
                    : `L'organisation ${restriction.organization} limite l'accès des applications`}
                </AlertTitle>
                <AlertDescription>
                  <p>
                    {restriction.kind === 'sso'
                      ? fr("Ses dépôts n'apparaîtront qu'une fois le token autorisé pour son authentification unique (SAML).")
                      : fr(
                          `Ses dépôts privés n'apparaîtront qu'après l'accord d'un de ses propriétaires sur ${forgeLabel(account.forge, account.host)}. Ses dépôts publics sont listés.`,
                        )}
                  </p>
                </AlertDescription>
                {restriction.url && (
                  <AlertActions>
                    <a
                      href={restriction.url}
                      target="_blank"
                      rel="noreferrer"
                      className={buttonVariants({ variant: 'ghost', size: 'sm' })}
                      aria-label={`${restriction.kind === 'sso' ? 'Autoriser le token' : "Demander l'accès"} sur ${forgeLabel(account.forge, account.host)} (nouvel onglet)`}
                    >
                      {restriction.kind === 'sso' ? 'Autoriser le token' : "Demander l'accès"} sur {forgeLabel(account.forge, account.host)}
                    </a>
                  </AlertActions>
                )}
              </Alert>
            )),
          )}
        </div>

        <Section aria-labelledby="comptes-titre">
          <h2 id="comptes-titre" className="sr-only">
            Comptes connectés
          </h2>
          <ul className="flex flex-wrap gap-2">
            {accounts.map((account) => (
              <AccountChip key={`${account.forge}:${account.host}`} account={account} />
            ))}
          </ul>
        </Section>

        <Synthesis data={data} state={filters.state} onState={filterState} />

        {data.batch && <BatchCard batch={data.batch} onCancel={() => cancel.mutate(data.batch!.id)} cancelling={cancel.isPending} />}

        {all.length === 0 ? (
          <Section>
            <EmptyState icon={FolderGit2} level="h2" title="Aucun dépôt accessible">
              <p>{fr("Le compte connecté n'a aucun dépôt, ni à lui, ni en collaboration, ni dans ses organisations.")}</p>
            </EmptyState>
          </Section>
        ) : (
          <RepositoryList
            all={all}
            shown={shown}
            synthesis={synthesis}
            filters={filters}
            onFilters={setFilters}
            sort={sort}
            onSort={setSort}
            selected={selected}
            onSelect={select}
            onAnalyze={analyze}
            onPropose={propose}
            proposeBlocked={online ? null : 'Hors ligne : les analyses et les PR attendront le réseau.'}
            blocked={blocked}
            pending={start.isPending}
          />
        )}

        <PublicRepository connected />
      </Container>
    </>
  )
}

/** Ce qui ne va pas avec un compte : token refusé, liste qui n'a pas pu être (re)chargée. */
function AccountAlert({ account }: { account: RepositoryAccount }) {
  const name = forgeLabel(account.forge, account.host)
  if (account.problem) {
    return (
      <Alert variant="danger" role="alert">
        <KeyRound aria-hidden="true" />
        <AlertTitle>
          {name} refuse le token de {account.login}
        </AlertTitle>
        <AlertDescription>
          <p>{account.problem}</p>
        </AlertDescription>
        <AlertActions>
          <Link to="/comptes" className={buttonVariants({ variant: 'primary', size: 'sm' })}>
            Reconnecter {name}
          </Link>
        </AlertActions>
      </Alert>
    )
  }
  if (!account.error) return null
  return (
    <Alert variant="warning" role="status">
      <TriangleAlert aria-hidden="true" />
      <AlertTitle>Liste de {name} non rechargée</AlertTitle>
      <AlertDescription>
        <p>{account.error}</p>
        <p className="text-fg-muted">
          {account.listed_at
            ? fr(`La liste affichée est celle du ${formatDateTime(account.listed_at)}.`)
            : 'Aucune liste chargée pour ce compte.'}
        </p>
      </AlertDescription>
    </Alert>
  )
}

function AccountChip({ account }: { account: RepositoryAccount }) {
  const name = forgeLabel(account.forge, account.host)
  const access = ACCESS[account.access]
  const label = access.label.replace('PR', requestWord(account.forge))
  const AccessIcon = access.icon
  return (
    <li className="inline-flex min-h-(--control-h) max-w-full items-center gap-2 rounded-full border border-border bg-surface px-3 text-sm">
      <ForgeLogo forge={account.forge} className="size-4" />
      <b>{name}</b>
      <span className="truncate font-mono">{account.login}</span>
      {account.problem ? (
        <Badge variant="danger">
          <CircleX aria-hidden="true" />
          token refusé
        </Badge>
      ) : (
        <Badge variant={access.variant}>
          <AccessIcon aria-hidden="true" />
          {label}
        </Badge>
      )}
    </li>
  )
}

/** La synthèse multi-dépôts (calculée par le serveur) ; un compteur non nul filtre le tableau. */
function Synthesis({ data, state, onState }: { data: List; state: StateFilter; onState: (state: StateFilter) => void }) {
  const synthesis = data.synthesis
  const rates = data.accounts.filter((account) => account.rate_limit !== null)
  // « Aucune faille connue » ne se dit qu'une fois toutes les analyses finies.
  const settled = synthesis.analyzed > 0 && synthesis.running === 0
  return (
    <Section aria-labelledby="synthese-titre">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="synthese-titre" className="text-xl">
          Synthèse
        </h2>
        {rates.map((account) => {
          const rate = account.rate_limit!
          const low = rateLow(rate)
          return (
            <p
              key={`${account.forge}:${account.host}`}
              className={cn('flex items-center gap-1.5 text-sm', low ? 'text-warning' : 'text-fg-muted')}
            >
              {low && <TriangleAlert className="size-4" aria-hidden="true" />}
              {rateText(rate, forgeLabel(account.forge, account.host))}
            </p>
          )
        })}
      </div>
      <div
        className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(170px,1fr))]"
        role="group"
        aria-label="Synthèse des dépôts ; choisir un compteur filtre le tableau"
      >
        <Stat
          icon={FolderGit2}
          label="Dépôts"
          value={synthesis.repositories}
          detail={`${formatNumber(synthesis.analyzed)} ${synthesis.analyzed >= 2 ? 'analysés' : 'analysé'} · ${formatNumber(synthesis.skipped)} ${synthesis.skipped >= 2 ? 'sautés' : 'sauté'}`}
        />
        <Stat
          icon={synthesis.vulnerabilities === 0 && settled ? ShieldCheck : ShieldAlert}
          label="Failles"
          value={synthesis.vulnerabilities}
          detail={
            synthesis.vulnerabilities > 0
              ? `dont ${count(synthesis.critical, 'critique')} · dans ${count(synthesis.vulnerable_repositories, 'dépôt')}`
              : synthesis.running > 0
                ? 'analyse en cours'
                : settled
                  ? 'aucune connue'
                  : null
          }
          sense={synthesis.vulnerabilities > 0 ? 'danger' : settled ? 'success' : null}
          pressed={state === 'vulnerable'}
          onPress={() => onState('vulnerable')}
        />
        <Stat
          icon={ListChecks}
          label="À mettre à jour"
          value={synthesis.to_update}
          detail={agreeRepositories(synthesis.to_update)}
          pressed={state === 'to_update'}
          onPress={() => onState('to_update')}
        />
        <Stat
          icon={CircleCheck}
          label="À jour"
          value={synthesis.up_to_date}
          detail={agreeRepositories(synthesis.up_to_date)}
          sense={synthesis.up_to_date > 0 ? 'success' : null}
          pressed={state === 'up_to_date'}
          onPress={() => onState('up_to_date')}
        />
        <Stat
          icon={CircleHelp}
          label="Non concluants"
          value={synthesis.inconclusive}
          detail={synthesis.inconclusive > 0 ? 'à relancer' : null}
          sense={synthesis.inconclusive > 0 ? 'inconclusive' : null}
          pressed={state === 'inconclusive'}
          onPress={() => onState('inconclusive')}
        />
        <Stat
          icon={GitPullRequest}
          label={`${requestWords(data.repositories.map((row) => row.forge))} ouvertes`}
          value={synthesis.open_requests}
          detail={synthesis.open_requests > 0 ? 'par forceupdate' : null}
        />
      </div>
    </Section>
  )
}

function agreeRepositories(n: number): string {
  return n >= 2 ? 'dépôts' : 'dépôt'
}

const SENSE = {
  danger: 'border-l-4 border-l-high',
  success: 'border-l-4 border-l-success',
  inconclusive: 'border-l-4 border-dashed border-l-inconclusive',
} as const

function Stat({
  icon: Icon,
  label,
  value,
  detail,
  sense = null,
  pressed,
  onPress,
}: {
  icon: LucideIcon
  label: string
  value: number
  detail: string | null
  sense?: keyof typeof SENSE | null
  pressed?: boolean
  onPress?: () => void
}) {
  const content = (
    <>
      <span className="flex items-center gap-2 text-sm font-medium text-fg-muted">
        <Icon className="size-4" aria-hidden="true" />
        {label}
      </span>
      <span className={cn('text-2xl leading-[1.1] tabular-nums sm:text-3xl', value === 0 ? 'font-medium text-fg-muted' : 'font-semibold')}>
        {formatNumber(value)}
      </span>
      {detail && <span className="text-xs text-fg-muted">{detail}</span>}
    </>
  )
  const box = cn('flex flex-col gap-1 rounded-md border border-border bg-surface px-4 py-3 text-left text-fg', sense && SENSE[sense])
  if (!onPress || value === 0) return <div className={box}>{content}</div>
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

/** L'analyse groupée : où elle en est, ce qu'elle consomme, « Annuler ». */
function BatchCard({ batch, onCancel, cancelling }: { batch: RepositoryBatch; onCancel: () => void; cancelling: boolean }) {
  const running = batch.status === 'running'
  const total = count(batch.total, 'dépôt')
  let title: string
  if (running) title = fr(`Analyse de ${total} : ${batch.finished} ${batch.finished >= 2 ? 'terminées' : 'terminée'}`)
  else if (batch.status === 'cancelled') title = `Analyse de ${total} annulée`
  else title = `Analyse de ${total} terminée${batch.finished_at ? ` à ${formatTime(batch.finished_at)}` : ''}`
  const details = [
    running ? `${batch.concurrency} à la fois` : null,
    'registres en cache partagés',
    `${count(batch.requests, "requête d'API utilisée", "requêtes d'API utilisées")}`,
    batch.failed > 0 ? count(batch.failed, 'échouée', 'échouées') : null,
    batch.skipped.length > 0 ? `${count(batch.skipped.length, 'dépôt vide sauté', 'dépôts vides sautés')}` : null,
  ].filter(Boolean)
  return (
    <Card className="mt-6 flex flex-col gap-3" role="region" aria-labelledby="lot-titre">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="lot-titre" className="flex items-center gap-2 text-base" aria-live="polite">
          {running ? (
            <LoaderCircle className="size-4 animate-spin text-link" aria-hidden="true" />
          ) : batch.status === 'cancelled' ? (
            <CircleStop className="size-4 text-fg-muted" aria-hidden="true" />
          ) : (
            <CircleCheck className="size-4 text-success" aria-hidden="true" />
          )}
          {title}
        </h2>
        {running && (
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={cancelling}>
            <CircleStop aria-hidden="true" />
            Annuler
          </Button>
        )}
      </div>
      {running && (
        <Blade
          label="Dépôts analysés"
          value={batch.finished}
          max={batch.total}
          valueText={`${batch.finished} sur ${batch.total}`}
        />
      )}
      <p className="text-sm text-fg-muted">{details.join(' · ')}</p>
    </Card>
  )
}

/** « Analyser un autre dépôt » : un dépôt public d'un autre compte, par son nom ou son adresse. */
function PublicRepository({ connected }: { connected: boolean }) {
  const id = useId()
  const online = useOnline()
  const [value, setValue] = useState('')
  const scan = useScanRepository()

  function submit(event: FormEvent) {
    event.preventDefault()
    if (value.trim()) scan.mutate({ repository: value.trim(), ...REPOSITORY_OPTIONS })
  }

  const error = scan.error ? errorText(scan.error) : null
  return (
    <Section aria-labelledby={`${id}-titre`}>
      <h2 id={`${id}-titre`} className="text-lg">
        Analyser un autre dépôt
      </h2>
      <form className="flex flex-col gap-1" onSubmit={submit}>
        <label className="text-sm font-medium" htmlFor={`${id}-depot`}>
          Dépôt public : owner/nom ou adresse
        </label>
        <div className="flex gap-2 max-sm:flex-col">
          <Input
            id={`${id}-depot`}
            mono
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder="pallets/flask"
            autoComplete="off"
            spellCheck={false}
            aria-describedby={`${id}-aide${error ? ` ${id}-erreur` : ''}`}
            aria-invalid={error ? true : undefined}
          />
          <Button type="submit" disabled={scan.isPending || !value.trim() || !online}>
            {scan.isPending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Play aria-hidden="true" />}
            Analyser
          </Button>
        </div>
        <p id={`${id}-aide`} className="text-sm text-fg-muted">
          {fr(
            connected
              ? "Un dépôt d'un autre compte, s'il est public (ou si le compte connecté y a accès). Lu par l'API, sans le cloner."
              : "Sans compte connecté, GitHub limite à 60 requêtes par heure : quelques dépôts publics. Lu par l'API, sans le cloner.",
          )}
        </p>
        {error && (
          <p id={`${id}-erreur`} role="alert" className="flex items-center gap-2 text-sm text-danger">
            <CircleX className="size-4 shrink-0" aria-hidden="true" />
            {error}
          </p>
        )}
      </form>
    </Section>
  )
}
