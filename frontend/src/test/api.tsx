/**
 * Les outils des tests de composants : un `fetch` simulé, route par route, et l'application
 * rendue à une adresse.
 */
import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { AppRoutes, createQueryClient } from '@/App'
import type {
  Account,
  AccountConnection,
  AccountList,
  ForgeStatus,
  Listing,
  Proposal,
  ProposedRepository,
  Report,
  RepositoryAccount,
  RepositoryBatch,
  RepositoryList,
  RepositoryRow,
  RepositorySynthesis,
  ScanDetail,
  ScanSummary,
  SettingsDocument,
  UpdatePlan,
} from '@/api/types'
import eol from './fixtures/eol.json'
import imports from './fixtures/imports.json'
import vulnerable from './fixtures/vulnerable.json'

/** Le rapport de `tests/projects/vulnerable` (`tests/e2e_server.py --report`). */
export const VULNERABLE = vulnerable as unknown as Report

/** Le rapport de `tests/projects/eol` : Python 3.8, Django 3.2 et Node.js 16 en fin de vie (E27). */
export const EOL = eol as unknown as Report

/** Le rapport de `tests/projects/scripts/imports.py`, copié seul : ses imports, sans version (E28). */
export const IMPORTS = imports as unknown as Report

/** Une réponse d'erreur de l'API. */
export class Status {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown = { detail: `Erreur ${status}.` }) {
    this.status = status
    this.body = body
  }
}

/** Le serveur ne répond pas (le `fetch` échoue). */
export const DOWN = Symbol('down')

type Handler = (request: { url: URL; init: RequestInit }) => unknown
type Reply = Handler | Status | typeof DOWN | object

/**
 * Remplace `fetch` : `routes` donne, par « MÉTHODE /chemin » (sans la requête), la réponse
 * (un objet, une `Status`, `DOWN`, ou une fonction de la requête). Rend la liste des appels.
 * Par défaut, `GET /api/accounts` rend les forges sans compte connecté (l'accueil les demande),
 * et `GET /api/settings` les réglages par défaut (les options d'analyse les suivent).
 */
export function mockApi(given: Record<string, Reply>) {
  const routes: Record<string, Reply> = {
    'GET /api/accounts': accountList(),
    'GET /api/settings': settingsDocument(),
    ...given,
  }
  const calls: { method: string; url: URL; init: RequestInit }[] = []
  const fetch = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), 'http://127.0.0.1:8765')
    const method = (init.method ?? 'GET').toUpperCase()
    calls.push({ method, url, init })
    const key = `${method} ${url.pathname}`
    if (!(key in routes)) throw new Error(`route non simulée : ${key}`)
    const route = routes[key]
    const reply = typeof route === 'function' ? (route as Handler)({ url, init }) : route
    if (reply === DOWN) throw new TypeError('Failed to fetch')
    if (reply instanceof Status) {
      return new Response(JSON.stringify(reply.body), {
        status: reply.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response(JSON.stringify(reply), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetch)
  return calls
}

/** L'application (coquille comprise) rendue à `path`. */
export function renderApp(path: string) {
  const client = createQueryClient()
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const OPTIONS = { include_tests: false, dev: true, transitive: false, offline: false, cache: true, ignore: [], selection: [] }

/** Une analyse, finie avec son rapport (par défaut celui de `vulnerable`). */
export function scanDetail(overrides: Partial<ScanDetail> = {}): ScanDetail {
  const report = overrides.report === undefined ? VULNERABLE : overrides.report
  return {
    id: 'a1',
    source: 'C:/Projets/vulnerable',
    kind: 'folder',
    repository: null,
    batch: null,
    status: 'done',
    options: OPTIONS,
    started_at: '2026-10-28T17:30:00+00:00',
    finished_at: '2026-10-28T17:30:01+00:00',
    error: null,
    progress: { kind: 'finished', done: 0, total: 0, ecosystem: null, name: null },
    summary: report ? report.summary : null,
    report,
    ...overrides,
  }
}

export function scanSummary(overrides: Partial<ScanSummary> = {}): ScanSummary {
  const { report: _report, ...summary } = scanDetail(overrides as Partial<ScanDetail>)
  return summary
}

/**
 * Le plan de la sélection proposée de `vulnerable` (lodash 4.18.1, flask 0.12.5, jinja2
 * 2.11.3), tel que le rend `POST /api/updates/plan` : deux diffs, npm et uv trouvés.
 */
export function planDocument(overrides: Partial<UpdatePlan> = {}): UpdatePlan {
  return {
    id: 'p1',
    scan: 'a1',
    status: 'planned',
    created_at: '2026-10-28T17:31:00+00:00',
    finished_at: null,
    selection: { '.|npm|lodash': '4.18.1', '.|PyPI|flask': '0.12.5', '.|PyPI|jinja2|2.10': '2.11.3' },
    applied: [
      { update: '.|PyPI|flask', version: '0.12.5' },
      { update: '.|PyPI|jinja2|2.10', version: '2.11.3' },
      { update: '.|npm|lodash', version: '4.18.1' },
    ],
    skipped: [],
    files: [
      {
        path: 'package.json',
        diff:
          '--- a/package.json\n+++ b/package.json\n@@ -3,6 +3,6 @@\n   "version": "1.0.0",\n   "private": true,\n   "dependencies": {\n-    "lodash": "4.17.15"\n+    "lodash": "4.18.1"\n   }\n }\n',
      },
      {
        path: 'requirements.in',
        diff:
          '--- a/requirements.in\n+++ b/requirements.in\n@@ -1,2 +1,2 @@\n # Une vieille application Flask ; requirements.txt est compilé avec uv pip compile.\n-flask==0.12\n+flask==0.12.5\n',
      },
    ],
    lockfiles: [
      {
        lockfile: 'package-lock.json',
        kind: 'npm',
        tool: 'npm',
        program: 'npm',
        available: true,
        command: 'npm install --package-lock-only --ignore-scripts',
        directory: '.',
        updates: [{ update: '.|npm|lodash', version: '4.18.1' }],
        workspace: false,
        reason: null,
        warnings: [],
        extra: null,
        accepted: true,
      },
      {
        lockfile: 'requirements.txt',
        kind: 'uv-pip-compile',
        tool: 'uv pip compile',
        program: 'uv',
        available: true,
        command:
          'uv pip compile requirements.in -o requirements.txt --python-version 3.7 -P flask==0.12.5 -P jinja2==2.11.3',
        directory: '.',
        updates: [
          { update: '.|PyPI|flask', version: '0.12.5' },
          { update: '.|PyPI|jinja2|2.10', version: '2.11.3' },
        ],
        workspace: false,
        reason: null,
        warnings: [
          "Pas repris de l'en-tête de requirements.txt : --exclude-newer 2019-01-01, qui écarterait les versions choisies.",
        ],
        extra: null,
        accepted: true,
      },
    ],
    uncommitted: [],
    applicable: true,
    error: null,
    results: [],
    progress: null,
    ...overrides,
  }
}

/** Ce que rend la régénération des deux lockfiles de `vulnerable` : versions exactes. */
export function regenerated(): UpdatePlan['results'] {
  const exact = (update: string, version: string) => ({ update, version, versions: [version], reach: 'exact' as const, held_by: [] })
  return [
    {
      lockfile: 'package-lock.json',
      status: 'regenerated',
      error: null,
      restored: [],
      installed: [exact('.|npm|lodash', '4.18.1')],
      changed: [],
      warnings: [],
      verified: null,
      dropped: [],
    },
    {
      lockfile: 'requirements.txt',
      status: 'regenerated',
      error: null,
      restored: [],
      installed: [exact('.|PyPI|flask', '0.12.5'), exact('.|PyPI|jinja2|2.10', '2.11.3')],
      changed: [],
      warnings: [],
      verified: null,
      dropped: [],
    },
  ]
}

export function listing(overrides: Partial<Listing> = {}): Listing {
  return {
    path: null,
    parent: null,
    entries: [
      { name: 'moi', path: 'C:/Users/moi', kind: 'folder', hidden: false },
      { name: 'C:', path: 'C:/', kind: 'drive', hidden: false },
    ],
    truncated: false,
    home: 'C:/Users/moi',
    recent: [],
    ...overrides,
  }
}

/** Le compte GitHub `@octo`, connecté par OAuth, avec les portées demandées. */
export function account(overrides: Partial<Account> = {}): Account {
  return {
    forge: 'github',
    host: 'github.com',
    login: 'octo',
    name: 'Octo Cat',
    url: 'https://github.com/octo',
    access: 'write',
    scopes: ['repo', 'read:org'],
    warnings: [],
    method: 'oauth',
    connected_at: '2026-10-28T17:30:00+00:00',
    checked_at: '2026-10-28T17:30:00+00:00',
    problem: null,
    ...overrides,
  }
}

/** GitHub dans la liste des forges : sans compte par défaut, toutes les façons de s'y connecter sauf gh. */
export function githubStatus(overrides: Partial<ForgeStatus> = {}): ForgeStatus {
  return {
    forge: 'github',
    name: 'GitHub',
    host: 'github.com',
    available: true,
    methods: ['oauth', 'device', 'token'],
    scopes: ['repo', 'read:org'],
    token_scopes: ['repo', 'read:org'],
    token_url: 'https://github.com/settings/tokens/new?scopes=repo,read:org&description=forceupdate',
    revocable: true,
    applications_url: 'https://github.com/settings/applications',
    self_hosted: false,
    request: 'PR',
    account: null,
    instances: [],
    connection: null,
    ...overrides,
  }
}

/** Le compte GitLab `@renard`, connecté à gitlab.com par OAuth. */
export function gitlabAccount(overrides: Partial<Account> = {}): Account {
  return account({
    forge: 'gitlab',
    host: 'gitlab.com',
    login: 'renard',
    name: 'Renard Roux',
    url: 'https://gitlab.com/renard',
    scopes: ['api'],
    ...overrides,
  })
}

/** GitLab dans la liste des forges : sans compte par défaut ; OAuth, token collé, instance. */
export function gitlabStatus(overrides: Partial<ForgeStatus> = {}): ForgeStatus {
  return {
    forge: 'gitlab',
    name: 'GitLab',
    host: 'gitlab.com',
    available: true,
    methods: ['oauth', 'token'],
    scopes: ['api'],
    token_scopes: ['api'],
    token_url: 'https://gitlab.com/-/user_settings/personal_access_tokens?name=forceupdate&scopes=api',
    revocable: true,
    applications_url: 'https://gitlab.com/-/user_settings/applications',
    self_hosted: true,
    request: 'MR',
    account: null,
    instances: [],
    connection: null,
    ...overrides,
  }
}

/** Le compte Bitbucket `@ecureuil`, connecté par OAuth. */
export function bitbucketAccount(overrides: Partial<Account> = {}): Account {
  return account({
    forge: 'bitbucket',
    host: 'bitbucket.org',
    login: 'ecureuil',
    name: 'Écureuil Roux',
    url: 'https://bitbucket.org/%7B0f1e2d3c%7D/',
    scopes: ['account', 'email', 'pullrequest:write', 'repository:write'],
    ...overrides,
  })
}

/** Les portées d'un token d'API Atlassian pour Bitbucket. */
export const BITBUCKET_TOKEN_SCOPES = [
  'read:user:bitbucket',
  'read:workspace:bitbucket',
  'read:repository:bitbucket',
  'write:repository:bitbucket',
  'read:pullrequest:bitbucket',
  'write:pullrequest:bitbucket',
]

/** Bitbucket dans la liste des forges : sans compte par défaut ; OAuth (sans révocation), token d'API. */
export function bitbucketStatus(overrides: Partial<ForgeStatus> = {}): ForgeStatus {
  return {
    forge: 'bitbucket',
    name: 'Bitbucket',
    host: 'bitbucket.org',
    available: true,
    methods: ['oauth', 'token'],
    scopes: ['account', 'email', 'repository:write', 'pullrequest:write'],
    token_scopes: BITBUCKET_TOKEN_SCOPES,
    token_url: 'https://id.atlassian.com/manage-profile/security/api-tokens',
    revocable: false,
    applications_url: 'https://bitbucket.org/account/settings/app-authorizations/',
    self_hosted: false,
    request: 'PR',
    account: null,
    instances: [],
    connection: null,
    ...overrides,
  }
}

/** `GET /api/accounts` : GitHub (`githubStatus(github)`), GitLab (`gitlabStatus(gitlab)`), puis
 * Bitbucket (`bitbucketStatus(bitbucket)`). */
export function accountList(
  github: Partial<ForgeStatus> = {},
  keyring: string | null = null,
  gitlab: Partial<ForgeStatus> = {},
  bitbucket: Partial<ForgeStatus> = {},
): AccountList {
  return { keyring, forges: [githubStatus(github), gitlabStatus(gitlab), bitbucketStatus(bitbucket)] }
}

/** Une connexion par device flow, en attente du code `WDJB-MJHT`. */
export function deviceConnection(overrides: Partial<AccountConnection> = {}): AccountConnection {
  return {
    id: 'c1',
    forge: 'github',
    method: 'device',
    status: 'pending',
    created_at: '2026-10-28T17:30:00+00:00',
    expires_at: '2026-10-28T17:45:00+00:00',
    authorize_url: null,
    user_code: 'WDJB-MJHT',
    verification_uri: 'https://github.com/login/device',
    interval: 5,
    error: null,
    account: null,
    ...overrides,
  }
}

/** Un dépôt de `octo`, pas encore analysé. */
export function repositoryRow(overrides: Partial<RepositoryRow> = {}): RepositoryRow {
  const fullName = overrides.full_name ?? 'octo/app'
  const [owner, name] = fullName.split('/')
  return {
    forge: 'github',
    host: 'github.com',
    full_name: fullName,
    owner,
    name,
    url: `https://github.com/${fullName}`,
    default_branch: 'main',
    private: false,
    archived: false,
    fork: false,
    empty: false,
    can_push: true,
    pushed_at: '2026-10-28T15:30:00+00:00',
    hidden: false,
    languages: ['Python'],
    state: 'not_scanned',
    reason: null,
    counts: null,
    scan: null,
    request: null,
    ...overrides,
  }
}

/** Le compte GitHub `octo`, vu depuis ses dépôts. */
export function repositoryAccount(overrides: Partial<RepositoryAccount> = {}): RepositoryAccount {
  return {
    forge: 'github',
    host: 'github.com',
    login: 'octo',
    access: 'write',
    problem: null,
    listed_at: '2026-10-28T17:30:00+00:00',
    error: null,
    repositories: 0,
    restrictions: [],
    rate_limit: { limit: 5000, remaining: 4210, reset_at: '2026-10-28T19:00:00+00:00' },
    ...overrides,
  }
}

export function synthesis(overrides: Partial<RepositorySynthesis> = {}): RepositorySynthesis {
  return {
    repositories: 0,
    hidden: 0,
    archived: 0,
    forks: 0,
    empty: 0,
    analyzed: 0,
    running: 0,
    not_scanned: 0,
    skipped: 0,
    to_update: 0,
    up_to_date: 0,
    inconclusive: 0,
    no_dependencies: 0,
    vulnerabilities: 0,
    critical: 0,
    vulnerable_repositories: 0,
    findings: { vulnerable: 0, eol: 0, yanked: 0, deprecated: 0, outdated: 0, unverifiable: 0, inconclusive: 0 },
    severities: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
    open_requests: 0,
    ...overrides,
  }
}

/** `GET /api/repositories` : par défaut, aucun compte connecté. */
export function repositoryList(overrides: Partial<RepositoryList> = {}): RepositoryList {
  return { accounts: [], repositories: [], synthesis: synthesis(), batch: null, ...overrides }
}

/** Une analyse groupée de `total` dépôts, en cours. */
export function batch(overrides: Partial<RepositoryBatch> = {}): RepositoryBatch {
  return {
    id: 'b1',
    status: 'running',
    started_at: '2026-10-28T17:31:00+00:00',
    finished_at: null,
    concurrency: 4,
    scans: ['s1', 's2', 's3'],
    total: 3,
    finished: 1,
    failed: 0,
    skipped: [],
    requests: 42,
    ...overrides,
  }
}

/**
 * Un dépôt d'un récapitulatif de PR : `octo/boutique`, prêt, la sélection proposée de
 * `vulnerable` (lodash, flask, jinja2), npm trouvé et uv absent.
 */
export function proposedRepository(overrides: Partial<ProposedRepository> = {}): ProposedRepository {
  const plan = planDocument()
  const fullName = overrides.full_name ?? 'octo/boutique'
  return {
    forge: 'github',
    host: 'github.com',
    full_name: fullName,
    url: `https://github.com/${fullName}`,
    default_branch: 'main',
    branch: 'forceupdate/dependencies',
    scan: 's-boutique',
    commit: 'abc1234def5678abc1234def5678abc1234def56',
    state: 'ready',
    reason: null,
    inconclusive: false,
    checked: true,
    request: null,
    closed: null,
    selection: plan.selection,
    applied: [
      { update: '.|npm|lodash', name: 'lodash', ecosystem: 'npm', project: '.', direct: true, current: '4.17.15', version: '4.18.1', gap: 'minor', fixes: ['CVE-2021-23337', 'CVE-2020-8203'], held_by: [], refused_by: [], blockers: [] },
      { update: '.|PyPI|flask', name: 'flask', ecosystem: 'PyPI', project: '.', direct: true, current: '0.12', version: '0.12.5', gap: 'patch', fixes: ['CVE-2018-1000656'], held_by: [], refused_by: [], blockers: [] },
      { update: '.|PyPI|jinja2|2.10', name: 'jinja2', ecosystem: 'PyPI', project: '.', direct: false, current: '2.10', version: '2.11.3', gap: 'minor', fixes: ['CVE-2019-10906'], held_by: [], refused_by: [], blockers: [] },
    ],
    skipped: [],
    files: plan.files,
    lockfiles: [plan.lockfiles[0], { ...plan.lockfiles[1], available: false }],
    step: null,
    progress: null,
    pushed: false,
    base: null,
    results: [],
    committed: [],
    error: null,
    ...overrides,
  }
}

/** Un récapitulatif de PR préparé (rien n'est encore envoyé). */
export function proposal(overrides: Partial<Proposal> = {}): Proposal {
  const repositories = overrides.repositories ?? [proposedRepository()]
  const ready = repositories.filter((item) => item.state === 'ready')
  return {
    id: 'pr1',
    status: 'planned',
    created_at: '2026-10-29T10:00:00+00:00',
    started_at: null,
    finished_at: null,
    repositories,
    ready: ready.length,
    existing: ready.filter((item) => item.request !== null).length,
    error: null,
    ...overrides,
  }
}

/** Les réglages de la personne (`GET /api/settings`) : par défaut, ceux de forceupdate. */
export function settingsDocument(overrides: Partial<SettingsDocument> = {}): SettingsDocument {
  const defaults = {
    ignore: [],
    include_tests: false,
    selection: [],
    excluded_repositories: [],
    lock_timeout: 600,
    clone_timeout: 600,
    rust_default_toolchain: false,
  }
  return {
    values: defaults,
    defaults,
    file: 'C:/Users/moi/AppData/Local/forceupdate/forceupdate.toml',
    problems: [],
    cache: {
      path: 'C:/Users/moi/AppData/Local/forceupdate/Cache/cache.sqlite3',
      enabled: true,
      entries: 412,
      size: 3_456_789,
      oldest: '2026-10-30T08:00:00+00:00',
      newest: '2026-11-02T09:15:00+00:00',
    },
    ...overrides,
  }
}
