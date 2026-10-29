import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  CircleCheck,
  CircleHelp,
  ExternalLink,
  EyeOff,
  FilterX,
  Lock,
  OctagonAlert,
  RefreshCw,
  Search,
  ShieldAlert,
} from 'lucide-react'
import { useEffect, useId, useRef } from 'react'
import { Link } from 'react-router'
import { cn } from 'cn'
import type { RepositoryRow, RepositorySynthesis } from '@/api/types'
import { Blade } from '@/components/Blade'
import { EmptyState } from '@/components/EmptyState'
import { ForgeLogo } from '@/components/ForgeLogo'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/choice'
import { Input } from '@/components/ui/input'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { count, formatDateTime, formatRelative, fr } from '@/lib/format'
import {
  NO_REPOSITORY_FILTERS,
  STATE_FILTERS,
  forgesOf,
  owners,
  progressOf,
  repositoryKey,
  selectable,
  selectedUpdates,
  type RepositoryFilters,
  type RepositorySort,
  type RepositorySortKey,
} from '@/lib/repositories'
import { Section } from '@/shell/Page'

const FORGE_NAME = { github: 'GitHub', gitlab: 'GitLab', bitbucket: 'Bitbucket' } as const

interface ListProps {
  /** Tous les dépôts, et ceux que montrent les filtres et le tri. */
  all: RepositoryRow[]
  shown: RepositoryRow[]
  synthesis: RepositorySynthesis
  filters: RepositoryFilters
  onFilters: (filters: RepositoryFilters) => void
  sort: RepositorySort
  onSort: (sort: RepositorySort) => void
  selected: ReadonlySet<string>
  onSelect: (keys: string[], checked: boolean) => void
  onAnalyze: (rows: RepositoryRow[]) => void
  /** Pourquoi analyser n'est pas possible maintenant (hors ligne, en cours) ; `null` si ça l'est. */
  blocked: string | null
  pending: boolean
}

/**
 * La liste des dépôts (pages/depots.md, « Le tableau ») : filtres, tableau (une carte par dépôt
 * sous 768 px), cases à cocher et barre d'actions de la sélection.
 */
export function RepositoryList(props: ListProps) {
  const { all, shown, synthesis, filters, onFilters, selected, onSelect, onAnalyze, blocked, pending } = props
  const id = useId()
  const wide = useMediaQuery('(min-width: 768px)')
  const forges = forgesOf(all)
  const ownerList = owners(all)
  const filtered = filters.name !== '' || filters.forge !== 'all' || filters.owner !== 'all' || filters.state !== 'all'
  const picked = all.filter((row) => selected.has(repositoryKey(row)))
  const updates = selectedUpdates(all, selected)

  const masked = [
    synthesis.archived && count(synthesis.archived, 'archivé'),
    synthesis.forks && count(synthesis.forks, 'fork'),
    synthesis.empty && count(synthesis.empty, 'vide'),
  ].filter(Boolean)

  return (
    <Section aria-labelledby={`${id}-titre`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={`${id}-titre`} className="text-xl">
          Dépôts
        </h2>
        <p className="flex flex-wrap items-center gap-2 text-sm text-fg-muted">
          <span aria-live="polite">
            {count(shown.length, 'affiché', 'affichés')}
            {synthesis.hidden > 0 &&
              ` · ${count(synthesis.hidden, 'masqué', 'masqués')}${filters.hidden ? ' par défaut' : ''} (${masked.join(', ')})`}
          </span>
          {synthesis.hidden > 0 && (
            <Button variant="ghost" size="sm" aria-pressed={filters.hidden} onClick={() => onFilters({ ...filters, hidden: !filters.hidden })}>
              {filters.hidden ? 'Les masquer' : 'Les afficher'}
            </Button>
          )}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2" role="search" aria-label="Filtrer les dépôts">
        <div className="relative min-w-55 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-fg-muted" aria-hidden="true" />
          <label htmlFor={`${id}-nom`} className="sr-only">
            Filtrer par nom
          </label>
          <Input
            id={`${id}-nom`}
            className="pl-9"
            placeholder="Filtrer par nom"
            value={filters.name}
            onChange={(event) => onFilters({ ...filters, name: event.target.value })}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        {forges.length > 1 && (
          <>
            <label htmlFor={`${id}-forge`} className="sr-only">
              Forge
            </label>
            <NativeSelect
              id={`${id}-forge`}
              value={filters.forge}
              onChange={(event) => onFilters({ ...filters, forge: event.target.value as RepositoryFilters['forge'] })}
            >
              <NativeSelectOption value="all">Toutes les forges</NativeSelectOption>
              {forges.map((forge) => (
                <NativeSelectOption key={forge} value={forge}>
                  {FORGE_NAME[forge]}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </>
        )}
        {ownerList.length > 1 && (
          <>
            <label htmlFor={`${id}-proprietaire`} className="sr-only">
              Propriétaire
            </label>
            <NativeSelect
              id={`${id}-proprietaire`}
              value={filters.owner}
              onChange={(event) => onFilters({ ...filters, owner: event.target.value })}
            >
              <NativeSelectOption value="all">Tous les propriétaires</NativeSelectOption>
              {ownerList.map((owner) => (
                <NativeSelectOption key={owner} value={owner}>
                  {owner}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </>
        )}
        <label htmlFor={`${id}-etat`} className="sr-only">
          État
        </label>
        <NativeSelect
          id={`${id}-etat`}
          value={filters.state}
          onChange={(event) => onFilters({ ...filters, state: event.target.value as RepositoryFilters['state'] })}
        >
          {STATE_FILTERS.map(({ value, label }) => (
            <NativeSelectOption key={value} value={value}>
              {label}
            </NativeSelectOption>
          ))}
        </NativeSelect>
        {filtered && (
          <Button variant="ghost" size="sm" onClick={() => onFilters({ ...NO_REPOSITORY_FILTERS, hidden: filters.hidden })}>
            <FilterX aria-hidden="true" />
            Tout afficher
          </Button>
        )}
      </div>

      {shown.length === 0 ? (
        <EmptyState
          icon={FilterX}
          title="Aucun dépôt ne correspond"
          actions={<Button onClick={() => onFilters(NO_REPOSITORY_FILTERS)}>Tout afficher</Button>}
        >
          <p>Changer les filtres pour voir les autres dépôts.</p>
        </EmptyState>
      ) : wide ? (
        <RepositoryTable {...props} />
      ) : (
        <RepositoryCards {...props} />
      )}

      {picked.length > 0 && (
        <div
          role="region"
          aria-label="Actions sur la sélection"
          className="sticky bottom-4 z-20 flex flex-wrap items-center gap-3 rounded-md border border-control bg-surface px-4 py-3 shadow-raised max-sm:-mx-4 max-sm:bottom-0 max-sm:rounded-none max-sm:[&>button]:flex-auto"
        >
          <span className="grow text-sm">
            <b>{count(picked.length, 'dépôt sélectionné', 'dépôts sélectionnés')}</b>
            {updates > 0 && (
              <span className="text-fg-muted"> · {count(updates, 'mise à jour cochée par défaut', 'mises à jour cochées par défaut')}</span>
            )}
            {blocked && <span className="block text-fg-muted">{blocked}</span>}
          </span>
          <Button variant="ghost" onClick={() => onSelect(picked.map(repositoryKey), false)}>
            Tout désélectionner
          </Button>
          <Button variant="primary" onClick={() => onAnalyze(picked)} disabled={blocked !== null || pending}>
            <RefreshCw aria-hidden="true" />
            {picked.length >= 2 ? `Analyser ces ${picked.length} dépôts` : 'Analyser ce dépôt'}
          </Button>
        </div>
      )}
    </Section>
  )
}

/** La case de tête : aucune, quelques-unes (indéterminée) ou toutes les lignes affichées. */
function SelectAll({ shown, selected, onSelect }: Pick<ListProps, 'shown' | 'selected' | 'onSelect'>) {
  const box = useRef<HTMLInputElement>(null)
  const keys = shown.filter(selectable).map(repositoryKey)
  const checked = keys.filter((key) => selected.has(key)).length
  const all = keys.length > 0 && checked === keys.length
  useEffect(() => {
    if (box.current) box.current.indeterminate = checked > 0 && !all
  }, [checked, all])
  return (
    <Checkbox
      ref={box}
      checked={all}
      disabled={keys.length === 0}
      onChange={(event) => onSelect(keys, event.target.checked)}
      aria-label={`Tout sélectionner (${count(keys.length, 'dépôt affiché', 'dépôts affichés')})`}
    />
  )
}

function SortButton({ label, column, sort, onSort }: { label: string; column: RepositorySortKey; sort: RepositorySort; onSort: (sort: RepositorySort) => void }) {
  const active = sort.key === column
  const Icon = !active ? ArrowUpDown : sort.descending ? ArrowDown : ArrowUp
  // Le premier clic : le nom de A à Z, le dernier push du plus récent au plus ancien.
  const next: RepositorySort = active ? { key: column, descending: !sort.descending } : { key: column, descending: column === 'pushed' }
  return (
    <button
      type="button"
      className="inline-flex min-h-6 items-center gap-1 whitespace-nowrap uppercase pointer-coarse:min-h-11"
      onClick={() => onSort(next)}
    >
      {label}
      <Icon className="size-3.5" aria-hidden="true" />
    </button>
  )
}

function ariaSort(sort: RepositorySort, column: RepositorySortKey): 'ascending' | 'descending' | undefined {
  if (sort.key !== column) return undefined
  return sort.descending ? 'descending' : 'ascending'
}

function RepositoryTable({ shown, selected, onSelect, sort, onSort }: ListProps) {
  return (
    <Table>
      <TableCaption className="sr-only">
        Dépôts des comptes connectés, triés par {sort.key === 'name' ? 'nom' : 'dernier push'}
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col" className="w-10">
            <SelectAll shown={shown} selected={selected} onSelect={onSelect} />
          </TableHead>
          <TableHead scope="col" aria-sort={ariaSort(sort, 'name')}>
            <SortButton label="Dépôt" column="name" sort={sort} onSort={onSort} />
          </TableHead>
          <TableHead scope="col" className="max-lg:hidden">
            Forge
          </TableHead>
          <TableHead scope="col">Langages</TableHead>
          <TableHead scope="col" aria-sort={ariaSort(sort, 'pushed')}>
            <SortButton label="Dernier push" column="pushed" sort={sort} onSort={onSort} />
          </TableHead>
          <TableHead scope="col">Analyse</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {shown.map((row) => {
          const key = repositoryKey(row)
          const checked = selected.has(key)
          return (
            <TableRow key={key} className={cn(checked && 'bg-primary-soft [tbody_&]:hover:bg-primary-soft')}>
              <TableCell>
                <RowCheckbox row={row} checked={checked} onSelect={onSelect} />
              </TableCell>
              <TableCell>
                <RepositoryName row={row} />
                <span className="mt-1 flex items-center gap-1.5 text-xs text-fg-muted lg:hidden">
                  <ForgeLogo forge={row.forge} className="size-3.5" />
                  {FORGE_NAME[row.forge]}
                </span>
              </TableCell>
              <TableCell className="max-lg:hidden">
                <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                  <ForgeLogo forge={row.forge} className="size-4" />
                  {FORGE_NAME[row.forge]}
                </span>
              </TableCell>
              <TableCell>
                <Languages row={row} />
              </TableCell>
              <TableCell>
                <Pushed row={row} />
              </TableCell>
              <TableCell className="min-w-45">
                <Analysis row={row} />
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}

function RepositoryCards({ shown, selected, onSelect }: ListProps) {
  return (
    <>
      <div className="flex items-center gap-3 rounded-md border border-border bg-surface-2 px-4 py-2 text-sm">
        <SelectAll shown={shown} selected={selected} onSelect={onSelect} />
        <span className="text-fg-muted">Tout sélectionner</span>
      </div>
      <ul className="flex flex-col gap-3" aria-label="Dépôts des comptes connectés">
        {shown.map((row) => {
          const key = repositoryKey(row)
          const checked = selected.has(key)
          return (
            <li key={key} className={cn('rounded-md border border-border bg-surface p-4', checked && 'border-control bg-primary-soft')}>
              <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2">
                <RowCheckbox row={row} checked={checked} onSelect={onSelect} />
                <div className="flex min-w-0 flex-col gap-2">
                  <RepositoryName row={row} />
                  <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
                    <dt className="text-fg-muted">Forge</dt>
                    <dd className="flex items-center gap-1.5">
                      <ForgeLogo forge={row.forge} className="size-4" />
                      {FORGE_NAME[row.forge]}
                    </dd>
                    <dt className="text-fg-muted">Langages</dt>
                    <dd>
                      <Languages row={row} />
                    </dd>
                    <dt className="text-fg-muted">Dernier push</dt>
                    <dd>
                      <Pushed row={row} />
                    </dd>
                  </dl>
                  <Analysis row={row} />
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </>
  )
}

function RowCheckbox({ row, checked, onSelect }: { row: RepositoryRow; checked: boolean; onSelect: ListProps['onSelect'] }) {
  return (
    <Checkbox
      checked={checked}
      disabled={!selectable(row)}
      onChange={(event) => onSelect([repositoryKey(row)], event.target.checked)}
      aria-label={selectable(row) ? `Sélectionner ${row.full_name}` : `${row.full_name} : vide, rien à analyser`}
    />
  )
}

/** `owner/` atténué puis le nom, en chasse fixe ; le lien mène au rapport de la dernière analyse. */
function RepositoryName({ row }: { row: RepositoryRow }) {
  const name = (
    <>
      <span className="font-normal text-fg-muted">{row.owner}/</span>
      {row.name}
    </>
  )
  const forge = FORGE_NAME[row.forge]
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      {row.scan ? (
        <Link to={`/analyses/${row.scan.id}`} className="font-mono text-sm font-semibold break-all text-fg">
          {name}
        </Link>
      ) : (
        <span className="font-mono text-sm font-semibold break-all">{name}</span>
      )}
      <span className="inline-flex items-center gap-1">
        {row.private && (
          <span role="img" aria-label="privé" title="privé" className="inline-flex text-fg-muted">
            <Lock className="size-4" aria-hidden="true" />
          </span>
        )}
        <a
          href={row.url}
          target="_blank"
          rel="noreferrer"
          aria-label={`Ouvrir ${row.full_name} sur ${forge} (nouvel onglet)`}
          title={`Ouvrir sur ${forge}`}
          className="inline-flex size-6 items-center justify-center rounded-xs text-fg-muted hover:text-fg pointer-coarse:size-11"
        >
          <ExternalLink className="size-3.5" aria-hidden="true" />
        </a>
      </span>
      {row.archived && <Badge variant="neutral">archivé</Badge>}
      {row.fork && <Badge variant="neutral">fork</Badge>}
      {row.empty && <Badge variant="neutral">vide</Badge>}
    </span>
  )
}

function Languages({ row }: { row: RepositoryRow }) {
  if (row.languages.length === 0) return <span className="text-sm text-fg-muted">—</span>
  return <span className="text-sm">{row.languages.slice(0, 3).join(', ')}</span>
}

function Pushed({ row }: { row: RepositoryRow }) {
  if (!row.pushed_at) return <span className="text-sm text-fg-muted">—</span>
  return (
    <time dateTime={row.pushed_at} title={formatDateTime(row.pushed_at)} className="text-sm whitespace-nowrap">
      {formatRelative(row.pushed_at)}
    </time>
  )
}

const SKIPPED_TEXT: Record<string, string> = {
  vide: 'vide : rien à analyser',
  archivé: 'archivé : pas analysé par défaut',
  fork: 'fork : pas analysé par défaut',
}

/** L'état de la dernière analyse : ses chiffres, sa progression, ou pourquoi il n'y en a pas. */
export function Analysis({ row }: { row: RepositoryRow }) {
  const readOnly = !row.can_push && (
    <Badge variant="neutral">
      <EyeOff aria-hidden="true" />
      lecture seule
    </Badge>
  )
  switch (row.state) {
    case 'running': {
      const progress = progressOf(row.scan)
      // En attente de son tour : rien n'avance encore, pas de lame.
      if (!row.scan?.progress) return <span className="text-sm text-fg-muted">{progress.text}</span>
      return (
        <div className="flex min-w-40 flex-col gap-1">
          <span className="text-sm text-fg-muted">{progress.text}</span>
          <Blade label={`Analyse de ${row.full_name}`} value={progress.value} max={progress.max} />
        </div>
      )
    }
    case 'to_update': {
      const counts = row.counts
      if (!counts) return null
      const worst = counts.worst === 'critical' ? 'high' : (counts.worst ?? 'high')
      return (
        <div className="flex flex-wrap items-center gap-1.5">
          {counts.critical > 0 && (
            <Badge variant="critical">
              <OctagonAlert aria-hidden="true" />
              {count(counts.critical, 'critique')}
            </Badge>
          )}
          {counts.vulnerabilities > 0 && (
            <Badge variant={worst}>
              <ShieldAlert aria-hidden="true" />
              {count(counts.vulnerabilities, 'faille')}
            </Badge>
          )}
          <Badge variant="outline">{count(counts.to_update, 'à mettre à jour', 'à mettre à jour')}</Badge>
          {counts.inconclusive > 0 && (
            <Badge variant="inconclusive">
              <CircleHelp aria-hidden="true" />
              {count(counts.inconclusive, 'non concluant')}
            </Badge>
          )}
          {readOnly}
        </div>
      )
    }
    case 'up_to_date':
      return (
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="success">
            <CircleCheck aria-hidden="true" />
            à jour
          </Badge>
          {readOnly}
        </div>
      )
    case 'no_dependencies':
      return <span className="text-sm text-fg-muted">aucun fichier de dépendances</span>
    case 'inconclusive':
      return (
        <div className="flex flex-col items-start gap-1">
          <Badge variant="inconclusive">
            <CircleHelp aria-hidden="true" />
            non concluant
          </Badge>
          {row.reason && <span className="text-sm text-fg-muted">{row.reason}</span>}
        </div>
      )
    case 'skipped':
      return (
        <Badge variant="neutral">{fr(`sauté : ${SKIPPED_TEXT[row.reason ?? ''] ?? row.reason ?? 'pas analysé'}`)}</Badge>
      )
    default:
      return (
        <div className="flex flex-col items-start gap-1">
          <Badge variant="neutral">pas encore analysé</Badge>
          {row.reason && <span className="text-sm text-fg-muted">{row.reason}</span>}
        </div>
      )
  }
}
