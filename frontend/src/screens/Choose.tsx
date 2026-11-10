import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  CircleX,
  CornerLeftUp,
  Eye,
  File,
  FileCode,
  Folder,
  FolderSearch,
  HardDrive,
  House,
  LoaderCircle,
  Play,
  Search,
  Upload,
} from 'lucide-react'
import { useId, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { cn } from 'cn'
import { ApiError, api, queryKeys } from '@/api/client'
import type { Entry, Listing } from '@/api/types'
import { EmptyState } from '@/components/EmptyState'
import { FileDrop, UPLOAD_LIMITS } from '@/components/FileDrop'
import { ScanOptionsFields } from '@/components/ScanOptionsFields'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { useScanOptions, useStartScan, useUpload } from '@/hooks/useScanActions'
import { basename, count, formatNumber, fr } from '@/lib/format'
import { UploadError } from '@/screens/Home'
import { Breadcrumb, Container, PageHead, Section, useDocumentTitle } from '@/shell/Page'

/**
 * Écran 2 : désigner un dossier ou un fichier de l'ordinateur (ECRANS.md). Le navigateur ne
 * peut pas donner un chemin à une page : c'est le serveur qui liste (`GET /api/fs`). Le
 * dossier ouvert est dans l'adresse (`?chemin=`), pour le retour arrière.
 */
export function Choose() {
  const [params, setParams] = useSearchParams()
  const mode = params.get('mode') === 'fichier' ? 'fichier' : 'dossier'
  const path = params.get('chemin')
  const title = mode === 'fichier' ? 'Choisir un fichier' : 'Choisir un dossier'
  useDocumentTitle(title)

  const [selected, setSelected] = useState<string | null>(null)
  const [options, setOptions] = useScanOptions()
  const start = useStartScan()
  const upload = useUpload()
  const listing = useQuery({
    queryKey: queryKeys.folder(path),
    queryFn: () => api.listFolder(path),
    placeholderData: keepPreviousData,
  })

  function open(next: string | null, select: string | null = null) {
    setSelected(select)
    const updated = new URLSearchParams(params)
    if (next) updated.set('chemin', next)
    else updated.delete('chemin')
    setParams(updated)
  }

  const shown = listing.data && !listing.isPlaceholderData ? listing.data : null
  const folder = shown?.path ?? null

  // « Parcourir… » : la fenêtre de choix du système, ouverte par le serveur (session 36).
  const browse = useMutation({
    mutationFn: () =>
      api.pick({ kind: mode === 'fichier' ? 'file' : 'folder', start: folder ?? listing.data?.home ?? null }),
    onSuccess: ({ path: chosen }) => {
      if (!chosen) return
      if (mode === 'fichier') open(parentOf(chosen), chosen)
      else open(chosen)
    },
  })

  return (
    <>
      <FileDrop onFile={(file) => upload.mutate(file)} />
      <Container narrow>
        <Breadcrumb items={[{ label: 'Analyser', to: '/' }, { label: title }]} />
        <PageHead>
          <h1 className="text-2xl">{title}</h1>
          <p className="text-fg-muted">
            {fr(
              "Les dossiers de l'ordinateur, listés par le serveur local : seulement les noms des dossiers, des fichiers de dépendances et des fichiers de code, jamais leur contenu. Un fichier de code est analysé à travers son projet, ou par ses imports.",
            )}
          </p>
        </PageHead>

        <Section aria-label="Parcourir">
          <PathField
            key={path ?? ''}
            path={path ?? ''}
            onOpen={(next) => open(next)}
            browse={
              <Button type="button" onClick={() => browse.mutate()} disabled={browse.isPending}>
                {browse.isPending ? (
                  <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />
                ) : (
                  <FolderSearch aria-hidden="true" />
                )}
                Parcourir…
              </Button>
            }
          />
          {browse.isPending && (
            <p role="status" className="text-sm text-fg-muted">
              {fr(
                `La fenêtre de choix ${mode === 'fichier' ? "d'un fichier" : "d'un dossier"} est ouverte : elle peut se trouver derrière le navigateur.`,
              )}
            </p>
          )}
          {browse.error && (
            <p role="alert" className="flex items-center gap-2 text-sm text-danger">
              <CircleX className="size-4 shrink-0" aria-hidden="true" />
              {browse.error.message}
            </p>
          )}
          {listing.isError && <ListingError error={listing.error} path={path} />}
          <Card className="p-0">
            {shown ? (
              <FolderList
                key={shown.path ?? ''}
                listing={shown}
                selected={selected}
                onOpen={open}
                onSelect={(entry) => setSelected(entry.path === selected ? null : entry.path)}
              />
            ) : listing.isError ? null : (
              <ListSkeleton />
            )}
          </Card>
          <div className="flex flex-wrap items-center gap-2">
            {selected ? (
              <>
                <Button
                  variant="primary"
                  disabled={start.isPending}
                  onClick={() => start.mutate({ path: selected, ...options })}
                >
                  {start.isPending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Play aria-hidden="true" />}
                  Analyser ce fichier
                </Button>
                <span className="font-mono text-sm break-all text-fg-muted">{basename(selected)}</span>
              </>
            ) : (
              <>
                <Button
                  variant={mode === 'fichier' ? 'secondary' : 'primary'}
                  disabled={!folder || start.isPending}
                  onClick={() => folder && start.mutate({ path: folder, ...options })}
                >
                  {start.isPending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Play aria-hidden="true" />}
                  Analyser ce dossier
                </Button>
                {folder && <span className="font-mono text-sm break-all text-fg-muted">{basename(folder)}</span>}
                {!folder && shown && (
                  <span className="text-sm text-fg-muted">Ouvrir d'abord un dossier.</span>
                )}
              </>
            )}
          </div>
          {start.error && (
            <p role="alert" className="flex items-center gap-2 text-sm text-danger">
              <CircleX className="size-4" aria-hidden="true" />
              {start.error.message}
            </p>
          )}
          <ScanOptionsFields value={options} onChange={setOptions} />
        </Section>

        <Section aria-labelledby="envoyer-titre">
          <h2 id="envoyer-titre" className="text-lg">
            Ou envoyer un fichier
          </h2>
          <UploadZone onFile={(file) => upload.mutate(file)} pending={upload.isPending} prominent={mode === 'fichier' && !selected} />
          {upload.error && <UploadError error={upload.error} />}
        </Section>
      </Container>
    </>
  )
}

/**
 * Le chemin courant, éditable : coller un chemin et y aller ; `browse`, la fenêtre du système.
 * « Aller » n'est jamais désactivé : c'est une navigation, pas une action, et un chemin
 * remplace celui qui charge (les squelettes disent le chargement). Désactivé, il faisait perdre
 * Entrée sans rien dire : un formulaire dont le bouton d'envoi l'est ne s'envoie pas (E38).
 */
function PathField({
  path,
  onOpen,
  browse,
}: {
  path: string
  onOpen: (path: string | null) => void
  browse: ReactNode
}) {
  const id = useId()
  const [value, setValue] = useState(path)

  function submit(event: FormEvent) {
    event.preventDefault()
    onOpen(value.trim() || null)
  }

  return (
    <form className="flex flex-col gap-1" onSubmit={submit}>
      <label className="text-sm font-medium" htmlFor={`${id}-chemin`}>
        Dossier ouvert
      </label>
      <div className="flex gap-2 max-sm:flex-col">
        <Input
          id={`${id}-chemin`}
          mono
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Points de départ"
          autoComplete="off"
          spellCheck={false}
          aria-describedby={`${id}-aide`}
        />
        <Button type="submit" variant="ghost">
          <ArrowRight aria-hidden="true" />
          Aller
        </Button>
        {browse}
      </div>
      <p id={`${id}-aide`} className="text-sm text-fg-muted">
        {fr(
          "Coller un chemin absolu pour y aller ; vide : les points de départ. « Parcourir… » ouvre la fenêtre de choix de l'ordinateur.",
        )}
      </p>
    </form>
  )
}

function ListingError({ error, path }: { error: Error; path: string | null }) {
  if (!(error instanceof ApiError)) return null
  return (
    <Alert variant="danger" role="alert">
      <CircleX aria-hidden="true" />
      <AlertTitle>Dossier illisible</AlertTitle>
      <AlertDescription>
        <p>{error.message}</p>
        <p className="text-fg-muted">
          {path ? fr('Corriger le chemin ci-dessus, ou repartir des points de départ (chemin vide).') : null}
        </p>
      </AlertDescription>
    </Alert>
  )
}

function ListSkeleton() {
  return (
    <ul aria-busy="true" aria-label="Chargement du dossier">
      {['w-[30%]', 'w-[45%]', 'w-[25%]', 'w-[38%]'].map((width) => (
        <li key={width} className="flex items-center gap-3 border-border px-4 py-3 not-first:border-t">
          <Skeleton className="size-5" />
          <Skeleton className={width} />
        </li>
      ))}
    </ul>
  )
}

const ROW =
  'flex min-h-11 w-full items-center gap-3 px-4 py-2 text-left text-sm transition-colors duration-150 hover:bg-surface-hover focus-visible:-outline-offset-2'

/**
 * La liste d'un dossier, ou les points de départ. Flèches pour parcourir, Entrée pour ouvrir
 * un dossier (ou choisir un fichier), Retour arrière pour remonter.
 */
function FolderList({
  listing,
  selected,
  onOpen,
  onSelect,
}: {
  listing: Listing
  selected: string | null
  onOpen: (path: string | null, select?: string | null) => void
  onSelect: (entry: Entry) => void
}) {
  const id = useId()
  const [filter, setFilter] = useState('')
  const [showHidden, setShowHidden] = useState(false)
  const list = useRef<HTMLUListElement>(null)

  const query = filter.trim().toLocaleLowerCase('fr')
  const hidden = listing.entries.filter((entry) => entry.hidden).length
  const entries = listing.entries.filter(
    (entry) => (showHidden || !entry.hidden) && (!query || entry.name.toLocaleLowerCase('fr').includes(query)),
  )

  function keys(event: KeyboardEvent<HTMLUListElement>) {
    const buttons = [...(list.current?.querySelectorAll<HTMLButtonElement>('button[data-entry]') ?? [])]
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const next = event.key === 'ArrowDown' ? Math.min(buttons.length - 1, index + 1) : Math.max(0, index - 1)
      buttons[next]?.focus()
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      buttons[event.key === 'Home' ? 0 : buttons.length - 1]?.focus()
    } else if (event.key === 'Backspace' && listing.path) {
      event.preventDefault()
      onOpen(listing.parent)
    }
  }

  const starts = listing.path === null
  const folders = entries.filter((entry) => entry.kind === 'folder' || entry.kind === 'drive').length
  const files = entries.filter((entry) => entry.kind === 'file').length
  const code = entries.length - folders - files

  return (
    <div className="flex flex-col">
      {!starts && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <div className="relative min-w-55 flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-fg-muted" aria-hidden="true" />
            <label htmlFor={`${id}-filtre`} className="sr-only">
              Filtrer par nom
            </label>
            <Input
              id={`${id}-filtre`}
              className="pl-9"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filtrer par nom"
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          {hidden > 0 && (
            <Button size="sm" variant="ghost" aria-pressed={showHidden} onClick={() => setShowHidden((shown) => !shown)}>
              <Eye aria-hidden="true" />
              {showHidden ? 'Masquer les éléments cachés' : `Afficher les éléments cachés (${formatNumber(hidden)})`}
            </Button>
          )}
          <p className="w-full text-sm text-fg-muted" aria-live="polite">
            {count(folders, 'dossier')}, {count(files, 'fichier')} de dépendances
            {code > 0 && `, ${count(code, 'fichier')} de code`}
          </p>
        </div>
      )}
      {/* Les flèches passent d'un bouton de la liste à l'autre : le clavier de ses boutons. */}
      {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <ul ref={list} onKeyDown={keys} aria-label={starts ? 'Points de départ' : `Contenu de ${listing.path}`}>
        {listing.path && (
          <li>
            <button
              type="button"
              data-entry
              className={ROW}
              onClick={() => onOpen(listing.parent)}
            >
              <CornerLeftUp className="size-5 shrink-0" aria-hidden="true" />
              <span>Dossier parent</span>
              <span className="truncate font-mono text-xs text-fg-muted">{listing.parent ?? 'points de départ'}</span>
            </button>
          </li>
        )}
        {entries.map((entry) => {
          const isFile = entry.kind === 'file' || entry.kind === 'code'
          const Icon =
            entry.kind === 'drive'
              ? HardDrive
              : entry.kind === 'file'
                ? FileCode
                : entry.kind === 'code'
                  ? File
                  : starts && entry.path === listing.home
                    ? House
                    : Folder
          const chosen = entry.path === selected
          return (
            <li key={entry.path} className="border-t border-border">
              <button
                type="button"
                data-entry
                className={cn(ROW, chosen && 'bg-primary-soft')}
                aria-pressed={isFile ? chosen : undefined}
                onClick={() => (isFile ? onSelect(entry) : onOpen(entry.path))}
              >
                <Icon className={cn('size-5 shrink-0', entry.kind === 'file' && 'text-link')} aria-hidden="true" />
                <span className={cn('min-w-0 font-mono break-all', entry.hidden && 'text-fg-muted')}>{entry.name}</span>
                {starts && entry.path === listing.home && <span className="text-xs text-fg-muted">dossier personnel</span>}
                {isFile && <span className="ml-auto text-xs whitespace-nowrap text-fg-muted">{chosen ? 'choisi' : 'choisir'}</span>}
              </button>
            </li>
          )
        })}
        {starts && listing.recent.length > 0 && (
          <li className="border-t border-border px-4 pt-4 pb-2 text-xs font-semibold tracking-[0.04em] text-fg-muted uppercase">
            Récents
          </li>
        )}
        {starts &&
          listing.recent.map((item) => {
            const isFile = item.kind === 'file' || item.kind === 'code'
            return (
              <li key={`recent:${item.path}`} className="border-t border-border">
                <button
                  type="button"
                  data-entry
                  className={ROW}
                  onClick={() => (isFile ? onOpen(parentOf(item.path), item.path) : onOpen(item.path))}
                >
                  {isFile ? <File className="size-5 shrink-0" aria-hidden="true" /> : <Folder className="size-5 shrink-0" aria-hidden="true" />}
                  <span className="font-mono">{basename(item.path)}</span>
                  <span className="min-w-0 truncate font-mono text-xs text-fg-muted">{item.path}</span>
                </button>
              </li>
            )
          })}
      </ul>
      {!starts && entries.length === 0 && (
        <EmptyState icon={FolderSearch} title={query ? 'Aucun nom ne correspond' : 'Rien à choisir ici'} className="m-4">
          <p>
            {query
              ? fr('Changer le filtre, ou analyser quand même ce dossier.')
              : fr(
                  'Ni sous-dossier, ni fichier de dépendances ou de code. On peut quand même analyser ce dossier : la recherche descend dans tous ses sous-dossiers.',
                )}
          </p>
        </EmptyState>
      )}
      {listing.truncated && (
        <p className="border-t border-border px-4 py-3 text-sm text-fg-muted" role="status">
          {fr('Liste coupée à 5 000 entrées : filtrer par nom, ou coller le chemin voulu.')}
        </p>
      )}
    </div>
  )
}

/** Le dossier d'un chemin POSIX : `C:/a/b` → `C:/a`, `C:/b` → `C:/`, `/b` → `/`. */
function parentOf(path: string): string {
  const cut = path.lastIndexOf('/')
  if (cut <= 0) return '/'
  const parent = path.slice(0, cut)
  return parent.endsWith(':') ? `${parent}/` : parent
}

/** Envoyer un fichier : la zone de dépôt, doublée du bouton « Choisir un fichier » (clavier). */
function UploadZone({ onFile, pending, prominent }: { onFile: (file: File) => void; pending: boolean; prominent: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed border-control p-5 text-center text-fg-muted">
      <Upload className="size-5" aria-hidden="true" />
      <p className="text-sm">
        Déposer un fichier n'importe où sur la page, ou le choisir. {UPLOAD_LIMITS}
      </p>
      <p className="text-sm">
        {fr(
          "Le fichier est envoyé seul : son lockfile voisin n'est pas lu, un fichier de code l'est par ses imports (ou son bloc PEP 723), et rien n'est écrit sur l'ordinateur.",
        )}
      </p>
      <input
        ref={input}
        type="file"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onFile(file)
          event.target.value = ''
        }}
      />
      <Button variant={prominent ? 'primary' : 'secondary'} disabled={pending} onClick={() => input.current?.click()}>
        {pending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <Upload aria-hidden="true" />}
        Choisir un fichier
      </Button>
    </div>
  )
}
