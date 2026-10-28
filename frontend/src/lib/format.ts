/**
 * Les règles françaises de l'interface (MASTER, « Typographie ») : dates par
 * Intl.DateTimeFormat("fr-FR"), durées relatives, virgule décimale, accord du nombre, espaces
 * insécables (U+00A0, comme dans les maquettes) posées par `fr` ; les messages de l'API
 * s'affichent tels quels.
 */

/** Espace insécable (U+00A0). */
export const NBSP = '\u00a0'

/**
 * Un texte de l'interface aux règles françaises : l'espace avant « : ; ! ? » et à l'intérieur
 * des guillemets devient insécable. Pas pour les messages de l'API, montrés tels quels.
 */
export function fr(text: string): string {
  return text.replace(/ ([:;!?»])/g, `${NBSP}$1`).replace(/« /g, `«${NBSP}`)
}

const dateFormat = new Intl.DateTimeFormat('fr-FR', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
})
const timeFormat = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' })
const numberFormat = new Intl.NumberFormat('fr-FR')
const relativeFormat = new Intl.RelativeTimeFormat('fr-FR', { numeric: 'auto' })

/** « 1 faille », « 28 failles » ; `plural` par défaut : le singulier suivi d'un « s ». */
export function count(n: number, singular: string, plural = `${singular}s`): string {
  return `${numberFormat.format(n)}${NBSP}${Math.abs(n) >= 2 ? plural : singular}`
}

/** Le mot seul, accordé : « élevée » / « élevées ». */
export function agree(n: number, singular: string, plural = `${singular}s`): string {
  return Math.abs(n) >= 2 ? plural : singular
}

export function formatNumber(n: number): string {
  return numberFormat.format(n)
}

/** « 28 oct. 2026 » */
export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso))
}

/** « 18:30 » */
export function formatTime(iso: string): string {
  return timeFormat.format(new Date(iso))
}

/** « 28 oct. 2026 à 18:30 » */
export function formatDateTime(iso: string): string {
  return `${formatDate(iso)} à ${formatTime(iso)}`
}

/** « 0,9 s », « 12 s », « 2 min 05 s ». */
export function formatDuration(ms: number): string {
  const seconds = Math.max(0, ms) / 1000
  if (seconds < 10) {
    return `${seconds.toLocaleString('fr-FR', { maximumFractionDigits: 1 })}${NBSP}s`
  }
  if (seconds < 60) return `${Math.round(seconds)}${NBSP}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes}${NBSP}min ${String(rest).padStart(2, '0')}${NBSP}s`
}

/** « il y a 2 h », « il y a 7 jours », « maintenant ». */
export function formatRelative(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
  ]
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return relativeFormat.format(Math.trunc(seconds / size), unit)
  }
  return 'maintenant'
}

/** Le dernier élément d'un chemin POSIX (`C:/Projets/demo` → `demo`) ; `C:/` reste `C:/`. */
export function basename(path: string): string {
  const trimmed = path.replace(/\/+$/, '')
  if (!trimmed.includes('/')) return path
  return trimmed.slice(trimmed.lastIndexOf('/') + 1)
}
