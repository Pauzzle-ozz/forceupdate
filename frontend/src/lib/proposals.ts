/**
 * Les déductions d'affichage de l'écran 8 (PR / MR) : le numéro tel que l'écrit la forge, l'étape
 * d'un envoi en mots, ce qui est coché, où en est l'envoi. Ce que chaque PR fera, ce qui est
 * sauté et pourquoi, et ce qui s'est passé viennent du serveur (`/api/proposals`).
 */
import type { ChangeRequest, ForgeKind, Proposal, ProposedRepository, ProposedState } from '@/api/types'
import { count, fr } from '@/lib/format'

export const FORGE_NAME: Record<ForgeKind, string> = { github: 'GitHub', gitlab: 'GitLab', bitbucket: 'Bitbucket' }

/** « PR » ; « MR » sur GitLab. */
export function requestWord(forge: ForgeKind): string {
  return forge === 'gitlab' ? 'MR' : 'PR'
}

/** Le numéro tel que l'écrit la forge : `#41` (GitHub, Bitbucket), `!12` (GitLab). */
export function requestNumber(forge: ForgeKind, request: Pick<ChangeRequest, 'number'>): string {
  return `${forge === 'gitlab' ? '!' : '#'}${request.number}`
}

/** L'adresse de l'écran 8 pour préparer les PR de ces dépôts d'une forge. */
export function proposalPath(forge: ForgeKind, names: string[]): string {
  return `/pr?${new URLSearchParams({ forge, depots: names.join(',') })}`
}

/** Les dépôts demandés par l'adresse de l'écran 8 (`?forge=github&depots=a/b,c/d`). */
export function requestedRepositories(params: URLSearchParams): { forge: ForgeKind; names: string[] } | null {
  const forge = params.get('forge')
  const names = (params.get('depots') ?? '')
    .split(',')
    .map((name) => name.trim())
    .filter(Boolean)
  if (!forge || !['github', 'gitlab', 'bitbucket'].includes(forge) || names.length === 0) return null
  return { forge: forge as ForgeKind, names: [...new Set(names)] }
}

/** Les dépôts cochés par défaut : prêts, à l'analyse concluante (le serveur le dit). */
export function defaultChecked(proposal: Proposal): Set<string> {
  return new Set(proposal.repositories.filter((item) => item.checked).map((item) => item.full_name))
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
      return fr("rien à faire sur la branche par défaut telle qu'elle est : rien n'est poussé")
    case 'failed':
      return `pas de ${word}`
    default:
      return ''
  }
}

/** « 3 PR ouvertes · 1 mise à jour · 1 en échec ». */
export function resultSummary(proposal: Proposal): string {
  const items = sent(proposal)
  const word = requestWord(proposal.forge)
  const by = (state: ProposedState) => items.filter((item) => item.state === state).length
  return [
    by('opened') && `${by('opened')} ${word} ${by('opened') >= 2 ? 'ouvertes' : 'ouverte'}`,
    by('updated') && `${by('updated')} ${by('updated') >= 2 ? 'mises à jour' : 'mise à jour'}`,
    by('nothing') && `${count(by('nothing'), 'dépôt')} sans rien à faire`,
    by('failed') && `${by('failed')} en échec`,
  ]
    .filter(Boolean)
    .join(' · ')
}
