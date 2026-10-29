import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { RepositoryList } from '@/api/types'
import { display } from '@/test/display'
import {
  Status,
  VULNERABLE,
  account,
  accountList,
  batch,
  githubStatus,
  mockApi,
  renderApp,
  repositoryAccount,
  repositoryList,
  repositoryRow,
  scanDetail,
  scanSummary,
  synthesis,
} from '@/test/api'

const ROWS = [
  repositoryRow({
    full_name: 'octo/boutique',
    private: true,
    languages: ['TypeScript', 'Python'],
    state: 'to_update',
    counts: { vulnerabilities: 3, critical: 1, worst: 'critical', to_update: 12, inconclusive: 0, updates: 4 },
    scan: scanSummary({ id: 's-boutique', kind: 'repository', source: 'octo/boutique' }),
    pushed_at: '2026-10-28T10:00:00+00:00',
  }),
  repositoryRow({
    full_name: 'atelier/api',
    can_push: false,
    state: 'up_to_date',
    counts: { vulnerabilities: 0, critical: 0, worst: null, to_update: 0, inconclusive: 0, updates: 0 },
    scan: scanSummary({ id: 's-api', kind: 'repository', source: 'atelier/api' }),
    pushed_at: '2026-09-01T10:00:00+00:00',
  }),
  repositoryRow({ full_name: 'octo/scripts', state: 'inconclusive', reason: 'PyPI injoignable', pushed_at: '2026-10-20T10:00:00+00:00' }),
  repositoryRow({ full_name: 'octo/notes', state: 'no_dependencies', languages: ['Markdown'], pushed_at: null }),
  repositoryRow({ full_name: 'octo/neuf' }),
  repositoryRow({ full_name: 'octo/ancien', archived: true, hidden: true, state: 'skipped', reason: 'archivé' }),
  repositoryRow({ full_name: 'octo/vide', empty: true, hidden: true, state: 'skipped', reason: 'vide' }),
]

function list(overrides: Partial<RepositoryList> = {}): RepositoryList {
  return repositoryList({
    accounts: [repositoryAccount({ repositories: ROWS.length })],
    repositories: ROWS,
    synthesis: synthesis({
      repositories: 7,
      hidden: 2,
      archived: 1,
      empty: 1,
      analyzed: 4,
      skipped: 2,
      not_scanned: 1,
      to_update: 1,
      up_to_date: 1,
      inconclusive: 1,
      no_dependencies: 1,
      vulnerabilities: 3,
      critical: 1,
      vulnerable_repositories: 1,
    }),
    ...overrides,
  })
}

const FLASK = { forge: 'github' as const, host: 'github.com', full_name: 'pallets/flask', url: 'https://github.com/pallets/flask', commit: null, truncated: false }

function connected() {
  return { 'GET /api/accounts': accountList(githubStatus({ account: account() })) }
}

/** La ligne du tableau du dépôt `name` (son nom est en chasse fixe). */
function rowOf(name: string): HTMLElement {
  const row = screen.getAllByRole('row').find((each) => each.querySelector('.font-mono')?.textContent === name)
  if (!row) throw new Error(`pas de ligne pour ${name}`)
  return row
}

describe('mes dépôts (écran 7)', () => {
  it('sans compte : « Connecter un compte », et un dépôt public à analyser quand même', async () => {
    mockApi({ 'GET /api/repositories': repositoryList() })
    renderApp('/depots')
    expect(await screen.findByRole('heading', { level: 2, name: 'Aucun compte connecté' })).toBeInTheDocument()
    expect(document.title).toBe('Mes dépôts · forceupdate')
    expect(screen.getByRole('link', { name: 'Connecter un compte' })).toHaveAttribute('href', '/comptes')
    expect(screen.getByLabelText('Dépôt public : owner/nom ou adresse')).toBeInTheDocument()
    expect(screen.getByText(/60 requêtes par heure/)).toBeInTheDocument()
  })

  it('la liste : comptes, synthèse, requêtes restantes, et une ligne par dépôt avec son état', async () => {
    mockApi({ 'GET /api/repositories': list() })
    renderApp('/depots')
    expect(await screen.findByRole('heading', { level: 2, name: 'Synthèse' })).toBeInTheDocument()
    expect(screen.getByText(/7 dépôts sur 1 compte/)).toBeInTheDocument()
    const chips = screen.getByRole('region', { name: 'Comptes connectés' })
    expect(within(chips).getByText('octo')).toBeInTheDocument()
    expect(within(chips).getByText('lecture et PR')).toBeInTheDocument()
    expect(screen.getByText(/API GitHub : 4 210 requêtes restantes sur 5 000/)).toBeInTheDocument()
    const stats = screen.getByRole('group', { name: /Synthèse des dépôts/ })
    expect(within(stats).getByText('4 analysés · 2 sautés')).toBeInTheDocument()
    expect(within(stats).getByRole('button', { name: /^Failles/ })).toHaveTextContent('3dont 1 critique · dans 1 dépôt')

    // Le dépôt privé, à mettre à jour : ses chiffres, le lien vers son rapport.
    const boutique = rowOf('octo/boutique')
    expect(within(boutique).getByRole('img', { name: 'privé' })).toBeInTheDocument()
    expect(within(boutique).getByText('1 critique')).toBeInTheDocument()
    expect(within(boutique).getByText('3 failles')).toBeInTheDocument()
    expect(within(boutique).getByText('12 à mettre à jour')).toBeInTheDocument()
    expect(within(boutique).getByRole('link', { name: 'octo/boutique' })).toHaveAttribute('href', '/analyses/s-boutique')
    expect(within(boutique).getByRole('link', { name: 'Ouvrir octo/boutique sur GitHub (nouvel onglet)' })).toHaveAttribute(
      'href',
      'https://github.com/octo/boutique',
    )
    expect(within(rowOf('atelier/api')).getByText('à jour')).toBeInTheDocument()
    expect(within(rowOf('atelier/api')).getByText('lecture seule')).toBeInTheDocument()
    expect(within(rowOf('octo/scripts')).getByText('non concluant')).toBeInTheDocument()
    expect(within(rowOf('octo/scripts')).getByText('PyPI injoignable')).toBeInTheDocument()
    expect(within(rowOf('octo/notes')).getByText('aucun fichier de dépendances')).toBeInTheDocument()
    expect(within(rowOf('octo/neuf')).getByText('pas encore analysé')).toBeInTheDocument()

    // Archivés, forks et vides : masqués, comptés, à afficher sur demande.
    expect(screen.queryByText('octo/ancien')).toBeNull()
    expect(screen.getByText(/5 affichés · 2 masqués \(1 archivé, 1 vide\)/)).toBeInTheDocument()
  })

  it('filtres, compteurs filtrants, dépôts masqués et tri', async () => {
    mockApi({ 'GET /api/repositories': list() })
    const user = userEvent.setup()
    renderApp('/depots')
    await screen.findByRole('heading', { level: 2, name: 'Synthèse' })
    await user.type(screen.getByLabelText('Filtrer par nom'), 'boutique')
    expect(screen.getAllByRole('row')).toHaveLength(2)
    await user.click(screen.getByRole('button', { name: 'Tout afficher' }))
    const toUpdate = screen.getByRole('button', { name: /^À mettre à jour/ })
    await user.click(toUpdate)
    expect(toUpdate).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getAllByRole('row')).toHaveLength(2)
    await user.click(toUpdate)
    await user.selectOptions(screen.getByLabelText('Propriétaire'), 'atelier')
    expect(screen.getAllByRole('row')).toHaveLength(2)
    await user.selectOptions(screen.getByLabelText('Propriétaire'), 'all')

    // Le dernier push, du plus récent au plus ancien ; jamais poussé : en dernier.
    const header = screen.getByRole('columnheader', { name: /Dernier push/ })
    await user.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'descending')
    const names = screen.getAllByRole('row').slice(1).map((row) => row.querySelector('.font-mono')?.textContent)
    expect(names).toEqual(['octo/neuf', 'octo/boutique', 'octo/scripts', 'atelier/api', 'octo/notes'])

    await user.click(screen.getByRole('button', { name: 'Les afficher' }))
    expect(within(rowOf('octo/ancien')).getByText('sauté : archivé : pas analysé par défaut')).toBeInTheDocument()
    expect(within(rowOf('octo/vide')).getByRole('checkbox')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Les masquer' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('cocher des dépôts, puis les analyser ensemble', async () => {
    const calls = mockApi({
      'GET /api/repositories': list(),
      'POST /api/repositories/batches': batch(),
    })
    const user = userEvent.setup()
    renderApp('/depots')
    await screen.findByRole('heading', { level: 2, name: 'Synthèse' })
    await user.click(screen.getByRole('checkbox', { name: 'Sélectionner octo/boutique' }))
    await user.click(screen.getByRole('checkbox', { name: 'Sélectionner octo/neuf' }))
    const all = screen.getByRole('checkbox', { name: /Tout sélectionner/ }) as HTMLInputElement
    expect(all.indeterminate).toBe(true)
    expect(rowOf('octo/boutique')).toHaveClass('bg-primary-soft')
    const bar = screen.getByRole('region', { name: 'Actions sur la sélection' })
    expect(within(bar).getByText('2 dépôts sélectionnés')).toBeInTheDocument()
    expect(within(bar).getByText(/4 mises à jour cochées par défaut/)).toBeInTheDocument()
    await user.click(within(bar).getByRole('button', { name: 'Analyser ces 2 dépôts' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    const sent = calls.find((call) => call.method === 'POST')!
    expect(sent.url.pathname).toBe('/api/repositories/batches')
    expect(JSON.parse(String(sent.init.body))).toEqual({
      forge: 'github',
      repositories: ['octo/boutique', 'octo/neuf'],
      dev: true,
      transitive: false,
      include_tests: false,
      cache: true,
    })
    expect(screen.queryByRole('region', { name: 'Actions sur la sélection' })).toBeNull()
  })

  it('« Tout sélectionner » prend les lignes affichées, pas les vides', async () => {
    mockApi({ 'GET /api/repositories': list() })
    const user = userEvent.setup()
    renderApp('/depots')
    await screen.findByRole('heading', { level: 2, name: 'Synthèse' })
    await user.click(screen.getByRole('button', { name: 'Les afficher' }))
    await user.click(screen.getByRole('checkbox', { name: /Tout sélectionner \(6\sdépôts affichés\)/ }))
    expect(screen.getByText('6 dépôts sélectionnés')).toBeInTheDocument()
  })

  it('une analyse groupée en cours : sa carte, la progression par dépôt, « Annuler »', async () => {
    const running = repositoryRow({
      full_name: 'octo/site',
      state: 'running',
      scan: scanSummary({
        id: 's-site',
        kind: 'repository',
        source: 'octo/site',
        status: 'running',
        summary: null,
        progress: { kind: 'downloading', done: 2, total: 5, ecosystem: null, name: null },
      }),
    })
    const calls = mockApi({
      'GET /api/repositories': list({ repositories: [running, ...ROWS], batch: batch() }),
      'DELETE /api/repositories/batches/b1': batch({ status: 'cancelled' }),
    })
    const user = userEvent.setup()
    renderApp('/depots')
    const card = await screen.findByRole('region', { name: /Analyse de 3\sdépôts\s: 1 terminée/ })
    expect(within(card).getByRole('progressbar', { name: 'Dépôts analysés' })).toHaveAttribute('aria-valuenow', '1')
    expect(within(card).getByText(/4 à la fois · registres en cache partagés · 42 requêtes d'API utilisées/)).toBeInTheDocument()
    expect(within(rowOf('octo/site')).getByText('téléchargement : 2 sur 5 fichiers')).toBeInTheDocument()
    expect(within(rowOf('octo/site')).getByRole('progressbar')).toHaveAttribute('aria-valuemax', '5')
    // Pendant l'analyse, on n'en lance pas d'autre.
    expect(screen.getByRole('button', { name: 'Analyser tous les dépôts' })).toBeDisabled()
    await user.click(within(card).getByRole('button', { name: 'Annuler' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'DELETE')).toBe(true))
  })

  it('les alertes : token refusé, organisation restreinte, dépôts non concluants', async () => {
    const calls = mockApi({
      'GET /api/repositories': list({
        accounts: [
          repositoryAccount({
            problem: 'GitHub refuse le token (401) : révoqué, expiré, ou mal copié. Se reconnecter.',
            restrictions: [{ organization: 'nord', kind: 'app_access', url: 'https://github.com/settings/applications' }],
          }),
        ],
      }),
      'POST /api/repositories/batches': batch(),
    })
    const user = userEvent.setup()
    renderApp('/depots')
    const refused = await screen.findByRole('alert')
    expect(within(refused).getByText('GitHub refuse le token de octo')).toBeInTheDocument()
    expect(within(refused).getByRole('link', { name: 'Reconnecter GitHub' })).toHaveAttribute('href', '/comptes')
    expect(screen.getByText('token refusé')).toBeInTheDocument()
    expect(screen.getByText("L'organisation nord limite l'accès des applications")).toBeInTheDocument()
    expect(screen.getByRole('link', { name: "Demander l'accès sur GitHub (nouvel onglet)" })).toHaveAttribute(
      'href',
      'https://github.com/settings/applications',
    )
    expect(screen.getByText('1 dépôt non concluant')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Relancer ce dépôt' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    expect(JSON.parse(String(calls.find((call) => call.method === 'POST')!.init.body)).repositories).toEqual(['octo/scripts'])
  })

  it('hors ligne : la liste du dernier chargement, les analyses attendent', async () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => false })
    mockApi({ 'GET /api/repositories': list() })
    const user = userEvent.setup()
    renderApp('/depots')
    expect(await screen.findByText(/La liste affichée est celle du dernier chargement/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyser tous les dépôts' })).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: 'Sélectionner octo/neuf' }))
    expect(screen.getByRole('button', { name: 'Analyser ce dépôt' })).toBeDisabled()
    expect(screen.getByText('Hors ligne : les analyses attendront le réseau.')).toBeInTheDocument()
  })

  it('sous 768 px : une carte par dépôt', async () => {
    display.wide = false
    mockApi({ 'GET /api/repositories': list() })
    renderApp('/depots')
    const cards = await screen.findByRole('list', { name: 'Dépôts des comptes connectés' })
    expect(screen.queryByRole('table')).toBeNull()
    expect(within(cards).getAllByRole('listitem')).toHaveLength(5)
    expect(within(cards).getByRole('link', { name: 'octo/boutique' })).toBeInTheDocument()
  })

  it('liste indisponible : « Réessayer »', async () => {
    mockApi({ 'GET /api/repositories': new Status(500, { detail: 'Panne.' }) })
    renderApp('/depots')
    expect(await screen.findByRole('heading', { level: 1, name: 'Dépôts indisponibles' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeInTheDocument()
  })

  it('un dépôt public d’un autre compte : analysé, puis son analyse s’ouvre', async () => {
    const calls = mockApi({
      'GET /api/repositories': list(),
      'POST /api/repositories/scans': ({ init }: { init: RequestInit }) => {
        const body = JSON.parse(String(init.body))
        if (body.repository === 'octo/inconnu') {
          return new Status(404, { detail: 'Dépôt introuvable sur GitHub : octo/inconnu n’existe pas.' })
        }
        return scanSummary({ id: 'pub', kind: 'repository', source: 'pallets/flask', repository: FLASK, status: 'running', summary: null })
      },
      'GET /api/scans/pub': scanDetail({
        id: 'pub',
        kind: 'repository',
        source: 'pallets/flask',
        repository: FLASK,
        status: 'running',
        report: null,
        summary: null,
        progress: null,
      }),
    })
    const user = userEvent.setup()
    renderApp('/depots')
    const field = await screen.findByLabelText('Dépôt public : owner/nom ou adresse')
    await user.type(field, 'octo/inconnu')
    await user.click(screen.getByRole('button', { name: 'Analyser' }))
    expect(await screen.findByText('Dépôt introuvable sur GitHub : octo/inconnu n’existe pas.')).toBeInTheDocument()
    expect(field).toHaveAttribute('aria-invalid', 'true')
    await user.clear(field)
    await user.type(field, 'https://github.com/pallets/flask')
    await user.click(screen.getByRole('button', { name: 'Analyser' }))
    expect(await screen.findByRole('heading', { level: 1, name: /Analyse de pallets\/flask/ })).toBeInTheDocument()
    expect(screen.getByText('Lecture du dépôt et de son arborescence')).toBeInTheDocument()
    expect(calls.filter((call) => call.method === 'POST').map((call) => JSON.parse(String(call.init.body)).repository)).toEqual([
      'octo/inconnu',
      'https://github.com/pallets/flask',
    ])
  })
})

describe('le rapport d’un dépôt (écran 4)', () => {
  const repository = { forge: 'github' as const, host: 'github.com', full_name: 'octo/boutique', url: 'https://github.com/octo/boutique', commit: '4e111271b1494995708a9e878a10829b5e10c7ba', truncated: true }

  it('le dépôt, son commit, le lien vers la forge ; ni plan local, ni « Mettre à jour »', async () => {
    mockApi({
      'GET /api/scans/r1': scanDetail({ id: 'r1', kind: 'repository', source: 'octo/boutique', repository, report: { ...VULNERABLE, source: 'octo/boutique' } }),
    })
    renderApp('/analyses/r1')
    expect(await screen.findByRole('heading', { level: 1, name: 'octo/boutique' })).toBeInTheDocument()
    const crumbs = screen.getByRole('navigation', { name: "Fil d'Ariane" })
    expect(within(crumbs).getByRole('link', { name: 'Mes dépôts' })).toHaveAttribute('href', '/depots')
    expect(screen.getByText('4e11127')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Voir sur GitHub/ })).toHaveAttribute('href', 'https://github.com/octo/boutique')
    expect(screen.getByText('Analyse partielle : arborescence incomplète')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Mettre à jour/ })).toBeNull()
    expect(screen.getByRole('button', { name: "Relancer l'analyse" })).toBeInTheDocument()
  })

  it('« Relancer l’analyse » repasse par les dépôts', async () => {
    const calls = mockApi({
      'GET /api/scans/r1': scanDetail({ id: 'r1', kind: 'repository', source: 'octo/boutique', repository }),
      'POST /api/repositories/scans': scanSummary({ id: 'r2', kind: 'repository', source: 'octo/boutique', repository, status: 'running', summary: null }),
      'GET /api/scans/r2': scanDetail({ id: 'r2', kind: 'repository', source: 'octo/boutique', repository, status: 'running', report: null, summary: null }),
    })
    const user = userEvent.setup()
    renderApp('/analyses/r1')
    await user.click(await screen.findByRole('button', { name: "Relancer l'analyse" }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    const sent = calls.find((call) => call.method === 'POST')!
    expect(sent.url.pathname).toBe('/api/repositories/scans')
    expect(JSON.parse(String(sent.init.body))).toEqual({
      repository: 'octo/boutique',
      dev: true,
      transitive: false,
      include_tests: false,
      cache: true,
    })
  })
})

describe('l’accueil et les dépôts', () => {
  it('la carte « Mes dépôts » donne le nombre de dépôts du compte', async () => {
    mockApi({ ...connected(), 'GET /api/repositories': list(), 'GET /api/scans': [], 'GET /api/fs': { path: null, parent: null, entries: [], truncated: false, home: 'C:/Users/moi', recent: [] } })
    renderApp('/')
    expect(await screen.findByText('7 dépôts · 4 analysés')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Voir mes dépôts' })).toHaveAttribute('href', '/depots')
  })

  it('les analyses d’un lot ne sont pas dans « Cette session » ; un dépôt seul, si', async () => {
    mockApi({
      'GET /api/scans': [
        scanSummary({ id: 'lot', kind: 'repository', source: 'octo/boutique', batch: 'b1' }),
        scanSummary({ id: 'seul', kind: 'repository', source: 'pallets/flask', repository: { forge: 'github', host: 'github.com', full_name: 'pallets/flask', url: 'https://github.com/pallets/flask', commit: null, truncated: false } }),
      ],
      'GET /api/fs': { path: null, parent: null, entries: [], truncated: false, home: 'C:/Users/moi', recent: [] },
    })
    renderApp('/')
    expect(await screen.findByRole('link', { name: 'pallets/flask' })).toBeInTheDocument()
    expect(screen.getByText('dépôt GitHub')).toBeInTheDocument()
    expect(screen.queryByText('octo/boutique')).toBeNull()
  })
})
