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
  closed_at: null,
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

/**
 * Le titre « Préparer les PR », une fois préparé le récapitulatif : la préparation
 * (`/pr?depots=…`) le montre, puis passe à `/pr/{id}`, qui le rend de nouveau. Un `findByRole`
 * peut tenir l'ancien titre, détaché juste après : l'assertion se refait jusqu'à ce qu'il tienne.
 */
async function prepared() {
  await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: 'Préparer les PR' })).toBeInTheDocument())
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
    renderApp('/pr?depots=github:github.com/octo/boutique,github:github.com/octo/site,gitlab:gitlab.com/atelier/web/api')
    await prepared()
    const posts = calls.filter((call) => call.method === 'POST')
    expect(posts).toHaveLength(1)
    expect(JSON.parse(String(posts[0].init.body))).toEqual({
      repositories: [
        { forge: 'github', host: 'github.com', full_name: 'octo/boutique', selection: null },
        { forge: 'github', host: 'github.com', full_name: 'octo/site', selection: null },
        { forge: 'gitlab', host: 'gitlab.com', full_name: 'atelier/web/api', selection: null },
      ],
    })
  })

  it('un récapitulatif refusé le dit, avec « Réessayer »', async () => {
    mockApi({ 'POST /api/proposals': new Status(404, { detail: 'Aucun compte GitHub connecté.' }) })
    renderApp('/pr?depots=github:github.com/octo/boutique')
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
    expect(JSON.parse(String(send.init.body))).toEqual({ repositories: [{ forge: 'github', host: 'github.com', full_name: 'octo/boutique' }, { forge: 'github', host: 'github.com', full_name: 'octo/site' }] })
  })

  it('une PR fermée sans fusion : dite avec son lien, pas cochée, l’envoyer en ouvre une nouvelle', async () => {
    const closed = { ...REQUEST, number: 3, url: 'https://github.com/octo/boutique/pull/3', closed_at: '2026-10-30T08:00:00Z' }
    const calls = mockApi({
      'GET /api/proposals/pr1': proposal({ repositories: [proposedRepository({ closed, checked: false })] }),
      'POST /api/proposals/pr1/send': proposal({ status: 'running' }),
    })
    const user = userEvent.setup()
    renderApp('/pr/pr1')
    const box = within(await card('octo/boutique'))
    expect(box.getByText(/PR\s#3 fermée sans fusion/, { selector: '[data-slot="badge"]' })).toBeInTheDocument()
    expect(box.getByText('nouvelle PR')).toBeInTheDocument()
    expect(box.getByText(/La PR\s#3 a été fermée sans fusion le 30\soct\.\s2026\s: l'envoyer en ouvre une nouvelle\. Pas cochée par défaut\./)).toBeInTheDocument()
    expect(box.getByRole('link', { name: /Voir la PR #3 sur GitHub/ })).toHaveAttribute('href', 'https://github.com/octo/boutique/pull/3')
    const checkbox = box.getByRole('checkbox', { name: 'Envoyer la PR de octo/boutique' })
    expect(checkbox).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Envoyer la PR' })).toBeDisabled()
    await user.click(checkbox)
    await user.click(screen.getByRole('button', { name: 'Envoyer la PR' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
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

  it('rien de poussé parce que les versions sont retenues : le résultat dit par qui (session 36)', async () => {
    // Le cas de mew : des indirectes dont la correction est une majeure que leur parent refuse ;
    // npm régénère le lockfile à l'identique, rien n'est commité.
    const held = (update: string, versions: string[], by: string[]) => ({
      update,
      version: versions[versions.length - 1],
      versions,
      reach: 'below' as const,
      held_by: by,
    })
    const done = proposal({
      status: 'done',
      started_at: '2026-11-03T13:30:00+00:00',
      finished_at: '2026-11-03T13:31:00+00:00',
      repositories: [
        proposedRepository({
          full_name: 'octo/mew',
          state: 'nothing',
          applied: [
            { update: 'backend|npm|minimatch|10.2.6', name: 'minimatch', ecosystem: 'npm', project: 'backend', direct: false, current: '10.2.6', version: '11.0.1', gap: 'major', fixes: ['CVE-2026-118764'], held_by: [], refused_by: [], blockers: [] },
            { update: 'backend|npm|basic-ftp|5.3.1', name: 'basic-ftp', ecosystem: 'npm', project: 'backend', direct: false, current: '5.3.1', version: '6.2.1', gap: 'major', fixes: ['CVE-2026-1'], held_by: [], refused_by: [], blockers: [] },
          ],
          results: [
            {
              ...regenerated()[0],
              lockfile: 'backend/package-lock.json',
              installed: [
                held('backend|npm|minimatch|10.2.6', ['10.2.6'], ['nodemon 3.1.14']),
                held('backend|npm|basic-ftp|5.3.1', ['5.3.1'], ['get-uri 6.0.5']),
              ],
            },
          ],
        }),
        proposedRepository({ full_name: 'octo/site', state: 'nothing' }),
      ],
    })
    mockApi({ 'GET /api/proposals/pr1': done, 'GET /api/repositories': repositoryList() })
    renderApp('/pr/pr1')
    expect(await screen.findByRole('heading', { level: 1, name: 'PR envoyées' })).toBeInTheDocument()
    expect(screen.getByText(/1 dépôt aux mises à jour retenues · 1 dépôt sans rien à faire/)).toBeInTheDocument()
    // Dans la carte, et dans l'annonce aux lecteurs d'écran.
    expect(screen.getAllByText(/aucune mise à jour n'a pu se faire/)).toHaveLength(2)
    const list = screen.getByRole('list', { name: 'Mises à jour retenues de octo/mew' })
    const lines = within(list).getAllByRole('listitem').map((line) => line.textContent)
    expect(lines).toEqual([
      'minimatch 10.2.6, pas 11.0.1 (backend) : retenue par nodemon 3.1.14',
      'basic-ftp 5.3.1, pas 6.2.1 (backend) : retenue par get-uri 6.0.5',
    ])
    expect(screen.getByText(/monter ce paquet d'abord, ou forcer sa version/)).toBeInTheDocument()
    // Un dépôt vraiment sans rien à faire garde sa phrase.
    expect(screen.getAllByText(/rien à faire sur la branche par défaut/).length).toBeGreaterThan(0)
  })

  it('une majeure refusée, les notes d’un lockfile refait, une ligne par paquet retenu (session 37)', async () => {
    const minimatch = (current: string) => ({
      update: `frontend|npm|minimatch|${current}`,
      name: 'minimatch',
      ecosystem: 'npm' as const,
      project: 'frontend',
      direct: false,
      current,
      version: '11.0.1',
      gap: 'major' as const,
      fixes: ['CVE-2026-118764'],
      held_by: [],
      refused_by: [],
      blockers: [],
    })
    const done = proposal({
      status: 'done',
      started_at: '2026-11-03T13:30:00+00:00',
      finished_at: '2026-11-03T13:31:00+00:00',
      repositories: [
        proposedRepository({
          full_name: 'octo/forceupdate',
          state: 'updated',
          pushed: true,
          request: REQUEST,
          applied: [
            minimatch('5.1.9'),
            minimatch('10.2.6'),
            { update: 'frontend|npm|typescript', name: 'typescript', ecosystem: 'npm', project: 'frontend', direct: true, current: '5.9.3', version: '7.0.2', gap: 'major', fixes: [], held_by: [], refused_by: [], blockers: [] },
          ],
          lockfiles: [{ ...proposedRepository().lockfiles[0], lockfile: 'frontend/package-lock.json', tool: 'npm' }],
          results: [
            {
              ...regenerated()[0],
              lockfile: 'frontend/package-lock.json',
              installed: [
                { update: 'frontend|npm|minimatch|5.1.9', version: '11.0.1', versions: ['5.1.9', '10.2.6'], reach: 'below', held_by: ['@redocly/openapi-core 1.34.22'] },
                { update: 'frontend|npm|minimatch|10.2.6', version: '11.0.1', versions: ['5.1.9', '10.2.6'], reach: 'below', held_by: ['@ts-morph/common 0.27.0'] },
              ],
              warnings: ["npm refusait le lockfile qu'il venait d'écrire (Missing: @emnapi/wasi-threads@1.2.3 from lock file) : refait par « npm install --ignore-scripts --no-audit --no-fund », sans les scripts du projet, puis relu."],
              dropped: [
                { update: 'frontend|npm|typescript', version: '7.0.2', reason: 'Could not resolve dependency: peer typescript@"^5.x" from openapi-typescript@7.13.0.' },
              ],
            },
          ],
        }),
      ],
    })
    mockApi({ 'GET /api/proposals/pr1': done, 'GET /api/repositories': repositoryList() })
    renderApp('/pr/pr1')
    const refused = await screen.findByRole('list', { name: 'Majeures refusées de octo/forceupdate' })
    expect(refused).toHaveTextContent('typescript 7.0.2 (frontend) : pas faite, npm la refuse')
    expect(refused).toHaveTextContent('peer typescript@"^5.x" from openapi-typescript@7.13.0')
    expect(screen.getByText(/monter d'abord le paquet qui bloque/)).toBeInTheDocument()
    const notes = screen.getByRole('list', { name: 'En route, pour octo/forceupdate' })
    expect(notes).toHaveTextContent("frontend/package-lock.json : npm refusait le lockfile qu'il venait d'écrire")
    // Deux mises à jour de minimatch (une par version installée), une seule ligne.
    const held = within(screen.getByRole('list', { name: 'Mises à jour retenues de octo/forceupdate' })).getAllByRole('listitem')
    expect(held.map((line) => line.textContent)).toEqual([
      'minimatch 5.1.9, 10.2.6, pas 11.0.1 (frontend) : retenue par @redocly/openapi-core 1.34.22, @ts-morph/common 0.27.0',
    ])
  })

  it('au récapitulatif, ce qui retiendra ou fera refuser une version, et la version qui l’accepterait (E37)', async () => {
    const blocker = { peer: false, companion: false, checked: true, held: true }
    const ready = proposal({
      repositories: [
        proposedRepository({
          applied: [
            {
              update: '.|npm|minimatch|10.2.6', name: 'minimatch', ecosystem: 'npm', project: '.', direct: false,
              current: '10.2.6', version: '11.0.1', gap: 'major', fixes: ['CVE-2026-118764'],
              held_by: ['nodemon 3.1.14'], refused_by: [],
              blockers: [{ ...blocker, name: 'nodemon', version: '3.1.14', range: '^10.2.1', accepting: '4.0.1' }],
            },
            {
              update: '.|PyPI|redis', name: 'redis', ecosystem: 'PyPI', project: '.', direct: true,
              current: '5.3.1', version: '8.1.0', gap: 'major', fixes: ['CVE-2026-2'],
              held_by: [], refused_by: ['arq 0.28.0'],
              blockers: [{ ...blocker, held: false, name: 'arq', version: '0.28.0', range: '<6,>=4.2.0', accepting: null }],
            },
          ],
        }),
      ],
    })
    mockApi({ 'GET /api/proposals/pr1': ready, 'GET /api/repositories': repositoryList() })
    renderApp('/pr/pr1')
    expect(await screen.findByText("retenue par nodemon 3.1.14 : monter d'abord nodemon en 4.0.1")).toBeInTheDocument()
    expect(screen.getByText("refusée à cause de arq 0.28.0 : aucune de ses versions ne l'accepte")).toBeInTheDocument()
    // Leurs failles ne sont pas comptées.
    expect(screen.queryByText(/failles? corrigées?/)).not.toBeInTheDocument()
  })

  it('un dépôt en échec se renvoie, avec la même sélection ; l’icône dit l’échec (session 37)', async () => {
    const done = proposal({
      status: 'done',
      started_at: '2026-11-03T13:30:00+00:00',
      finished_at: '2026-11-03T13:31:00+00:00',
      repositories: [
        proposedRepository({
          full_name: 'octo/vulnerable',
          state: 'failed',
          error: "Git n'a pas pu cloner : la forge ne répond pas (réseau, DNS, certificat).",
        }),
      ],
    })
    const calls = mockApi({
      'GET /api/proposals/pr1': done,
      'GET /api/repositories': repositoryList(),
      'POST /api/proposals/pr1/send': proposal({ status: 'running' }),
    })
    const user = userEvent.setup()
    renderApp('/pr/pr1')
    expect(await screen.findByText(/Envoi terminé\s: 1 en échec/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Renvoyer le dépôt en échec' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    const send = calls.find((call) => call.method === 'POST')!
    expect(send.url.pathname).toBe('/api/proposals/pr1/send')
    expect(JSON.parse(String(send.init.body))).toEqual({
      repositories: [{ forge: 'github', host: 'github.com', full_name: 'octo/vulnerable' }],
    })
  })

  it('un dépôt sauté sans rien de coché mène au choix de ses mises à jour (session 37)', async () => {
    // La PR d'avant fusionnée : il ne reste que des majeures, jamais pré-cochées.
    const empty = proposal({
      repositories: [
        proposedRepository({ full_name: 'octo/demo', scan: 's-demo', state: 'skipped', reason: 'aucune mise à jour cochée', checked: false }),
      ],
    })
    mockApi({ 'GET /api/proposals/pr1': empty, 'GET /api/repositories': repositoryList() })
    renderApp('/pr/pr1')
    const link = await screen.findByRole('link', { name: 'Choisir les mises à jour de octo/demo' })
    expect(link).toHaveAttribute('href', '/analyses/s-demo/mise-a-jour?pr=pr1')
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
    await prepared()
    const post = calls.find((call) => call.method === 'POST')!
    expect(JSON.parse(String(post.init.body)).repositories.map((item: { full_name: string }) => item.full_name)).toEqual([
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
    await prepared()
    const body = JSON.parse(String(calls.find((call) => call.method === 'POST')!.init.body))
    expect(body.repositories).toEqual([
      {
        forge: 'github',
        host: 'github.com',
        full_name: 'octo/boutique',
        selection: { '.|npm|lodash': '4.18.1', '.|PyPI|flask': '0.12.5', '.|PyPI|jinja2|2.10': '2.11.3' },
      },
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
    expect(body.repositories.map((item: { full_name: string }) => item.full_name)).toEqual([
      'octo/site',
      'atelier/api',
      'octo/boutique',
    ])
    expect(body.repositories[1].selection).toBeNull() // sauté : sélection par défaut
    expect(body.repositories[2].selection).not.toHaveProperty('.|npm|lodash')
  })
})

describe('GitLab : des MR, et des récapitulatifs à plusieurs forges', () => {
  const MR = {
    number: 12,
    url: 'https://gitlab.com/groupe/web/app/-/merge_requests/12',
    title: 'Mise à jour des dépendances (forceupdate)',
    branch: 'forceupdate/dependencies',
    base: 'main',
    closed_at: null,
  }
  const gitlabRow = (overrides: Parameters<typeof repositoryRow>[0] = {}) =>
    repositoryRow({
      forge: 'gitlab',
      host: 'gitlab.com',
      full_name: 'groupe/web/app',
      owner: 'groupe/web',
      name: 'app',
      url: 'https://gitlab.com/groupe/web/app',
      state: 'to_update',
      ...overrides,
    })
  const mixed = repositoryList({
    accounts: [
      repositoryAccount({ repositories: 1 }),
      repositoryAccount({ forge: 'gitlab', host: 'gitlab.com', login: 'renard', repositories: 2 }),
    ],
    repositories: [
      repositoryRow({ full_name: 'octo/boutique', state: 'to_update' }),
      gitlabRow({ request: MR }),
      gitlabRow({ host: 'git.example.com', full_name: 'equipe/outil', owner: 'equipe', name: 'outil', url: 'https://git.example.com/equipe/outil' }),
    ],
    synthesis: synthesis({ repositories: 3, to_update: 3, analyzed: 3, open_requests: 1 }),
  })

  it('l’écran 7 : la colonne PR / MR, le compteur, « Préparer 1 PR et 1 MR »', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
    const calls = mockApi({ 'GET /api/repositories': mixed, 'POST /api/proposals': recap(), 'GET /api/proposals/pr1': recap() })
    const user = userEvent.setup()
    renderApp('/depots')
    const link = await screen.findByRole('link', { name: 'MR !12 de groupe/web/app sur GitLab (nouvel onglet)' })
    expect(link).toHaveAttribute('href', MR.url)
    expect(screen.getByRole('columnheader', { name: 'PR / MR' })).toBeInTheDocument()
    expect(screen.getByText('PR et MR ouvertes')).toBeInTheDocument()
    expect(screen.getAllByText('GitLab (git.example.com)').length).toBeGreaterThan(0)
    expect(screen.getByRole('option', { name: 'GitLab' })).toBeInTheDocument()

    await user.click(screen.getByRole('checkbox', { name: 'Sélectionner octo/boutique' }))
    await user.click(screen.getByRole('checkbox', { name: 'Sélectionner groupe/web/app' }))
    await user.click(screen.getByRole('button', { name: 'Préparer 1 PR et 1 MR' }))
    await screen.findByRole('heading', { level: 1, name: 'Préparer les PR' })
    const post = calls.find((call) => call.method === 'POST')!
    expect(JSON.parse(String(post.init.body)).repositories).toEqual([
      { forge: 'github', host: 'github.com', full_name: 'octo/boutique', selection: null },
      { forge: 'gitlab', host: 'gitlab.com', full_name: 'groupe/web/app', selection: null },
    ])
  })

  it('le même nom sur deux forges : chaque case dit sa forge', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
    mockApi({
      'GET /api/repositories': repositoryList({
        accounts: [repositoryAccount(), repositoryAccount({ forge: 'gitlab', host: 'gitlab.com', login: 'octo' })],
        repositories: [
          repositoryRow({ full_name: 'octo/app' }),
          gitlabRow({ full_name: 'octo/app', owner: 'octo', name: 'app', url: 'https://gitlab.com/octo/app' }),
          repositoryRow({ full_name: 'octo/seul' }),
        ],
      }),
    })
    renderApp('/depots')
    expect(await screen.findByRole('checkbox', { name: 'Sélectionner octo/app (GitHub)' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Sélectionner octo/app (GitLab)' })).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: 'Sélectionner octo/seul' })).toBeInTheDocument()
  })

  function mixedRecap(state: 'ready' | 'opened' = 'ready'): Proposal {
    const sent = state === 'opened'
    return proposal({
      status: sent ? 'done' : 'planned',
      repositories: [
        proposedRepository({ state, request: sent ? REQUEST : null }),
        proposedRepository({
          forge: 'gitlab',
          host: 'gitlab.com',
          full_name: 'groupe/web/app',
          url: 'https://gitlab.com/groupe/web/app',
          scan: 's-app',
          state: sent ? 'opened' : 'ready',
          request: MR,
          pushed: sent,
        }),
      ],
    })
  }

  it('l’écran 8 : un récapitulatif de PR et de MR, puis leur envoi', async () => {
    const calls = mockApi({
      'GET /api/proposals/pr1': mixedRecap(),
      'POST /api/proposals/pr1/send': { ...mixedRecap(), status: 'running' },
    })
    const user = userEvent.setup()
    renderApp('/pr/pr1')
    expect(await screen.findByRole('heading', { level: 1, name: 'Préparer les PR et MR' })).toBeInTheDocument()
    const app = within(await card('groupe/web/app'))
    expect(app.getByRole('checkbox', { name: 'Envoyer la MR de groupe/web/app' })).toBeChecked()
    expect(app.getByText(/met à jour la MR\s!12/)).toBeInTheDocument()
    expect(app.getByText('GitLab')).toBeInTheDocument()
    expect(within(await card('octo/boutique')).getByText('GitHub')).toBeInTheDocument()
    expect(screen.getByText(/2 dépôts, 1 PR et 1 MR à envoyer/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Envoyer 1 PR et 1 MR' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    expect(JSON.parse(String(calls.find((call) => call.method === 'POST')!.init.body))).toEqual({
      repositories: [
        { forge: 'github', host: 'github.com', full_name: 'octo/boutique' },
        { forge: 'gitlab', host: 'gitlab.com', full_name: 'groupe/web/app' },
      ],
    })
  })

  it('le résultat : « 1 PR ouverte · 1 MR ouverte », le lien de chaque', async () => {
    mockApi({ 'GET /api/proposals/pr1': mixedRecap('opened') })
    renderApp('/pr/pr1')
    expect(await screen.findByRole('heading', { level: 1, name: 'PR et MR envoyées' })).toBeInTheDocument()
    expect(screen.getByText(/Envoi terminé : 1 PR ouverte · 1 MR ouverte/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Voir la MR !12 sur GitLab/ })).toHaveAttribute('href', MR.url)
    expect(screen.getByRole('link', { name: /Voir la PR #41 sur GitHub/ })).toHaveAttribute('href', REQUEST.url)
  })
})

describe('Bitbucket : des PR, avec celles de GitHub', () => {
  const PR = {
    number: 3,
    url: 'https://bitbucket.org/ecureuil/app/pull-requests/3',
    title: 'Mise à jour des dépendances (forceupdate)',
    branch: 'forceupdate/dependencies',
    base: 'main',
    closed_at: null,
  }
  const cloudRow = (overrides: Parameters<typeof repositoryRow>[0] = {}) =>
    repositoryRow({
      forge: 'bitbucket',
      host: 'bitbucket.org',
      full_name: 'ecureuil/app',
      owner: 'ecureuil',
      name: 'app',
      url: 'https://bitbucket.org/ecureuil/app',
      state: 'to_update',
      ...overrides,
    })

  it('l’écran 7 : la colonne PR, `#3`, « Préparer 2 PR »', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
    const calls = mockApi({
      'GET /api/repositories': repositoryList({
        accounts: [
          repositoryAccount({ repositories: 1 }),
          repositoryAccount({ forge: 'bitbucket', host: 'bitbucket.org', login: 'ecureuil', repositories: 1, rate_limit: null }),
        ],
        repositories: [repositoryRow({ full_name: 'octo/boutique', state: 'to_update' }), cloudRow({ request: PR })],
        synthesis: synthesis({ repositories: 2, to_update: 2, analyzed: 2, open_requests: 1 }),
      }),
      'POST /api/proposals': recap(),
      'GET /api/proposals/pr1': recap(),
    })
    const user = userEvent.setup()
    renderApp('/depots')
    const link = await screen.findByRole('link', { name: 'PR #3 de ecureuil/app sur Bitbucket (nouvel onglet)' })
    expect(link).toHaveAttribute('href', PR.url)
    expect(screen.getByRole('columnheader', { name: 'PR' })).toBeInTheDocument()
    expect(screen.getByText('PR ouvertes')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Bitbucket' })).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Sélectionner octo/boutique' }))
    await user.click(screen.getByRole('checkbox', { name: 'Sélectionner ecureuil/app' }))
    await user.click(screen.getByRole('button', { name: 'Préparer 2 PR' }))
    await screen.findByRole('heading', { level: 1, name: 'Préparer les PR' })
    const post = calls.find((call) => call.method === 'POST')!
    expect(JSON.parse(String(post.init.body)).repositories).toEqual([
      { forge: 'github', host: 'github.com', full_name: 'octo/boutique', selection: null },
      { forge: 'bitbucket', host: 'bitbucket.org', full_name: 'ecureuil/app', selection: null },
    ])
  })

  it('l’écran 8 : « met à jour la PR #3 », puis le lien vers Bitbucket', async () => {
    const both = (sent: boolean) =>
      proposal({
        status: sent ? 'done' : 'planned',
        repositories: [
          proposedRepository({ state: sent ? 'opened' : 'ready', request: sent ? REQUEST : null }),
          proposedRepository({
            forge: 'bitbucket',
            host: 'bitbucket.org',
            full_name: 'ecureuil/app',
            url: 'https://bitbucket.org/ecureuil/app',
            scan: 's-app',
            state: sent ? 'updated' : 'ready',
            request: PR,
            pushed: sent,
          }),
        ],
      })
    mockApi({ 'GET /api/proposals/pr1': both(false) })
    const view = renderApp('/pr/pr1')
    expect(await screen.findByRole('heading', { level: 1, name: 'Préparer les PR' })).toBeInTheDocument()
    const app = within(await card('ecureuil/app'))
    expect(app.getByRole('checkbox', { name: 'Envoyer la PR de ecureuil/app' })).toBeChecked()
    expect(app.getByText(/met à jour la PR\s#3/)).toBeInTheDocument()
    expect(app.getByText('Bitbucket')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Envoyer 2 PR' })).toBeInTheDocument()
    view.unmount()

    mockApi({ 'GET /api/proposals/pr1': both(true) })
    renderApp('/pr/pr1')
    expect(await screen.findByRole('heading', { level: 1, name: 'PR envoyées' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Voir la PR #3 sur Bitbucket/ })).toHaveAttribute('href', PR.url)
  })
})
