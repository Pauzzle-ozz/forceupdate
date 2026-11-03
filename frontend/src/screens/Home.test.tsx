import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { DOWN, accountList, Status, listing, mockApi, renderApp, scanDetail, scanSummary } from '@/test/api'

describe('l’accueil (écran 1)', () => {
  it('premier lancement : les trois sources, et « Aucune analyse pour l’instant »', async () => {
    mockApi({ 'GET /api/scans': [], 'GET /api/fs': listing() })
    renderApp('/')
    expect(screen.getByRole('heading', { level: 1, name: 'Analyser du code' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Choisir un dossier/ })).toHaveAttribute('href', '/choisir?mode=dossier')
    expect(screen.getByRole('link', { name: 'Choisir un fichier' })).toHaveAttribute('href', '/choisir?mode=fichier')
    expect(screen.getByRole('link', { name: 'Connecter un compte' })).toHaveAttribute('href', '/comptes')
    expect(await screen.findByRole('heading', { name: "Aucune analyse pour l'instant" })).toBeInTheDocument()
    // La navigation : « Analyser » est l'écran courant.
    expect(screen.getByRole('link', { name: 'Analyser' })).toHaveAttribute('aria-current', 'page')
  })

  it('les analyses de la session, avec leurs chiffres, et les chemins récents', async () => {
    mockApi({
      'GET /api/scans': [
        scanSummary({ id: 'a1' }),
        scanSummary({
          id: 'a2',
          source: 'C:/Projets/site',
          status: 'running',
          finished_at: null,
          summary: null,
          progress: { kind: 'package_checked', done: 41, total: 64, ecosystem: 'npm', name: 'lodash' },
        }),
        scanSummary({ id: 'a3', source: 'requirements.in', kind: 'upload', status: 'cancelled', summary: null }),
      ],
      'GET /api/fs': listing({
        recent: [
          { path: 'C:/Projets/vulnerable', kind: 'folder' },
          { path: 'C:/Projets/api/requirements.txt', kind: 'file' },
        ],
      }),
    })
    renderApp('/')
    const session = (await screen.findByRole('heading', { name: 'Cette session' })).parentElement!
    const items = within(session).getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(items[0]).toHaveTextContent('28 failles')
    expect(items[0]).toHaveTextContent('2 plus récentes')
    expect(within(items[0]).getByRole('link', { name: 'Ouvrir le rapport' })).toHaveAttribute('href', '/analyses/a1')
    expect(within(items[1]).getByRole('progressbar', { name: 'Analyse de site' })).toHaveAttribute('aria-valuenow', '41')
    expect(items[1]).toHaveTextContent('en cours · 41 sur 64 paquets')
    expect(within(items[1]).getByRole('link', { name: 'Suivre' })).toBeInTheDocument()
    expect(items[2]).toHaveTextContent('fichier envoyé')
    expect(items[2]).toHaveTextContent('annulée')
    // Un fichier envoyé ne se relance pas : il se redépose.
    expect(within(items[2]).queryByRole('button', { name: 'Relancer' })).toBeNull()

    const chips = screen.getByRole('list', { name: 'Chemins récents, à analyser de nouveau' })
    expect(within(chips).getAllByRole('button').map((button) => button.getAttribute('aria-label'))).toEqual([
      'vulnerable, analyser de nouveau (C:/Projets/vulnerable)',
      'requirements.txt, analyser de nouveau (C:/Projets/api/requirements.txt)',
    ])
  })

  it('un chemin récent relance l’analyse, avec les options par défaut', async () => {
    const calls = mockApi({
      'GET /api/scans': [],
      'GET /api/fs': listing({ recent: [{ path: 'C:/Projets/vulnerable', kind: 'folder' }] }),
      'POST /api/scans': scanSummary({ id: 'b1', status: 'running', summary: null, finished_at: null }),
      'GET /api/scans/b1': scanSummary({ id: 'b1', status: 'running', summary: null, finished_at: null }),
    })
    const user = userEvent.setup()
    renderApp('/')
    await user.click(await screen.findByRole('button', { name: /^vulnerable, analyser de nouveau/ }))
    const post = calls.find((call) => call.method === 'POST')!
    expect(JSON.parse(String(post.init.body))).toEqual({
      path: 'C:/Projets/vulnerable',
      dev: true,
      transitive: false,
      include_tests: false,
      offline: false,
      cache: true,
    })
    expect(await screen.findByRole('heading', { name: /Analyse de vulnerable/ })).toBeInTheDocument()
  })

  it('une analyse déjà finie quand le serveur répond (un fichier seul, quelques ms) : son rapport', async () => {
    // Le résumé de POST /api/scans dit « done », sans le rapport : la page le demande, et ne
    // conclut pas « L'analyse a échoué » (vu par la CI, E35).
    const calls = mockApi({
      'GET /api/scans': [],
      'GET /api/fs': listing(),
      'POST /api/scans': scanSummary({ id: 'b2' }),
      'GET /api/scans/b2': scanDetail({ id: 'b2' }),
    })
    const user = userEvent.setup()
    renderApp('/')
    await user.type(screen.getByLabelText("Chemin absolu d'un dossier ou d'un fichier"), 'C:/Projets/vulnerable')
    await user.click(screen.getByRole('button', { name: 'Analyser' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'vulnerable' })).toBeInTheDocument()
    expect(screen.queryByText("L'analyse a échoué")).not.toBeInTheDocument()
    expect(calls.some((call) => call.method === 'GET' && call.url.pathname === '/api/scans/b2')).toBe(true)
  })

  it('« Ou donner un chemin » : l’erreur du serveur sous le champ', async () => {
    mockApi({
      'GET /api/scans': [],
      'GET /api/fs': listing(),
      'POST /api/scans': new Status(400, { detail: '« projets » : donner un chemin absolu.' }),
    })
    const user = userEvent.setup()
    renderApp('/')
    const field = screen.getByLabelText("Chemin absolu d'un dossier ou d'un fichier")
    await user.type(field, 'projets')
    await user.click(screen.getByRole('button', { name: 'Analyser' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('« projets » : donner un chemin absolu.')
    expect(field).toHaveAttribute('aria-invalid', 'true')
  })

  it('hors ligne : le bandeau, « Hors ligne » dans l’en-tête, et l’option cochée d’office', async () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => false })
    mockApi({ 'GET /api/scans': [], 'GET /api/fs': listing() })
    const user = userEvent.setup()
    renderApp('/')
    expect(screen.getByText('Pas de réseau')).toBeInTheDocument()
    expect(screen.getByText('Hors ligne')).toBeInTheDocument()
    await user.click(screen.getByText("Options d'analyse"))
    const offline = screen.getByRole('switch', { name: /Hors ligne/ })
    expect(offline).toBeChecked()
    expect(offline).toBeDisabled()
  })

  it('serveur arrêté : le bandeau commun, et la liste « indisponible »', async () => {
    mockApi({ 'GET /api/scans': DOWN, 'GET /api/fs': DOWN, 'GET /api/accounts': DOWN })
    renderApp('/')
    expect(await screen.findByText('Le serveur local ne répond plus')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Analyses récentes indisponibles' })).toBeInTheDocument()
  })

  it('session terminée (401) : le bandeau dit d’ouvrir la nouvelle adresse', async () => {
    mockApi({
      'GET /api/scans': new Status(401),
      'GET /api/fs': new Status(401),
      'GET /api/accounts': new Status(401),
    })
    renderApp('/')
    expect(await screen.findByText('Session terminée')).toBeInTheDocument()
    expect(screen.getByText(/son jeton a changé/)).toBeInTheDocument()
  })

  it('« Réessayer » efface le bandeau quand le serveur répond de nouveau', async () => {
    let up = false
    mockApi({
      'GET /api/scans': () => (up ? [] : DOWN),
      'GET /api/fs': () => (up ? listing() : DOWN),
      'GET /api/accounts': () => (up ? accountList() : DOWN),
    })
    const user = userEvent.setup()
    renderApp('/')
    await screen.findByText('Le serveur local ne répond plus')
    up = true
    await user.click(screen.getByRole('button', { name: 'Réessayer' }))
    await waitFor(() => expect(screen.queryByText('Le serveur local ne répond plus')).toBeNull())
    expect(await screen.findByRole('heading', { name: "Aucune analyse pour l'instant" })).toBeInTheDocument()
  })
})
