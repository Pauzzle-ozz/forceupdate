import { useWindowVirtualizer } from '@tanstack/react-virtual'
import { ArrowDown, ArrowUp, ArrowUpDown, FilterX, Search } from 'lucide-react'
import { useLayoutEffect, useRef, useState } from 'react'
import { cn } from 'cn'
import type { Report } from '@/api/types'
import { EmptyState } from '@/components/EmptyState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import {
  KINDS,
  KIND_LABEL,
  NO_FILTERS,
  ecosystems,
  type Directness,
  type Filters,
  type KindFilter,
  type Row,
  type Sort,
  type SortKey,
} from '@/lib/report'
import { Section } from '@/shell/Page'
import {
  ConstraintCell,
  FindingsCell,
  PackageMeta,
  SeverityCell,
  UpdateCell,
  UsedCell,
  shownCount,
} from './cells'

/** Au-delà, la liste est virtualisée (MASTER, « Tableau »). */
const VIRTUAL_FROM = 50

const DIRECTNESS: { value: Directness; label: string }[] = [
  { value: 'all', label: 'Toutes' },
  { value: 'direct', label: 'Directes' },
  { value: 'indirect', label: 'Indirectes' },
]

/**
 * Le tableau des dépendances (ECRANS.md, écran 4 ; pages/rapport.md) : filtrable, triable
 * (gravité par défaut, nom), le nom du paquet ouvre le détail. Sous 768 px, une vraie liste de
 * cartes (un tableau restylé en blocs perd sa sémantique).
 */
export function Dependencies({
  report,
  all,
  shown,
  filters,
  onFilters,
  sort,
  onSort,
  onOpen,
  sectionRef,
}: {
  report: Report
  all: Row[]
  shown: Row[]
  filters: Filters
  onFilters: (filters: Filters) => void
  sort: Sort
  onSort: (sort: Sort) => void
  onOpen: (row: Row) => void
  sectionRef: React.Ref<HTMLElement>
}) {
  const wide = useMediaQuery('(min-width: 768px)')
  const projects = report.projects.length > 1
  const present = ecosystems(report)
  const kinds = KINDS.filter((kind) => all.some((row) => row.findings.some((finding) => finding.kind === kind)))
  const filtered = shown.length !== all.length

  return (
    <Section aria-labelledby="deps-titre" ref={sectionRef} className="scroll-mt-(--header-h)">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="deps-titre" className="text-xl">
          Dépendances
        </h2>
        <p className="text-sm text-fg-muted" aria-live="polite">
          {shownCount(shown.length, all.length)}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2" role="search" aria-label="Filtrer les dépendances">
        <div className="relative max-w-80 min-w-0 flex-[1_1_220px]">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-fg-muted" aria-hidden="true" />
          <label htmlFor="filtre-nom" className="sr-only">
            Filtrer par nom
          </label>
          <Input
            id="filtre-nom"
            className="pl-9"
            placeholder="Filtrer par nom"
            value={filters.query}
            onChange={(event) => onFilters({ ...filters, query: event.target.value })}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div className="inline-flex overflow-hidden rounded-sm border border-control" role="group" aria-label="Directes ou indirectes">
          {DIRECTNESS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              aria-pressed={filters.directness === value}
              onClick={() => onFilters({ ...filters, directness: value })}
              className={cn(
                'min-h-[calc(var(--control-h)-2px)] border-control bg-surface px-3 text-sm text-fg-muted not-first:border-l',
                filters.directness === value && 'bg-primary-soft font-semibold text-link',
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {present.length > 1 && (
          <>
            <label htmlFor="filtre-eco" className="sr-only">
              Écosystème
            </label>
            <NativeSelect
              id="filtre-eco"
              value={filters.ecosystem}
              onChange={(event) => onFilters({ ...filters, ecosystem: event.target.value as Filters['ecosystem'] })}
            >
              <NativeSelectOption value="all">Tous les écosystèmes</NativeSelectOption>
              {present.map((ecosystem) => (
                <NativeSelectOption key={ecosystem} value={ecosystem}>
                  {ecosystem}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </>
        )}
        <label htmlFor="filtre-type" className="sr-only">
          Type de constat
        </label>
        <NativeSelect
          id="filtre-type"
          value={filters.kind}
          onChange={(event) => onFilters({ ...filters, kind: event.target.value as KindFilter })}
        >
          <NativeSelectOption value="all">Tous les constats</NativeSelectOption>
          {kinds.map((kind) => (
            <NativeSelectOption key={kind} value={kind}>
              {KIND_LABEL[kind]}
            </NativeSelectOption>
          ))}
          <NativeSelectOption value="none">Sans constat</NativeSelectOption>
        </NativeSelect>
        {projects && (
          <>
            <label htmlFor="filtre-projet" className="sr-only">
              Projet
            </label>
            <NativeSelect
              id="filtre-projet"
              value={filters.project}
              onChange={(event) => onFilters({ ...filters, project: event.target.value })}
            >
              <NativeSelectOption value="all">Tous les projets</NativeSelectOption>
              {report.projects.map((project) => (
                <NativeSelectOption key={project.path} value={project.path}>
                  {project.path}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </>
        )}
        {filtered && (
          <Button variant="ghost" size="sm" onClick={() => onFilters(NO_FILTERS)}>
            <FilterX aria-hidden="true" />
            Tout afficher
          </Button>
        )}
      </div>

      {shown.length === 0 ? (
        <EmptyState icon={FilterX} title="Aucune dépendance ne correspond" actions={
          <Button onClick={() => onFilters(NO_FILTERS)}>Tout afficher</Button>
        }>
          <p>Changer les filtres pour voir les autres dépendances.</p>
        </EmptyState>
      ) : wide ? (
        <DependencyTable report={report} rows={shown} projects={projects} sort={sort} onSort={onSort} onOpen={onOpen} />
      ) : (
        <DependencyCards report={report} rows={shown} projects={projects} sort={sort} onSort={onSort} onOpen={onOpen} />
      )}
    </Section>
  )
}

interface ListProps {
  report: Report
  rows: Row[]
  projects: boolean
  sort: Sort
  onSort: (sort: Sort) => void
  onOpen: (row: Row) => void
}

/** Les lignes visibles : toutes, ou, au-delà de 50, celles de la fenêtre (et les marges). */
function useVisible(rows: Row[], estimate: number) {
  const anchor = useRef<HTMLElement | null>(null)
  const [margin, setMargin] = useState(0)
  const virtual = rows.length > VIRTUAL_FROM
  useLayoutEffect(() => {
    if (virtual && anchor.current) setMargin(anchor.current.getBoundingClientRect().top + window.scrollY)
  }, [virtual, rows.length])
  // oxlint-disable-next-line react/incompatible-library -- rendu à chaque défilement, voulu
  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: () => estimate,
    overscan: 8,
    scrollMargin: margin,
    enabled: virtual,
  })
  if (!virtual) {
    return { anchor, virtualizer: null, items: rows.map((row, index) => ({ row, index })), before: 0, after: 0 }
  }
  const items = virtualizer.getVirtualItems()
  const before = items.length > 0 ? items[0].start - margin : 0
  const after = items.length > 0 ? virtualizer.getTotalSize() - (items[items.length - 1].end - margin) : 0
  return {
    anchor,
    virtualizer,
    items: items.map((item) => ({ row: rows[item.index], index: item.index })),
    before,
    after,
  }
}

function SortButton({
  label,
  column,
  sort,
  onSort,
}: {
  label: string
  column: SortKey
  sort: Sort
  onSort: (sort: Sort) => void
}) {
  const active = sort.key === column
  const Icon = !active ? ArrowUpDown : sort.descending ? ArrowDown : ArrowUp
  // Le premier clic : la gravité de la plus haute à la plus basse, le nom de A à Z.
  const next: Sort = active ? { key: column, descending: !sort.descending } : { key: column, descending: column === 'severity' }
  return (
    <button
      type="button"
      className="inline-flex min-h-6 items-center gap-1 uppercase pointer-coarse:min-h-11"
      onClick={() => onSort(next)}
    >
      {label}
      <Icon className="size-3.5" aria-hidden="true" />
    </button>
  )
}

function ariaSort(sort: Sort, column: SortKey): 'ascending' | 'descending' | undefined {
  if (sort.key !== column) return undefined
  // Gravité « décroissante » : de la plus haute à la plus basse.
  return sort.descending ? 'descending' : 'ascending'
}

function DependencyTable({ report, rows, projects, sort, onSort, onOpen }: ListProps) {
  const { anchor, virtualizer, items, before, after } = useVisible(rows, 64)
  const columns = projects ? 7 : 6
  return (
    <div ref={anchor as React.Ref<HTMLDivElement>}>
      <Table>
        <TableCaption className="sr-only">
          Dépendances {projects ? 'des projets' : 'du projet'}, triées par {sort.key === 'name' ? 'nom' : 'gravité'}
        </TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead scope="col" aria-sort={ariaSort(sort, 'name')}>
              <SortButton label="Paquet" column="name" sort={sort} onSort={onSort} />
            </TableHead>
            {projects && (
              <TableHead scope="col" className="max-lg:hidden">
                Projet
              </TableHead>
            )}
            <TableHead scope="col">Utilisée</TableHead>
            <TableHead scope="col">Contrainte</TableHead>
            <TableHead scope="col">Constats</TableHead>
            <TableHead scope="col" aria-sort={ariaSort(sort, 'severity')}>
              <SortButton label="Gravité" column="severity" sort={sort} onSort={onSort} />
            </TableHead>
            <TableHead scope="col">Mise à jour proposée</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {before > 0 && (
            <tr aria-hidden="true">
              {/* oxlint-disable-next-line jsx-a11y/control-has-associated-label -- marge de la liste virtualisée */}
              <td colSpan={columns} style={{ height: before }} />
            </tr>
          )}
          {items.map(({ row, index }) => (
            <TableRow key={row.key} data-index={index} ref={virtualizer?.measureElement}>
              <TableCell>
                <PackageButton row={row} onOpen={onOpen} />
                <PackageMeta row={row} project={projects} />
              </TableCell>
              {projects && (
                <TableCell className="max-lg:hidden">
                  <span className="font-mono text-sm">{row.project.path}</span>
                </TableCell>
              )}
              <TableCell>
                <UsedCell row={row} />
              </TableCell>
              <TableCell>
                <ConstraintCell row={row} />
              </TableCell>
              <TableCell>
                <FindingsCell row={row} report={report} />
              </TableCell>
              <TableCell>
                <SeverityCell row={row} />
              </TableCell>
              <TableCell>
                <UpdateCell row={row} />
              </TableCell>
            </TableRow>
          ))}
          {after > 0 && (
            <tr aria-hidden="true">
              {/* oxlint-disable-next-line jsx-a11y/control-has-associated-label -- marge de la liste virtualisée */}
              <td colSpan={columns} style={{ height: after }} />
            </tr>
          )}
        </TableBody>
      </Table>
    </div>
  )
}

/** Sous 768 px : une carte par dépendance, chaque valeur avec son libellé. */
function DependencyCards({ report, rows, projects, sort, onSort, onOpen }: ListProps) {
  const { anchor, virtualizer, items, before, after } = useVisible(rows, 220)
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-sm text-fg-muted">
        Trier par
        <Button
          size="sm"
          variant="ghost"
          aria-pressed={sort.key === 'severity'}
          onClick={() => onSort({ key: 'severity', descending: sort.key === 'severity' ? !sort.descending : true })}
        >
          gravité {sort.key === 'severity' && (sort.descending ? '(la plus haute d’abord)' : '(la plus basse d’abord)')}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          aria-pressed={sort.key === 'name'}
          onClick={() => onSort({ key: 'name', descending: sort.key === 'name' ? !sort.descending : false })}
        >
          nom {sort.key === 'name' && (sort.descending ? '(Z à A)' : '(A à Z)')}
        </Button>
      </div>
      <ul
        ref={anchor as React.Ref<HTMLUListElement>}
        className="rounded-md border border-border bg-surface"
        aria-label="Dépendances"
      >
        {before > 0 && <li aria-hidden="true" style={{ height: before }} />}
        {items.map(({ row, index }) => (
          <li
            key={row.key}
            data-index={index}
            ref={virtualizer?.measureElement}
            className="flex flex-col gap-2 border-border px-4 py-3 not-first:border-t"
          >
            <div>
              <PackageButton row={row} onOpen={onOpen} />
              <PackageMeta row={row} />
            </div>
            <dl className="grid grid-cols-[9.5em_minmax(0,1fr)] gap-x-2 gap-y-1.5 text-sm">
              {projects && <Field label="Projet"><span className="font-mono">{row.project.path}</span></Field>}
              <Field label="Utilisée">
                <UsedCell row={row} />
              </Field>
              <Field label="Contrainte">
                <ConstraintCell row={row} />
              </Field>
              <Field label="Constats">
                <FindingsCell row={row} report={report} />
              </Field>
              <Field label="Gravité">
                <SeverityCell row={row} />
              </Field>
              <Field label="Mise à jour">
                <UpdateCell row={row} />
              </Field>
            </dl>
          </li>
        ))}
        {after > 0 && <li aria-hidden="true" style={{ height: after }} />}
      </ul>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="pt-0.5 text-xs font-semibold tracking-[0.04em] text-fg-muted uppercase">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  )
}

/** Le nom du paquet : le bouton qui ouvre son détail (souligné en pointillé). */
function PackageButton({ row, onOpen }: { row: Row; onOpen: (row: Row) => void }) {
  return (
    <button
      type="button"
      className="text-left font-mono text-sm font-semibold break-all text-fg underline decoration-control decoration-dotted underline-offset-[3px] hover:decoration-current"
      onClick={() => onOpen(row)}
      aria-label={`${row.dependency.name}, voir le détail`}
    >
      {row.dependency.name}
    </button>
  )
}
