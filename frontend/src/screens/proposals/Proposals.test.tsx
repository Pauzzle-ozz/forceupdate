import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import type { Proposal } from '@/api/types'
import {
  Status,
  VULNERABLE,
  mockApi,
  proposal,
  proposedRepository,
  regenerated,
  renderApp,
  repositoryAccount,
  repositoryList,
  repositoryRow,
  scanDetail,
  scanSummary,
  synthesis,
} from '@/test/api'

const REQUEST = {
  number: 41,
  url: 'https://github.com/octo/boutique/pull/41',
  title: 'Mise à jour des dépendances (forceupdate)',
  branch: 'forceupdate/dependencies',
  base: 'main',
}

/** Le récapitulatif de trois dépôts : un prêt, un prêt avec une PR déjà ouverte et une analyse non concluante, un sauté. */
function recap(): Proposal {
  return proposal({
    repositories: [
      proposedRepository(),
      proposedRepository({
        full_name: 'octo/site',
        scan: 's-site',
        request: { ...REQUEST, number: 12, url: 'https://github.com/octo/site/pull/12' },
        inconclusive: true,
        checked: false,
        skipped: [{ update: '.|npm|left-pad', name: 'left-pad', version: '1.3.0', reason: "package.json a changé depuis l'analyse" }],
      }),
      proposedRepository({
        full_name: 'atelier/api',
        scan: 's-api',
        state: 'skipped',
        reason: 'lecture seule : pas de droit de push',
        checked: false,
        applied: [],
        files: [],
        lockfiles: [],
      }),
    ],
  })
}

/** La carte du dépôt `name` dans le récapitulatif. */
async function card(name: string): Promise<HTMLElement> {
  const heading = await screen.findByRole('heading', { name })
  return heading.closest<HTMLElement>('[data-slot="card"]')!
}

afterEach(() => {
  Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
})

describe('PR (écran 8)', () => {
  it('sans dépôt demandé : retour à « Mes dépôts »', async () => {
    mockApi({})
    renderApp('/pr')
    expect(await screen.findByRole('heading', { name: 'Aucun dépôt sélectionné' })).toBeInTheDocument()
    for (const link of screen.getAllByRole('link', { name: 'Mes dépôts' })) expect(link).toHaveAttribute('href', '/depots')
  })

  it('prépare le récapitulatif des dépôts demandés, puis passe à son adresse', async () => {
    const calls = mockApi({ 'POST /api/proposals': recap(), 'GET /api/proposals/pr1': recap() })
    renderApp('/pr?forge=github&depots=octo/boutique,octo/site,atelier/api')
    expect(await screen.findByRole('heading', { level: 1, name: 'Préparer les PR' })).toBeInTheDocument()
    const posts = calls.filter((call) => call.method === 'POST')
    expect(posts).toHaveLength(1)
    expect(JSON.parse(String(posts[0].init.body))).toEqual({
      forge: 'github',
      repositories: [
        { repository: 'octo/boutique', selection: null },
        { repository: 'octo/site', selection: null },
        { repository: 'atelier/api', selection: null },
      ],
    })
  })

  it('un récapitulatif refusé le dit, avec « Réessayer »', async () => {
    mockApi({ 'POST /api/proposals': new Status(404, { detail: 'Aucun compte GitHub connecté.' }) })
    renderApp('/pr?forge=github&depots=octo/boutique')
    expect(await screen.findByText('Aucun compte GitHub connecté.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeInTheDocument()
  })

  it('le récapitulatif dit ce que chaque PR fera, et rien ne part sans « Envoyer »', async () => {
    const calls = mockApi({ 'GET /api/proposals/pr1': recap(), 'POST /api/proposals/pr1/send': { ...recap(), status: 'running' } })
    const user = userEvent.setup()
    renderApp('/pr/pr1')
    const box = within(await card('octo/boutique'))
    expect(box.getByRole('checkbox', { name: 'Envoyer la PR de octo/boutique' })).toBeChecked()
    expect(box.getByText('nouvelle PR')).toBeInTheDocument()
    expect(box.getByText('lodash')).toBeInTheDocument()
    expect(box.getByText(/4\.17\.15 → 4\.18\.1/)).toBeInTheDocument()
    expect(box.getByText(/régénéré par npm/)).toBeInTheDocument()
    expect(box.getByText('uv absent')).toBeInTheDocument()
    expect(box.getByText(/uv pip compile requirements\.in/)).toBeInTheDocument()
    expect(box.getByRole('link', { name: 'Modifier la sélection de octo/boutique' })).toHaveAttribute(
      'href',
      '/analyses/s-boutique/mise-a-jour?pr=pr1',
    )

    const site = within(await card('octo/site'))
    expect(site.getByText(/met à jour la PR #12/)).toBeInTheDocument()
    expect(site.getByText('analyse non concluante')).toBeInTheDocument()
    expect(site.getByRole('checkbox', { name: 'Envoyer la PR de octo/site' })).not.toBeChecked()
    expect(site.getByText(/left-pad 1\.3\.0/)).toBeInTheDocument()

    const skipped = screen.getByRole('heading', { name: 'Sautés' }).closest('section')!
    expect(within(skipped).getByText('lecture seule : pas de droit de push')).toBeInTheDocument()
    expect(screen.getByText(/3 dépôts, 1 PR à envoyer/)).toBeInTheDocument()
    expect(calls.some((call) => call.method === 'POST')).toBe(false)

    await user.click(site.getByRole('checkbox', { name: 'Envoyer la PR de octo/site' }))
    expect(screen.getByText(/2 PR à envoyer \(dont 1 déjà ouverte, mise à jour\)/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Envoyer 2 PR' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    const send = calls.find((call) => call.method === 'POST')!
    expect(send.url.pathname).toBe('/api/proposals/pr1/send')
    expect(JSON.parse(String(send.init.body))).toEqual({ repositories: ['octo/boutique', 'octo/site'] })
  })

  it('rien de coché, ou hors ligne : pas d’envoi, et pourquoi', async () => {
    mockApi({ 'GET /api/proposals/pr1': recap() })
    const user = userEvent.setup()
    renderApp('/pr/pr1')
    await user.click(await screen.findByRole('checkbox', { name: 'Envoyer la PR de octo/boutique' }))
    expect(screen.getByRole('button', { name: 'Envoyer la PR' })).toBeDisabled()
    expect(screen.getByText('Aucun dépôt coché.')).toBeInTheDocument()
  })

  it('hors ligne : l’envoi attend le réseau', async () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => false })
    mockApi({ 'GET /api/proposals/pr1': recap() })
    renderApp('/pr/pr1')
    expect(await screen.findByRole('button', { name: 'Envoyer la PR' })).toBeDisabled()
    expect(screen.getByText(/Hors ligne\s*: l'envoi attendra le réseau\./)).toBeInTheDocument()
  })

  it('un envoi refusé le dit', async () => {
    mockApi({
      'GET /api/proposals/pr1': recap(),
      'POST /api/proposals/pr1/send': new Status(409, { detail: "git n'est pas installé : il faut git pour cloner." }),
    })
    const user = userEvent.setup()
    renderApp('/pr/pr1')
    await user.click(await screen.findByRole('button', { name: 'Envoyer la PR' }))
    expect(await screen.findByText("git n'est pas installé : il faut git pour cloner.")).toBeInTheDocument()
  })

  it('l’envoi se suit dépôt par dépôt', async () => {
    const running = proposal({
      status: 'running',
      started_at: '2026-10-29T10:01:00+00:00',
      repositories: [
        proposedRepository({ state: 'opened', request: REQUEST, pushed: true }),
        proposedRepository({
          full_name: 'octo/site',
          state: 'sending',
          step: 'updating',
          progress: { kind: 'regenerating', done: 1, total: 2, ecosystem: null, name: 'requirements.txt' },
        }),
        proposedRepository({ full_name: 'octo/docs', state: 'waiting' }),
      ],
    })
    mockApi({ 'GET /api/proposals/pr1': running })
    renderApp('/pr/pr1')
    expect(await screen.findByRole('heading', { level: 1, name: 'Envoi des PR' })).toBeInTheDocument()
    expect(screen.getByText(/Envoi de 3 dépôts\s*: 1 terminé/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Dépôts envoyés' })).toHaveAttribute('aria-valuenow', '1')
    expect(screen.getByText('régénération de requirements.txt (2 sur 2)')).toBeInTheDocument()
    expect(screen.getByText('en attente de son tour')).toBeInTheDocument()
    expect(screen.getByText(/ne s'annule pas/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Retour à mes dépôts' })).not.toBeInTheDocument()
  })

  it('le résultat : les liens des PR, ce qui reste à faire, les échecs', async () => {
    const results = regenerated()
    const done = proposal({
      status: 'done',
      started_at: '2026-10-29T10:01:00+00:00',
      finished_at: '2026-10-29T10:02:00+00:00',
      repositories: [
        proposedRepository({
          state: 'opened',
          request: REQUEST,
          pushed: true,
          committed: ['package.json', 'requirements.in', 'package-lock.json'],
          results: [results[0], { ...results[1], status: 'tool_missing', installed: [] }],
        }),
        proposedRepository({
          full_name: 'octo/site',
          state: 'updated',
          pushed: false,
          request: { ...REQUEST, number: 12, url: 'https://github.com/octo/site/pull/12' },
        }),
        proposedRepository({
          full_name: 'octo/docs',
          state: 'failed',
          error: "GitHub refuse l'accès (403) à /repos/octo/docs/pulls : Resource not accessible by integration.",
        }),
        proposedRepository({ full_name: 'octo/notes', state: 'skipped', reason: "pas coché à l'envoi" }),
      ],
    })
    mockApi({ 'GET /api/proposals/pr1': done, 'GET /api/repositories': repositoryList() })
    renderApp('/pr/pr1')
    expect(await screen.findByRole('heading', { level: 1, name: 'PR envoyées' })).toBeInTheDocument()
    expect(screen.getByText(/1 PR ouverte · 1 mise à jour · 1 en échec/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Voir la PR #41 sur GitHub/ })).toHaveAttribute('href', REQUEST.url)
    expect(screen.getByRole('link', { name: /Voir la PR #12 sur GitHub/ })).toHaveAttribute('target', '_blank')
    // Dans la carte, et dans l'annonce aux lecteurs d'écran.
    expect(screen.getAllByText(/PR #12 mise à jour\s*: elle avait déjà ces changements/)).toHaveLength(2)
    expect(screen.getByText(/requirements\.txt/, { selector: 'span.font-mono' })).toBeInTheDocument()
    expect(screen.getByText(/pas régénéré \(uv absent\)/)).toBeInTheDocument()
    expect(screen.getByText(/Resource not accessible by integration/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Pas envoyés' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Retour à mes dépôts' })).toHaveAttribute('href', '/depots')
  })

  it('un récapitulatif oublié (serveur redémarré) le dit', async () => {
    mockApi({ 'GET /api/proposals/vieux': new Status(404, { detail: 'Récapitulatif inconnu : vieux.' }) })
    renderApp('/pr/vieux')
    expect(await screen.findByRole('heading', { name: 'Récapitulatif introuvable' })).toBeInTheDocument()
  })
})

describe('les PR depuis l’écran 7 et le rapport d’un dépôt', () => {
  const rows = [
    repositoryRow({
      full_name: 'octo/boutique',
      state: 'to_update',
      counts: { vulnerabilities: 3, critical: 0, worst: 'high', to_update: 5, inconclusive: 0, updates: 3 },
      scan: scanSummary({ id: 's-boutique', kind: 'repository', source: 'octo/boutique' }),
      request: REQUEST,
    }),
    repositoryRow({ full_name: 'octo/site', state: 'to_update' }),
    repositoryRow({ full_name: 'atelier/api', can_push: false, state: 'up_to_date' }),
  ]
  const listed = repositoryList({
    accounts: [repositoryAccount({ repositories: 3 })],
    repositories: rows,
    synthesis: synthesis({ repositories: 3, to_update: 2, up_to_date: 1, analyzed: 3, open_requests: 1 }),
  })

  it('la colonne PR, le compteur des PR ouvertes, « Préparer N PR »', async () => {
    const calls = mockApi({ 'GET /api/repositories': listed, 'POST /api/proposals': recap(), 'GET /api/proposals/pr1': recap() })
    const user = userEvent.setup()
    renderApp('/depots')
    const link = await screen.findByRole('link', { name: 'PR #41 de octo/boutique sur GitHub (nouvel onglet)' })
    expect(link).toHaveAttribute('href', REQUEST.url)
    expect(screen.getByText('pas de droit de push')).toBeInTheDocument()
    const stat = screen.getByText('PR ouvertes').closest('div')!
    expect(within(stat).getByText('1')).toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: 'Sélectionner octo/boutique' }))
    await user.click(screen.getByRole('checkbox', { name: 'Sélectionner octo/site' }))
    expect(screen.getByRole('button', { name: 'Analyser ces 2 dépôts' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Préparer 2 PR' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Préparer les PR' })).toBeInTheDocument()
    const post = calls.find((call) => call.method === 'POST')!
    expect(JSON.parse(String(post.init.body)).repositories.map((item: { repository: string }) => item.repository)).toEqual([
      'octo/boutique',
      'octo/site',
    ])
  })

  const repoScan = scanDetail({
    id: 's-boutique',
    kind: 'repository',
    source: 'octo/boutique',
    repository: {
      forge: 'github',
      host: 'github.com',
      full_name: 'octo/boutique',
      url: 'https://github.com/octo/boutique',
      commit: 'abc1234def5678abc1234def5678abc1234def56',
      truncated: false,
      cloned: false,
    },
    report: VULNERABLE,
  })

  it('le rapport d’un dépôt propose « Préparer la PR »', async () => {
    mockApi({ 'GET /api/scans/s-boutique': repoScan })
    renderApp('/analyses/s-boutique')
    const prepare = await screen.findByRole('link', { name: /Préparer la PR/ })
    expect(prepare).toHaveAttribute('href', '/analyses/s-boutique/mise-a-jour')
    expect(screen.queryByRole('link', { name: /Mettre à jour/ })).not.toBeInTheDocument()
  })

  it('choisir la sélection d’un dépôt prépare le récapitulatif de sa PR', async () => {
    const calls = mockApi({
      'GET /api/scans/s-boutique': repoScan,
      'POST /api/proposals': recap(),
      'GET /api/proposals/pr1': recap(),
    })
    const user = userEvent.setup()
    renderApp('/analyses/s-boutique/mise-a-jour')
    expect(await screen.findByRole('heading', { level: 1, name: /Préparer la PR de\s*octo\/boutique/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Mes dépôts' })).toHaveAttribute('href', '/depots')
    expect(screen.getByText(/Rien n'est poussé à cette étape/)).toBeInTheDocument()
    await user.click(screen.getAllByRole('button', { name: 'Préparer la PR' })[0])
    expect(await screen.findByRole('heading', { level: 1, name: 'Préparer les PR' })).toBeInTheDocument()
    const body = JSON.parse(String(calls.find((call) => call.method === 'POST')!.init.body))
    expect(body.forge).toBe('github')
    expect(body.repositories).toEqual([
      { repository: 'octo/boutique', selection: { '.|npm|lodash': '4.18.1', '.|PyPI|flask': '0.12.5', '.|PyPI|jinja2|2.10': '2.11.3' } },
    ])
  })

  it('« Modifier la sélection » garde les autres dépôts du récapitulatif', async () => {
    const calls = mockApi({
      'GET /api/scans/s-boutique': repoScan,
      'GET /api/proposals/pr1': recap(),
      'POST /api/proposals': recap(),
    })
    const user = userEvent.setup()
    renderApp('/analyses/s-boutique/mise-a-jour?pr=pr1')
    await user.click(await screen.findByRole('checkbox', { name: /lodash/ }))
    await user.click(screen.getAllByRole('button', { name: 'Préparer la PR' })[0])
    await screen.findByRole('heading', { level: 1, name: 'Préparer les PR' })
    const body = JSON.parse(String(calls.find((call) => call.method === 'POST')!.init.body))
    expect(body.repositories.map((item: { repository: string }) => item.repository)).toEqual([
      'octo/site',
      'atelier/api',
      'octo/boutique',
    ])
    expect(body.repositories[1].selection).toBeNull() // sauté : sélection par défaut
    expect(body.repositories[2].selection).not.toHaveProperty('.|npm|lodash')
  })
})
