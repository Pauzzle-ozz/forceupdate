/**
 * Les déductions d'affichage de l'écran 8 (PR / MR) : le numéro tel que l'écrit la forge, l'étape
 * d'un envoi en mots, ce qui est coché, où en est l'envoi. Ce que chaque PR fera, ce qui est
 * sauté et pourquoi, et ce qui s'est passé viennent du serveur (`/api/proposals`).
 */
import type {
  ChangeRequest,
  ForgeKind,
  Proposal,
  ProposedRepository,
  ProposedState,
  RepositoryKey,
} from '@/api/types'
import { count, fr } from '@/lib/format'

export const FORGE_NAME: Record<ForgeKind, string> = { github: 'GitHub', gitlab: 'GitLab', bitbucket: 'Bitbucket' }

/** L'hôte du service en ligne de chaque forge ; un autre hôte est une instance auto-hébergée. */
export const FORGE_HOST: Record<ForgeKind, string> = {
  github: 'github.com',
  gitlab: 'gitlab.com',
  bitbucket: 'bitbucket.org',
}

/** « GitLab », ou « GitLab (gitlab.example.com) » pour une instance auto-hébergée. */
export function forgeLabel(forge: ForgeKind, host: string): string {
  return host === FORGE_HOST[forge] ? FORGE_NAME[forge] : `${FORGE_NAME[forge]} (${host})`
}

/** « PR » ; « MR » sur GitLab. */
export function requestWord(forge: ForgeKind): string {
  return forge === 'gitlab' ? 'MR' : 'PR'
}

/** « PR », « MR », ou « PR et MR » : le nom de ce qu'on propose sur ces forges. */
export function requestWords(forges: Iterable<ForgeKind>): string {
  const words = new Set([...forges].map(requestWord))
  if (words.size === 0) return 'PR'
  return ['PR', 'MR'].filter((word) => words.has(word)).join(' et ')
}

/** « 2 PR et 1 MR », « 1 PR » : combien il y en a, pour ces dépôts. */
export function requestCount(forges: ForgeKind[]): string {
  const pr = forges.filter((forge) => requestWord(forge) === 'PR').length
  const mr = forges.length - pr
  return [pr && `${pr} PR`, mr && `${mr} MR`].filter(Boolean).join(' et ') || '0 PR'
}

/** Le numéro tel que l'écrit la forge : `#41` (GitHub, Bitbucket), `!12` (GitLab). */
export function requestNumber(forge: ForgeKind, request: Pick<ChangeRequest, 'number'>): string {
  return `${forge === 'gitlab' ? '!' : '#'}${request.number}`
}

/** La clé d'un dépôt d'un compte : `github:github.com/owner/nom`. */
export function keyText(key: RepositoryKey): string {
  return `${key.forge}:${key.host}/${key.full_name}`
}

/** Un dépôt désigné par sa forge, l'hôte de son compte et son nom. */
export function keyOf(item: RepositoryKey): RepositoryKey {
  return { forge: item.forge, host: item.host, full_name: item.full_name }
}

/** L'adresse de l'écran 8 pour préparer les PR (MR sur GitLab) de ces dépôts. */
export function proposalPath(keys: RepositoryKey[]): string {
  return `/pr?${new URLSearchParams({ depots: keys.map(keyText).join(',') })}`
}

const FORGES: ForgeKind[] = ['github', 'gitlab', 'bitbucket']

/** Les dépôts demandés par l'adresse de l'écran 8 (`?depots=github:github.com/a/b,gitlab:…`). */
export function requestedRepositories(params: URLSearchParams): RepositoryKey[] | null {
  const found = new Map<string, RepositoryKey>()
  for (const text of (params.get('depots') ?? '').split(',')) {
    const match = /^([a-z]+):([^/\s]+)\/(\S+\/\S+)$/.exec(text.trim())
    if (!match || !FORGES.includes(match[1] as ForgeKind)) continue
    const key = { forge: match[1] as ForgeKind, host: match[2], full_name: match[3] }
    found.set(keyText(key).toLowerCase(), key)
  }
  return found.size > 0 ? [...found.values()] : null
}

/** Les dépôts cochés par défaut : prêts, à l'analyse concluante (le serveur le dit). */
export function defaultChecked(proposal: Proposal): Set<string> {
  return new Set(proposal.repositories.filter((item) => item.checked).map(keyText))
}

export function ready(proposal: Proposal): ProposedRepository[] {
  return proposal.repositories.filter((item) => item.state === 'ready')
}

const SENT: ProposedState[] = ['waiting', 'sending', 'opened', 'updated', 'nothing', 'failed']
const FINISHED: ProposedState[] = ['opened', 'updated', 'nothing', 'failed']

/** Les dépôts envoyés (en attente, en cours ou finis). */
export function sent(proposal: Proposal): ProposedRepository[] {
  return proposal.repositories.filter((item) => SENT.includes(item.state))
}

export function finished(item: ProposedRepository): boolean {
  return FINISHED.includes(item.state)
}

/** Ce que fait un dépôt en cours d'envoi, en mots. */
export function stepText(item: ProposedRepository): string {
  const word = requestWord(item.forge)
  switch (item.step) {
    case 'cloning':
      return 'clone superficiel de la branche par défaut'
    case 'updating':
      if (item.progress?.kind === 'regenerating' && item.progress.name) {
        return fr(`régénération de ${item.progress.name} (${item.progress.done + 1} sur ${item.progress.total})`)
      }
      return 'réécriture des manifestes et régénération des lockfiles'
    case 'pushing':
      return `push de la branche ${item.branch}`
    case 'requesting':
      return `ouverture ou mise à jour de la ${word}`
    default:
      return 'en cours'
  }
}

/** Une mise à jour que l'outil de lockfile a laissée sous la version choisie. */
export interface HeldUpdate {
  /** La clé de la mise à jour (`backend|npm|minimatch|10.2.6`). */
  update: string
  name: string
  /** Le projet, `.` pour la racine. */
  project: string
  /** La version choisie. */
  chosen: string
  /** Les versions restées dans le lockfile. */
  versions: string[]
  /** Les paquets qui la retiennent (`nodemon 3.1.14`) ; vide si l'outil ne le dit pas. */
  heldBy: string[]
}

/**
 * Les mises à jour d'un dépôt envoyé que l'outil de lockfile n'a pas pu faire : une indirecte
 * hors de la plage que demande le paquet qui la tire (`nodemon` demande `minimatch ^10.2.1`, la
 * correction est en 11.0.1) reste où elle est.
 */
export function heldUpdates(item: ProposedRepository): HeldUpdate[] {
  // Un paquet à plusieurs versions installées (deux minimatch indirectes) donne une mise à jour
  // par version, mais une seule ligne : les mêmes versions restent, retenues par les uns ou les
  // autres.
  const found = new Map<string, HeldUpdate>()
  for (const installed of item.results.flatMap((result) => result.installed)) {
    if (installed.reach !== 'below') continue
    const applied = item.applied.find((update) => update.update === installed.update)
    const held = {
      update: installed.update,
      name: applied?.name ?? installed.update,
      project: applied?.project ?? '.',
      chosen: applied?.version ?? installed.version,
      versions: installed.versions,
      heldBy: installed.held_by,
    }
    const key = `${held.project}|${held.name}|${held.chosen}`
    const known = found.get(key)
    found.set(
      key,
      known
        ? { ...known, versions: [...new Set([...known.versions, ...held.versions])], heldBy: [...new Set([...known.heldBy, ...held.heldBy])] }
        : held,
    )
  }
  return [...found.values()]
}

/** Une majeure que l'outil de lockfile refusait, retirée pour que le reste parte (session 37). */
export interface DroppedUpdate {
  update: string
  name: string
  project: string
  version: string
  /** Ce qu'en dit l'outil (en anglais, le plus souvent). */
  reason: string
  /** Le lockfile. */
  lockfile: string
  /** L'outil qui le régénère (« uv pip compile ») ; `null` s'il n'est pas dans le récapitulatif. */
  tool: string | null
}

/** Les majeures d'un dépôt envoyé que l'outil de lockfile refusait : remises comme avant. */
export function droppedUpdates(item: ProposedRepository): DroppedUpdate[] {
  return item.results.flatMap((result) =>
    result.dropped.map((dropped) => {
      const applied = item.applied.find((update) => update.update === dropped.update)
      return {
        update: dropped.update,
        name: applied?.name ?? dropped.update,
        project: applied?.project ?? '.',
        version: dropped.version,
        reason: dropped.reason,
        lockfile: result.lockfile,
        tool: item.lockfiles.find((job) => job.lockfile === result.lockfile)?.tool ?? null,
      }
    }),
  )
}

/** Rien de poussé parce que toutes les mises à jour ont été retenues : il y avait à faire. */
function allHeld(item: ProposedRepository): boolean {
  return item.state === 'nothing' && heldUpdates(item).length > 0
}

/** Ce qu'il est advenu d'un dépôt envoyé, en une phrase (sans l'erreur, dite à part). */
export function outcomeText(item: ProposedRepository): string {
  const word = requestWord(item.forge)
  const number = item.request ? ` ${requestNumber(item.forge, item.request)}` : ''
  switch (item.state) {
    case 'waiting':
      return 'en attente de son tour'
    case 'sending':
      return stepText(item)
    case 'opened':
      return `${word}${number} ouverte`
    case 'updated':
      return item.pushed
        ? `${word}${number} mise à jour`
        : fr(`${word}${number} mise à jour : elle avait déjà ces changements, rien n'est poussé, sa description est refaite`)
    case 'nothing':
      return allHeld(item)
        ? fr("aucune mise à jour n'a pu se faire : d'autres paquets retiennent les versions choisies ; rien n'est poussé")
        : fr("rien à faire sur la branche par défaut telle qu'elle est : rien n'est poussé")
    case 'failed':
      return `pas de ${word}`
    default:
      return ''
  }
}

/** « 3 PR ouvertes · 1 MR ouverte · 1 mise à jour · 1 en échec ». */
export function resultSummary(proposal: Proposal): string {
  const items = sent(proposal)
  const by = (state: ProposedState) => items.filter((item) => item.state === state).length
  const opened = (word: string) =>
    items.filter((item) => item.state === 'opened' && requestWord(item.forge) === word).length
  const held = items.filter(allHeld).length
  return [
    ...['PR', 'MR'].map((word) => opened(word) && `${opened(word)} ${word} ${opened(word) >= 2 ? 'ouvertes' : 'ouverte'}`),
    by('updated') && `${by('updated')} ${by('updated') >= 2 ? 'mises à jour' : 'mise à jour'}`,
    held && `${count(held, 'dépôt')} aux mises à jour retenues`,
    by('nothing') - held && `${count(by('nothing') - held, 'dépôt')} sans rien à faire`,
    by('failed') && `${by('failed')} en échec`,
  ]
    .filter(Boolean)
    .join(' · ')
}
