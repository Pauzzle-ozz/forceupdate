import { useQuery } from '@tanstack/react-query'
import {
  CircleCheck,
  CircleStop,
  CircleX,
  File,
  FileCode,
  Folder,
  FolderGit2,
  FolderOpen,
  History,
  LoaderCircle,
  Play,
  Unplug,
  Upload,
  WifiOff,
  type LucideIcon,
} from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { cn } from 'cn'
import { ApiError, api, queryKeys } from '@/api/client'
import type { RecentPath, ScanSummary, Summary } from '@/api/types'
import { Blade } from '@/components/Blade'
import { EmptyState } from '@/components/EmptyState'
import { FileDrop, UPLOAD_LIMITS } from '@/components/FileDrop'
import { ScanOptionsFields } from '@/components/ScanOptionsFields'
import { KIND_ICON } from '@/components/icons'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { DEFAULT_OPTIONS, rescanRequest, useScanOptions, useStartScan, useUpload } from '@/hooks/useScanActions'
import { useOnline } from '@/hooks/useStatus'
import { basename, count, formatTime, fr } from '@/lib/format'
import { KINDS, KIND_WORD, SEVERITIES } from '@/lib/report'
import { Container, PageHead, Section, useDocumentTitle } from '@/shell/Page'

/** Écran 1 : choisir quoi analyser, ou retrouver une analyse (ECRANS.md, maquette accueil.html). */
export function Home() {
  useDocumentTitle('Analyser')
  const online = useOnline()
  const upload = useUpload()

  return (
    <>
      {!online && (
        <Alert variant="warning" banner role="status">
          <WifiOff aria-hidden="true" />
          <AlertTitle>Pas de réseau</AlertTitle>
          <AlertDescription>
            <p>
              {fr(
                "L'analyse n'utilisera que le cache : ses données peuvent dater de plusieurs jours, et ce qui n'y est pas sortira « non concluant ». L'option « Hors ligne » est cochée.",
              )}
            </p>
          </AlertDescription>
        </Alert>
      )}
      <FileDrop onFile={(file) => upload.mutate(file)} />
      <Container narrow>
        <PageHead>
          <h1 className="text-2xl">Analyser du code</h1>
          <p className="text-fg-muted">
            Un dossier ou un fichier de l'ordinateur, ou les dépôts d'un compte connecté. Rien n'est modifié sans
            validation.
          </p>
        </PageHead>

        <Section aria-labelledby="sources-titre">
          <h2 id="sources-titre" className="sr-only">
            Choisir une source
          </h2>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-4">
            <SourceCard
              icon={FolderOpen}
              title="Un dossier"
              action={
                <Link to="/choisir?mode=dossier" className={buttonVariants({ variant: 'primary' })}>
                  <FolderOpen aria-hidden="true" />
                  Choisir un dossier
                </Link>
              }
            >
              <p>
                Tout le dossier est parcouru (sans <code>node_modules</code>, <code>.venv</code>, ni ce que{' '}
                <code>.gitignore</code> écarte). Un monorepo donne plusieurs projets.
              </p>
            </SourceCard>
            <SourceCard
              icon={FileCode}
              title="Un fichier"
              action={
                <Link to="/choisir?mode=fichier" className={buttonVariants({ variant: 'secondary' })}>
                  Choisir un fichier
                </Link>
              }
            >
              <p>
                Un manifeste ou un lockfile (<code>package.json</code>, <code>requirements.txt</code>,{' '}
                <code>uv.lock</code>…), pris sur l'ordinateur ou déposé ici.
              </p>
              <div
                className="flex flex-col items-center gap-2 rounded-md border-2 border-dashed border-control p-5 text-center text-fg-muted"
                aria-hidden="true"
              >
                <Upload className="size-5" />
                <span className="text-sm">Déposer un fichier n'importe où sur la page</span>
              </div>
            </SourceCard>
            <SourceCard
              icon={FolderGit2}
              title="Mes dépôts"
              action={
                <Link to="/comptes" className={buttonVariants({ variant: 'secondary' })}>
                  Connecter un compte
                </Link>
              }
            >
              <p>
                GitHub, GitLab, Bitbucket : tous les dépôts du compte, analysés sans les cloner. Une PR par dépôt à
                mettre à jour.
              </p>
              <p className="flex items-center gap-2 text-sm">
                <Unplug className="size-4" aria-hidden="true" />
                Aucun compte connecté
              </p>
            </SourceCard>
          </div>
          {upload.error && <UploadError error={upload.error} />}
          {upload.isPending && (
            <p role="status" className="text-sm text-fg-muted">
              Envoi du fichier…
            </p>
          )}
        </Section>

        <PathForm />

        <RecentScans />
      </Container>
    </>
  )
}

function SourceCard({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: LucideIcon
  title: string
  children: React.ReactNode
  action: React.ReactNode
}) {
  return (
    <Card className="flex flex-col gap-3">
      <span className="grid size-10 place-content-center rounded-md bg-primary-soft text-link" aria-hidden="true">
        <Icon className="size-6" />
      </span>
      <CardTitle className="text-lg">{title}</CardTitle>
      <div className="flex flex-col gap-3 text-sm text-fg-muted">{children}</div>
      <div className="mt-auto flex flex-wrap gap-2">{action}</div>
    </Card>
  )
}

/** Un fichier refusé : la raison donnée par le serveur, et les limites. */
export function UploadError({ error }: { error: Error }) {
  return (
    <Alert variant="danger" role="alert">
      <CircleX aria-hidden="true" />
      <AlertTitle>Fichier refusé</AlertTitle>
      <AlertDescription>
        <p>{error.message}</p>
        {error instanceof ApiError && <p className="text-fg-muted">{UPLOAD_LIMITS}</p>}
      </AlertDescription>
    </Alert>
  )
}

/** « Ou donner un chemin » : coller un chemin absolu, avec les options d'analyse. */
function PathForm() {
  const id = useId()
  const [path, setPath] = useState('')
  const [options, setOptions] = useScanOptions()
  const start = useStartScan()

  function submit(event: FormEvent) {
    event.preventDefault()
    if (path.trim()) start.mutate({ path: path.trim(), ...options })
  }

  const error = start.error instanceof ApiError ? start.error.message : null
  return (
    <Section aria-labelledby={`${id}-titre`}>
      <h2 id={`${id}-titre`} className="text-lg">
        Ou donner un chemin
      </h2>
      <form className="flex flex-col gap-2" onSubmit={submit}>
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium" htmlFor={`${id}-chemin`}>
            Chemin absolu d'un dossier ou d'un fichier
          </label>
          <div className="flex gap-2 max-sm:flex-col">
            <Input
              id={`${id}-chemin`}
              mono
              name="path"
              value={path}
              onChange={(event) => setPath(event.target.value)}
              placeholder="C:/Users/moi/Projets/mon-app"
              autoComplete="off"
              spellCheck={false}
              aria-describedby={`${id}-aide${error ? ` ${id}-erreur` : ''}`}
              aria-invalid={error ? true : undefined}
            />
            <Button type="submit" disabled={start.isPending || !path.trim()}>
              {start.isPending ? (
                <LoaderCircle className="animate-spin" aria-hidden="true" />
              ) : (
                <Play aria-hidden="true" />
              )}
              Analyser
            </Button>
          </div>
          <p id={`${id}-aide`} className="text-sm text-fg-muted">
            Coller le chemin copié depuis l'explorateur ou le terminal.
          </p>
          {error && (
            <p id={`${id}-erreur`} role="alert" className="flex items-center gap-2 text-sm text-danger">
              <CircleX className="size-4" aria-hidden="true" />
              {error}
            </p>
          )}
        </div>
        <ScanOptionsFields value={options} onChange={setOptions} />
      </form>
    </Section>
  )
}

/** « Analyses récentes » : celles de la session (`GET /api/scans`), et les chemins récents. */
function RecentScans() {
  const id = useId()
  const online = useOnline()
  const start = useStartScan()
  const scans = useQuery({
    queryKey: queryKeys.scans,
    queryFn: api.listScans,
    // Tant qu'une analyse tourne, sa progression se suit ici.
    refetchInterval: (query) => (query.state.data?.some((scan) => scan.status === 'running') ? 1000 : false),
  })
  const starts = useQuery({ queryKey: queryKeys.folder(null), queryFn: () => api.listFolder() })
  const recent = starts.data?.recent ?? []

  let body: React.ReactNode
  if (scans.isPending || starts.isPending) {
    body = <RecentSkeleton />
  } else if (scans.isError || starts.isError) {
    body = (
      <EmptyState icon={History} title="Analyses récentes indisponibles">
        <p>Elles reviendront dès que le serveur répondra.</p>
      </EmptyState>
    )
  } else if (scans.data.length === 0 && recent.length === 0) {
    body = (
      <EmptyState icon={History} title="Aucune analyse pour l'instant">
        <p>Choisir un dossier ou un fichier ci-dessus. Les chemins analysés seront proposés ici les fois suivantes.</p>
      </EmptyState>
    )
  } else {
    body = (
      <>
        {scans.data.length > 0 && (
          <div className="flex flex-col gap-4">
            <h3 className="text-base">Cette session</h3>
            <ul className="rounded-md border border-border bg-surface">
              {scans.data.map((scan) => (
                <ScanItem
                  key={scan.id}
                  scan={scan}
                  onRescan={() => start.mutate(rescanRequest(scan, online ? {} : { offline: true }))}
                  rescanning={start.isPending}
                />
              ))}
            </ul>
          </div>
        )}
        {recent.length > 0 && (
          <div className="flex flex-col gap-4">
            <h3 className="text-base">Chemins récents</h3>
            <ul className="flex flex-wrap gap-2" aria-label="Chemins récents, à analyser de nouveau">
              {recent.map((item) => (
                <li key={item.path} className="max-w-full">
                  <RecentChip
                    item={item}
                    disabled={start.isPending}
                    onClick={() => start.mutate({ path: item.path, ...DEFAULT_OPTIONS, offline: !online })}
                  />
                </li>
              ))}
            </ul>
          </div>
        )}
        {start.error && (
          <p role="alert" className="flex items-center gap-2 text-sm text-danger">
            <CircleX className="size-4" aria-hidden="true" />
            {start.error.message}
          </p>
        )}
      </>
    )
  }

  const filled = !scans.isPending && !scans.isError && (scans.data.length > 0 || recent.length > 0)
  return (
    <Section aria-labelledby={`${id}-titre`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={`${id}-titre`} className="text-xl">
          Analyses récentes
        </h2>
        {filled && (
          <p className="text-sm text-fg-muted">
            {fr("Les rapports sont gardés le temps de la session ; les chemins, d'une session à l'autre.")}
          </p>
        )}
      </div>
      {body}
    </Section>
  )
}

function RecentSkeleton() {
  return (
    <ul className="rounded-md border border-border bg-surface" aria-busy="true" aria-label="Chargement des analyses récentes">
      {[30, 24].map((width) => (
        <li key={width} className="flex items-center gap-3 border-border px-4 py-3 not-first:border-t">
          <Skeleton className="size-5" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className={width === 30 ? 'w-[30%]' : 'w-[24%]'} />
            <Skeleton className={cn(width === 30 ? 'w-[60%]' : 'w-1/2', 'min-h-2.5')} />
          </div>
          <Skeleton className="h-5.5 w-22" />
        </li>
      ))}
    </ul>
  )
}

function ScanItem({ scan, onRescan, rescanning }: { scan: ScanSummary; onRescan: () => void; rescanning: boolean }) {
  const upload = scan.kind === 'upload'
  const name = upload ? scan.source : basename(scan.source)
  const Icon = scan.kind === 'folder' ? Folder : File
  const report = `/analyses/${scan.id}`
  const progress = scan.progress
  const counted = progress && progress.total > 0 && ['checking', 'package_checked', 'vulnerabilities_checked'].includes(progress.kind)

  let action: React.ReactNode = null
  if (scan.status === 'done') {
    action = (
      <Link to={report} className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
        Ouvrir le rapport
      </Link>
    )
  } else if (scan.status === 'running') {
    action = (
      <Link to={report} className={buttonVariants({ variant: 'ghost', size: 'sm' })}>
        Suivre
      </Link>
    )
  } else if (!upload) {
    action = (
      <Button variant="ghost" size="sm" onClick={onRescan} disabled={rescanning}>
        Relancer
      </Button>
    )
  }

  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-2 border-border px-4 py-3 not-first:border-t md:grid-cols-[auto_minmax(0,1fr)_auto_auto]">
      <Icon className="size-5" aria-hidden="true" />
      <div className="min-w-0">
        {scan.status === 'done' ? (
          <Link to={report} className="font-mono font-bold">
            {name}
          </Link>
        ) : (
          <span className="font-mono font-bold">{name}</span>
        )}
        <div className="font-mono text-xs break-all text-fg-muted">{upload ? 'fichier envoyé' : scan.source}</div>
        {scan.status === 'running' && (
          <Blade
            label={`Analyse de ${name}`}
            value={counted ? progress.done : undefined}
            max={counted ? progress.total : undefined}
            className="mt-1.5 max-w-70"
          />
        )}
      </div>
      <div className="col-start-2 flex flex-wrap items-center gap-2 md:col-start-auto md:justify-end">
        <ScanStatus scan={scan} />
      </div>
      {action && <div className="col-start-2 justify-self-start md:col-start-auto">{action}</div>}
    </li>
  )
}

/** L'état d'une analyse de la session, et ses chiffres une fois finie. */
function ScanStatus({ scan }: { scan: ScanSummary }) {
  const finished = scan.finished_at ? formatTime(scan.finished_at) : null
  switch (scan.status) {
    case 'running': {
      const progress = scan.progress
      const detail =
        progress && progress.total > 0 && progress.kind === 'package_checked'
          ? ` · ${progress.done} sur ${count(progress.total, 'paquet')}`
          : ''
      return (
        <Badge variant="primary">
          <LoaderCircle className="animate-spin" aria-hidden="true" />
          en cours{detail}
        </Badge>
      )
    }
    case 'failed':
      return (
        <>
          <Badge variant="danger">
            <CircleX aria-hidden="true" />
            échouée
          </Badge>
          {finished && <span className="text-sm whitespace-nowrap text-fg-muted">à {finished}</span>}
        </>
      )
    case 'cancelled':
      return (
        <>
          <Badge variant="neutral">
            <CircleStop aria-hidden="true" />
            annulée
          </Badge>
          {finished && <span className="text-sm whitespace-nowrap text-fg-muted">à {finished}</span>}
        </>
      )
    default:
      return (
        <>
          {scan.summary && <SummaryBadges summary={scan.summary} />}
          {finished && <span className="text-sm whitespace-nowrap text-fg-muted">terminée à {finished}</span>}
        </>
      )
  }
}

/** Les chiffres d'une analyse finie : failles (couleur de la plus grave), autres constats, non concluants. */
export function SummaryBadges({ summary }: { summary: Summary }) {
  const findings = summary.findings
  const badges: React.ReactNode[] = []
  for (const kind of KINDS) {
    const n = findings[kind] ?? 0
    if (!n) continue
    const Icon = KIND_ICON[kind]
    const [one, many] = KIND_WORD[kind]
    const worst = SEVERITIES.find((severity) => (summary.vulnerabilities[severity] ?? 0) > 0) ?? 'high'
    const variant = kind === 'vulnerable' ? worst : kind === 'inconclusive' ? 'inconclusive' : 'outline'
    badges.push(
      <Badge key={kind} variant={variant}>
        {(kind === 'vulnerable' || kind === 'inconclusive') && <Icon aria-hidden="true" />}
        {count(n, one, many)}
      </Badge>,
    )
  }
  if (badges.length === 0) {
    return (
      <Badge variant="success">
        <CircleCheck aria-hidden="true" />
        rien à mettre à jour
      </Badge>
    )
  }
  return <>{badges}</>
}

function RecentChip({ item, onClick, disabled }: { item: RecentPath; onClick: () => void; disabled: boolean }) {
  const Icon = item.kind === 'file' ? File : Folder
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={item.path}
      aria-label={`${basename(item.path)}, analyser de nouveau (${item.path})`}
      className="inline-flex min-h-(--control-h) max-w-full items-center gap-2 rounded-full border border-border bg-surface px-3 text-sm text-fg transition-colors duration-150 hover:border-control disabled:opacity-45"
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      <span className="truncate font-mono">{basename(item.path)}</span>
    </button>
  )
}
