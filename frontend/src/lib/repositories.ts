/**
 * Les déductions d'affichage de l'écran 7 (Mes dépôts) : filtrer, trier, sélectionner, dire où en
 * est une analyse. L'état de chaque dépôt, ses chiffres et la synthèse viennent du serveur
 * (`GET /api/repositories`) : rien n'est recompté ici, sinon le nombre de mises à jour cochées
 * de la sélection (la somme de celles que le serveur donne pour chaque dépôt).
 */
import type { ForgeKind, RateLimit, RepositoryKey, RepositoryRow, ScanSummary } from '@/api/types'
import { count, formatNumber, formatTime, fr } from '@/lib/format'
import { forgeLabel, keyOf, keyText } from '@/lib/proposals'

export type StateFilter = 'all' | 'to_update' | 'vulnerable' | 'up_to_date' | 'inconclusive' | 'not_scanned'

export interface RepositoryFilters {
  name: string
  forge: 'all' | ForgeKind
  owner: 'all' | string
  state: StateFilter
  /** Montrer aussi les archivés, les forks et les vides. */
  hidden: boolean
}

export const NO_REPOSITORY_FILTERS: RepositoryFilters = {
  name: '',
  forge: 'all',
  owner: 'all',
  state: 'all',
  hidden: false,
}

export const STATE_FILTERS: { value: StateFilter; label: string }[] = [
  { value: 'all', label: 'Tous les états' },
  { value: 'to_update', label: 'À mettre à jour' },
  { value: 'vulnerable', label: 'Avec des failles' },
  { value: 'up_to_date', label: 'À jour' },
  { value: 'inconclusive', label: 'Non concluants' },
  { value: 'not_scanned', label: 'Pas encore analysés' },
]

export type RepositorySortKey = 'name' | 'pushed'

export interface RepositorySort {
  key: RepositorySortKey
  descending: boolean
}

export const DEFAULT_REPOSITORY_SORT: RepositorySort = { key: 'name', descending: false }

/** La clé d'un dépôt : sa forge, l'hôte de son compte, son nom (`gitlab:gitlab.com/g/projet`). */
export function repositoryKey(row: Pick<RepositoryRow, 'forge' | 'host' | 'full_name'>): string {
  return keyText(row)
}

function matchesState(row: RepositoryRow, state: StateFilter): boolean {
  switch (state) {
    case 'all':
      return true
    case 'vulnerable':
      return (row.counts?.vulnerabilities ?? 0) > 0
    case 'not_scanned':
      return row.state === 'not_scanned' || row.state === 'skipped'
    default:
      return row.state === state
  }
}

export function filterRepositories(rows: RepositoryRow[], filters: RepositoryFilters): RepositoryRow[] {
  const name = filters.name.trim().toLowerCase()
  return rows.filter(
    (row) =>
      (filters.hidden || !row.hidden) &&
      (!name || row.full_name.toLowerCase().includes(name)) &&
      (filters.forge === 'all' || row.forge === filters.forge) &&
      (filters.owner === 'all' || row.owner === filters.owner) &&
      matchesState(row, filters.state),
  )
}

export function sortRepositories(rows: RepositoryRow[], sort: RepositorySort): RepositoryRow[] {
  const sign = sort.descending ? -1 : 1
  const byName = (a: RepositoryRow, b: RepositoryRow) =>
    a.full_name.localeCompare(b.full_name, 'fr', { sensitivity: 'base' })
  return [...rows].sort((a, b) => {
    if (sort.key === 'pushed') {
      // Jamais poussé : en dernier, dans les deux sens.
      const one = a.pushed_at ? new Date(a.pushed_at).getTime() : null
      const other = b.pushed_at ? new Date(b.pushed_at).getTime() : null
      if (one !== other) {
        if (one === null) return 1
        if (other === null) return -1
        return sign * (one - other)
      }
      return byName(a, b)
    }
    return sign * byName(a, b)
  })
}

/** Les propriétaires des dépôts (comptes, organisations), par nom. */
export function owners(rows: RepositoryRow[]): string[] {
  return [...new Set(rows.map((row) => row.owner))].sort((a, b) => a.localeCompare(b, 'fr', { sensitivity: 'base' }))
}

export function forgesOf(rows: RepositoryRow[]): ForgeKind[] {
  return [...new Set(rows.map((row) => row.forge))]
}

/** Les noms que portent plusieurs dépôts (le même `owner/nom` sur GitHub et sur GitLab). */
export function twinNames(rows: RepositoryRow[]): Set<string> {
  const seen = new Set<string>()
  const twins = new Set<string>()
  for (const row of rows) {
    const name = row.full_name.toLowerCase()
    if (seen.has(name)) twins.add(name)
    seen.add(name)
  }
  return twins
}

/** Le nom d'un dépôt à dire (lecteurs d'écran) : avec sa forge, si un autre porte le même. */
export function spokenName(row: RepositoryRow, twins: ReadonlySet<string>): string {
  return twins.has(row.full_name.toLowerCase()) ? `${row.full_name} (${forgeLabel(row.forge, row.host)})` : row.full_name
}

/** Un dépôt vide n'a rien à analyser : il ne se coche pas. */
export function selectable(row: RepositoryRow): boolean {
  return !row.empty
}

/** Les mises à jour cochées par défaut dans les dépôts sélectionnés (déjà analysés). */
export function selectedUpdates(rows: RepositoryRow[], selected: ReadonlySet<string>): number {
  return rows.reduce((total, row) => total + (selected.has(repositoryKey(row)) ? (row.counts?.updates ?? 0) : 0), 0)
}

/** Les dépôts, comme les désigne l'API (une analyse groupée, un récapitulatif). */
export function keysOf(rows: RepositoryRow[]): RepositoryKey[] {
  return rows.map(keyOf)
}

export interface Progress {
  /** Où en est l'analyse, en mots. */
  text: string
  value?: number
  max?: number
}

/** Où en est l'analyse d'un dépôt, d'après son dernier événement. */
export function progressOf(scan: ScanSummary | null): Progress {
  const event = scan?.progress
  if (!event) return { text: 'en attente de son tour' }
  if (event.kind === 'downloading') {
    return { text: fr(`téléchargement : ${event.done} sur ${count(event.total, 'fichier')}`), value: event.done, max: event.total }
  }
  if (event.kind === 'cloning') return { text: 'clone superficiel (arborescence tronquée)' }
  if (['checking', 'package_checked', 'vulnerabilities_checked'].includes(event.kind) && event.total > 0) {
    return { text: `${event.done} sur ${count(event.total, 'vérification')}`, value: event.done, max: event.total }
  }
  return { text: 'lecture des fichiers' }
}

/** « API GitHub : 4 210 requêtes restantes sur 5 000, remise à zéro à 19:00 ». */
export function rateText(rate: RateLimit, forge: string): string {
  return fr(
    `API ${forge} : ${formatNumber(rate.remaining)} ${rate.remaining >= 2 ? 'requêtes restantes' : 'requête restante'} sur ${formatNumber(rate.limit)}, remise à zéro à ${formatTime(rate.reset_at)}`,
  )
}

/** Moins de 10 % des requêtes restent : à dire en avertissement. */
export function rateLow(rate: RateLimit): boolean {
  return rate.remaining < rate.limit * 0.1
}
