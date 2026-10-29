/**
 * Les appels à l'API du serveur local (docs/JSON_FORMAT.md, « L'API de l'interface web »).
 *
 * Le jeton de session voyage dans le cookie posé par l'adresse d'entrée : le navigateur le
 * joint tout seul (même origine). Chaque réponse dit aussi où en est la liaison avec le
 * serveur (`connection`) : une erreur réseau, c'est le serveur arrêté ; un 401, la session
 * terminée (le serveur a redémarré, son jeton a changé). La coquille en fait des bandeaux.
 */
import type {
  Account,
  AccountConnection,
  AccountList,
  ApplyRequest,
  BatchRequest,
  Disconnection,
  ForgeKind,
  Listing,
  PlanRequest,
  Proposal,
  ProposalRequest,
  RepositoryBatch,
  RepositoryKey,
  RepositoryList,
  RepositoryRequest,
  ScanDetail,
  ScanRequest,
  ScanSummary,
  UpdatePlan,
} from './types'

export type Connection = 'ok' | 'down' | 'session'

let connection: Connection = 'ok'
const listeners = new Set<() => void>()

export const connectionStore = {
  get: (): Connection => connection,
  set(next: Connection) {
    if (next === connection) return
    connection = next
    for (const listener of listeners) listener()
  },
  subscribe(listener: () => void) {
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
}

/** Une réponse d'erreur de l'API : `detail` est la phrase en français qu'elle donne. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Le serveur ne répond pas (arrêté, sans doute). */
export class ServerDownError extends Error {
  constructor() {
    super('Le serveur local ne répond pas.')
    this.name = 'ServerDownError'
  }
}

async function request<T>(method: string, url: string, init: RequestInit = {}): Promise<T> {
  let response: globalThis.Response
  try {
    response = await fetch(url, { method, credentials: 'same-origin', ...init })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    connectionStore.set('down')
    throw new ServerDownError()
  }
  if (response.status === 401) {
    connectionStore.set('session')
    throw new ApiError(401, 'Session terminée : le serveur a redémarré.')
  }
  connectionStore.set('ok')
  if (!response.ok) throw new ApiError(response.status, await detail(response))
  return (await response.json()) as T
}

async function detail(response: globalThis.Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
      return body.detail
    }
  } catch {
    // pas du JSON
  }
  return `Le serveur a répondu ${response.status}.`
}

/** `?host=…` pour un compte d'une instance auto-hébergée ; rien pour le service en ligne. */
function hostQuery(host: string | undefined): string {
  return host ? `?${new URLSearchParams({ host })}` : ''
}

function json(body: unknown): RequestInit {
  return { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

export const api = {
  /** Le contenu d'un dossier ; sans chemin, les points de départ (dossier personnel, lecteurs). */
  listFolder: (path?: string | null) =>
    request<Listing>('GET', path ? `/api/fs?${new URLSearchParams({ path })}` : '/api/fs'),

  startScan: (body: ScanRequest) => request<ScanSummary>('POST', '/api/scans', json(body)),

  listScans: () => request<ScanSummary[]>('GET', '/api/scans'),

  getScan: (id: string) => request<ScanDetail>('GET', `/api/scans/${encodeURIComponent(id)}`),

  cancelScan: (id: string) =>
    request<ScanSummary>('DELETE', `/api/scans/${encodeURIComponent(id)}`),

  /** Envoie un fichier (glisser-déposer, « Choisir un fichier ») : son contenu en corps brut. */
  uploadFile: (file: File) =>
    request<ScanSummary>('POST', `/api/files?${new URLSearchParams({ name: file.name })}`, {
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    }),

  scanEventsUrl: (id: string) => `/api/scans/${encodeURIComponent(id)}/events`,

  /** Prépare une sélection, sans rien écrire : diffs, lockfiles, garde-fou git. */
  planUpdate: (body: PlanRequest) => request<UpdatePlan>('POST', '/api/updates/plan', json(body)),

  /** Applique un plan, en tâche de fond ; `force` passe outre le garde-fou git. */
  applyUpdate: (body: ApplyRequest) => request<UpdatePlan>('POST', '/api/updates/apply', json(body)),

  getPlan: (id: string) => request<UpdatePlan>('GET', `/api/updates/${encodeURIComponent(id)}`),

  planEventsUrl: (id: string) => `/api/updates/${encodeURIComponent(id)}/events`,

  /** Un fichier tel que le plan le réécrit (fichier envoyé : sa version mise à jour). */
  planFileUrl: (id: string, path: string) =>
    `/api/updates/${encodeURIComponent(id)}/files/${path.split('/').map(encodeURIComponent).join('/')}`,

  /** Les forges, comment s'y connecter, et les comptes connectés (jamais leur token). */
  listAccounts: () => request<AccountList>('GET', '/api/accounts'),

  /** Commence une connexion par la page d'autorisation de la forge (aller à `authorize_url`). */
  startOAuth: (forge: ForgeKind) => request<AccountConnection>('POST', `/api/accounts/${forge}/oauth`),

  /** Commence une connexion par device flow : un code à taper sur la forge. */
  startDevice: (forge: ForgeKind) => request<AccountConnection>('POST', `/api/accounts/${forge}/device`),

  getConnection: (id: string) =>
    request<AccountConnection>('GET', `/api/accounts/connections/${encodeURIComponent(id)}`),

  cancelConnection: (id: string) =>
    request<AccountConnection>('DELETE', `/api/accounts/connections/${encodeURIComponent(id)}`),

  /** Connecte un compte avec un token collé : envoyé au serveur, jamais renvoyé. */
  connectToken: (forge: ForgeKind, token: string, url: string | null = null) =>
    request<Account>('POST', `/api/accounts/${forge}/token`, json({ token, url })),

  /** Reprend le compte de GitHub CLI (`gh`). */
  connectGh: (forge: ForgeKind) => request<Account>('POST', `/api/accounts/${forge}/gh`),

  /** Redemande à la forge qui est connecté et avec quels droits. */
  verifyAccount: (forge: ForgeKind, host?: string) =>
    request<Account>('POST', `/api/accounts/${forge}/verify${hostQuery(host)}`),

  disconnect: (forge: ForgeKind, host?: string) =>
    request<Disconnection>('DELETE', `/api/accounts/${forge}${hostQuery(host)}`),

  /**
   * Les dépôts des comptes connectés, l'état de leur dernière analyse et la synthèse. La liste
   * est demandée aux forges la première fois ; `reload` la redemande.
   */
  listRepositories: (reload = false) =>
    request<RepositoryList>('GET', reload ? '/api/repositories?reload=true' : '/api/repositories'),

  /** Analyse ensemble des dépôts d'un compte connecté, sans les cloner. */
  startBatch: (body: BatchRequest) => request<RepositoryBatch>('POST', '/api/repositories/batches', json(body)),

  /** Annule les analyses du lot qui ne sont pas finies. */
  cancelBatch: (id: string) =>
    request<RepositoryBatch>('DELETE', `/api/repositories/batches/${encodeURIComponent(id)}`),

  /** Analyse un dépôt donné par son nom ou son adresse, même d'un autre compte s'il est public. */
  scanRepository: (body: RepositoryRequest) =>
    request<ScanSummary>('POST', '/api/repositories/scans', json(body)),

  /** Le récapitulatif des PR de quelques dépôts : rien n'est cloné ni poussé. */
  createProposal: (body: ProposalRequest) => request<Proposal>('POST', '/api/proposals', json(body)),

  getProposal: (id: string) => request<Proposal>('GET', `/api/proposals/${encodeURIComponent(id)}`),

  /** Envoie les dépôts cochés du récapitulatif, en tâche de fond. */
  sendProposal: (id: string, repositories: RepositoryKey[]) =>
    request<Proposal>('POST', `/api/proposals/${encodeURIComponent(id)}/send`, json({ repositories })),
}

export const queryKeys = {
  scans: ['scans'] as const,
  scan: (id: string) => ['scan', id] as const,
  plan: (id: string) => ['plan', id] as const,
  folder: (path: string | null) => ['fs', path] as const,
  accounts: ['accounts'] as const,
  repositories: ['repositories'] as const,
  connection: (id: string) => ['connection', id] as const,
  proposal: (id: string) => ['proposal', id] as const,
}
