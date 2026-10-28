/**
 * Les outils des tests de composants : un `fetch` simulé, route par route, et l'application
 * rendue à une adresse.
 */
import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { AppRoutes, createQueryClient } from '@/App'
import type { Listing, Report, ScanDetail, ScanSummary, UpdatePlan } from '@/api/types'
import vulnerable from './fixtures/vulnerable.json'

/** Le rapport de `tests/projects/vulnerable` (`tests/e2e_server.py --report`). */
export const VULNERABLE = vulnerable as unknown as Report

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
 */
export function mockApi(routes: Record<string, Reply>) {
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

const OPTIONS = { include_tests: false, dev: true, transitive: false, offline: false, cache: true }

/** Une analyse, finie avec son rapport (par défaut celui de `vulnerable`). */
export function scanDetail(overrides: Partial<ScanDetail> = {}): ScanDetail {
  const report = overrides.report === undefined ? VULNERABLE : overrides.report
  return {
    id: 'a1',
    source: 'C:/Projets/vulnerable',
    kind: 'folder',
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
    },
    {
      lockfile: 'requirements.txt',
      status: 'regenerated',
      error: null,
      restored: [],
      installed: [exact('.|PyPI|flask', '0.12.5'), exact('.|PyPI|jinja2|2.10', '2.11.3')],
      changed: [],
      warnings: [],
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
