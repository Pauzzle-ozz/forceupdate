import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Status, listing, mockApi, renderApp, scanSummary } from '@/test/api'

const PROJECT = listing({
  path: 'C:/Projets/vulnerable',
  parent: 'C:/Projets',
  entries: [
    { name: '.venv', path: 'C:/Projets/vulnerable/.venv', kind: 'folder', hidden: true },
    { name: 'docs', path: 'C:/Projets/vulnerable/docs', kind: 'folder', hidden: false },
    { name: 'package.json', path: 'C:/Projets/vulnerable/package.json', kind: 'file', hidden: false },
    { name: 'requirements.in', path: 'C:/Projets/vulnerable/requirements.in', kind: 'file', hidden: false },
  ],
})

function folders(path: string | null) {
  if (path === null) return listing({ recent: [{ path: 'C:/Projets/vulnerable', kind: 'folder' }] })
  if (path === 'C:/Projets/vulnerable') return PROJECT
  if (path === 'C:/Projets') {
    return listing({
      path: 'C:/Projets',
      parent: 'C:/',
      entries: [{ name: 'vulnerable', path: 'C:/Projets/vulnerable', kind: 'folder', hidden: false }],
    })
  }
  return new Status(404, { detail: `Le dossier « ${path} » n'existe pas.` })
}

function api() {
  return mockApi({
    'GET /api/fs': ({ url }) => folders(url.searchParams.get('path')),
    'POST /api/scans': scanSummary({ id: 'b1', status: 'running', summary: null, finished_at: null }),
    'GET /api/scans/b1': scanSummary({ id: 'b1', status: 'running', summary: null, finished_at: null }),
  })
}

describe('choisir un dossier ou un fichier (écran 2)', () => {
  it('part des points de départ et des dossiers récents, puis ouvre un dossier', async () => {
    api()
    const user = userEvent.setup()
    renderApp('/choisir?mode=dossier')
    expect(screen.getByRole('heading', { level: 1, name: 'Choisir un dossier' })).toBeInTheDocument()
    const starts = await screen.findByRole('list', { name: 'Points de départ' })
    expect(within(starts).getByRole('button', { name: /moi/ })).toHaveTextContent('dossier personnel')
    await user.click(within(starts).getByRole('button', { name: /^vulnerable/ }))
    const list = await screen.findByRole('list', { name: 'Contenu de C:/Projets/vulnerable' })
    // Les éléments cachés sont repliés.
    expect(within(list).queryByText('.venv')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Afficher les éléments cachés (1)' }))
    expect(within(list).getByText('.venv')).toBeInTheDocument()
    expect(screen.getByLabelText('Dossier ouvert')).toHaveValue('C:/Projets/vulnerable')
  })

  it('au clavier : flèches pour parcourir, Retour arrière pour remonter', async () => {
    api()
    const user = userEvent.setup()
    renderApp('/choisir?mode=dossier&chemin=C:/Projets/vulnerable')
    const list = await screen.findByRole('list', { name: 'Contenu de C:/Projets/vulnerable' })
    const buttons = within(list).getAllByRole('button')
    buttons[0].focus()
    await user.keyboard('{ArrowDown}')
    expect(buttons[1]).toHaveFocus()
    await user.keyboard('{End}')
    expect(buttons.at(-1)).toHaveFocus()
    await user.keyboard('{Backspace}')
    expect(await screen.findByRole('list', { name: 'Contenu de C:/Projets' })).toBeInTheDocument()
  })

  it('analyse le dossier ouvert, ou le fichier choisi', async () => {
    const calls = api()
    const user = userEvent.setup()
    renderApp('/choisir?mode=fichier&chemin=C:/Projets/vulnerable')
    await screen.findByRole('list', { name: 'Contenu de C:/Projets/vulnerable' })
    const file = screen.getByRole('button', { name: /requirements\.in/ })
    await user.click(file)
    expect(file).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: 'Analyser ce fichier' }))
    const post = calls.find((call) => call.method === 'POST')!
    expect(JSON.parse(String(post.init.body)).path).toBe('C:/Projets/vulnerable/requirements.in')
    expect(await screen.findByRole('heading', { name: /Analyse de vulnerable/ })).toBeInTheDocument()
  })

  it('un fichier de code se choisit aussi (E28), compté à part', async () => {
    const calls = mockApi({
      'GET /api/fs': listing({
        path: 'C:/Projets/scripts',
        parent: 'C:/Projets',
        entries: [
          { name: 'helpers.py', path: 'C:/Projets/scripts/helpers.py', kind: 'code', hidden: false },
          { name: 'imports.py', path: 'C:/Projets/scripts/imports.py', kind: 'code', hidden: false },
          { name: 'requirements.txt', path: 'C:/Projets/scripts/requirements.txt', kind: 'file', hidden: false },
        ],
      }),
      'POST /api/scans': scanSummary({ id: 'b1', status: 'running', summary: null, finished_at: null }),
      'GET /api/scans/b1': scanSummary({ id: 'b1', status: 'running', summary: null, finished_at: null }),
    })
    const user = userEvent.setup()
    renderApp('/choisir?mode=fichier&chemin=C:/Projets/scripts')
    await screen.findByRole('list', { name: 'Contenu de C:/Projets/scripts' })
    expect(screen.getByText(/0 dossier, 1 fichier de dépendances/)).toHaveTextContent(
      '0 dossier, 1 fichier de dépendances, 2 fichiers de code',
    )
    const script = screen.getByRole('button', { name: /imports\.py/ })
    await user.click(script)
    expect(script).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: 'Analyser ce fichier' }))
    const post = calls.find((call) => call.method === 'POST')!
    expect(JSON.parse(String(post.init.body)).path).toBe('C:/Projets/scripts/imports.py')
  })

  it('un chemin qui n’existe pas : l’alerte, et le chemin reste éditable', async () => {
    api()
    const user = userEvent.setup()
    renderApp('/choisir?mode=dossier')
    const field = await screen.findByLabelText('Dossier ouvert')
    await user.type(field, 'D:/rien{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('Le dossier « D:/rien » n\'existe pas.')
    expect(screen.getByLabelText('Dossier ouvert')).toHaveValue('D:/rien')
  })

  it('envoie un fichier choisi, puis suit son analyse', async () => {
    const calls = mockApi({
      'GET /api/fs': listing(),
      'POST /api/files': scanSummary({ id: 'c1', kind: 'upload', source: 'package.json', status: 'running', summary: null }),
      'GET /api/scans/c1': scanSummary({ id: 'c1', kind: 'upload', source: 'package.json', status: 'running', summary: null }),
    })
    const user = userEvent.setup()
    const { container } = renderApp('/choisir?mode=fichier')
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!
    await user.upload(input, new File(['{"dependencies": {}}'], 'package.json', { type: 'application/json' }))
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true))
    const post = calls.find((call) => call.method === 'POST')!
    expect(post.url.searchParams.get('name')).toBe('package.json')
    expect((post.init.headers as Record<string, string>)['Content-Type']).toBe('application/octet-stream')
    expect(await screen.findByRole('heading', { name: /Analyse de package\.json/ })).toBeInTheDocument()
  })

  it('un fichier refusé : la raison et les limites', async () => {
    mockApi({
      'GET /api/fs': listing(),
      'POST /api/files': new Status(413, { detail: 'Fichier trop gros : 2 Mo au plus.' }),
    })
    const user = userEvent.setup()
    const { container } = renderApp('/choisir?mode=fichier')
    await user.upload(container.querySelector<HTMLInputElement>('input[type="file"]')!, new File(['x'], 'package.json'))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Fichier refusé')
    expect(alert).toHaveTextContent('Fichier trop gros : 2 Mo au plus.')
    expect(alert).toHaveTextContent('50 Mo pour un lockfile')
  })

  it('« Parcourir… » ouvre la fenêtre du système, puis le dossier choisi (session 36)', async () => {
    const calls = mockApi({
      'GET /api/fs': ({ url }) => folders(url.searchParams.get('path')),
      'POST /api/fs/pick': { path: 'C:/Projets/vulnerable' },
    })
    const user = userEvent.setup()
    renderApp('/choisir?mode=dossier')
    await screen.findByRole('list', { name: 'Points de départ' })
    await user.click(screen.getByRole('button', { name: 'Parcourir…' }))
    // Le dossier choisi s'ouvre dans la liste, prêt à analyser.
    expect(await screen.findByRole('list', { name: 'Contenu de C:/Projets/vulnerable' })).toBeInTheDocument()
    expect(screen.getByLabelText('Dossier ouvert')).toHaveValue('C:/Projets/vulnerable')
    expect(screen.getByRole('button', { name: 'Analyser ce dossier' })).toBeEnabled()
    const pick = calls.find((call) => call.method === 'POST')!
    expect(pick.url.pathname).toBe('/api/fs/pick')
    // Elle s'ouvre dans le dossier personnel, faute de dossier ouvert.
    expect(JSON.parse(String(pick.init.body))).toEqual({ kind: 'folder', start: 'C:/Users/moi' })
  })

  it('« Parcourir… » pour un fichier : le fichier choisi, dans son dossier', async () => {
    const calls = mockApi({
      'GET /api/fs': ({ url }) => folders(url.searchParams.get('path')),
      'POST /api/fs/pick': { path: 'C:/Projets/vulnerable/package.json' },
    })
    const user = userEvent.setup()
    renderApp('/choisir?mode=fichier&chemin=C:/Projets')
    await screen.findByRole('list', { name: 'Contenu de C:/Projets' })
    await user.click(screen.getByRole('button', { name: 'Parcourir…' }))
    // Le fichier est choisi tout de suite ; son dossier s'ouvre au changement d'adresse, après :
    // attendre sa liste (lire le champ dès le bouton échouait avec jsdom 30).
    expect(await screen.findByRole('list', { name: 'Contenu de C:/Projets/vulnerable' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyser ce fichier' })).toBeInTheDocument()
    expect(screen.getByLabelText('Dossier ouvert')).toHaveValue('C:/Projets/vulnerable')
    const pick = calls.find((call) => call.method === 'POST')!
    expect(JSON.parse(String(pick.init.body))).toEqual({ kind: 'file', start: 'C:/Projets' })
  })

  it('« Parcourir… » annulé ne change rien ; sans fenêtre possible, la raison', async () => {
    mockApi({ 'GET /api/fs': ({ url }) => folders(url.searchParams.get('path')), 'POST /api/fs/pick': { path: null } })
    const user = userEvent.setup()
    const { unmount } = renderApp('/choisir?mode=dossier&chemin=C:/Projets')
    await screen.findByRole('list', { name: 'Contenu de C:/Projets' })
    await user.click(screen.getByRole('button', { name: 'Parcourir…' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Parcourir…' })).toBeEnabled())
    expect(screen.getByLabelText('Dossier ouvert')).toHaveValue('C:/Projets')
    unmount()

    mockApi({
      'GET /api/fs': ({ url }) => folders(url.searchParams.get('path')),
      'POST /api/fs/pick': new Status(503, { detail: "Pas de fenêtre de choix : pas d'affichage." }),
    })
    renderApp('/choisir?mode=dossier')
    await screen.findByRole('list', { name: 'Points de départ' })
    await user.click(screen.getByRole('button', { name: 'Parcourir…' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("Pas de fenêtre de choix : pas d'affichage.")
  })
})
