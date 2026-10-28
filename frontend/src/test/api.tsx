/**
 * Les outils des tests de composants : un `fetch` simulé, route par route, et l'application
 * rendue à une adresse.
 */
import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import { AppRoutes, createQueryClient } from '@/App'
import type { Listing, Report, ScanDetail, ScanSummary } from '@/api/types'
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
