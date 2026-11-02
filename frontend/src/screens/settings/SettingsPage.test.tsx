import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SettingsRequest } from '@/api/types'
import { Status, mockApi, renderApp, settingsDocument } from '@/test/api'

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  document.documentElement.classList.remove('dark')
})

function body(init: RequestInit): SettingsRequest {
  return JSON.parse(String(init.body)) as SettingsRequest
}

describe('les réglages (écran 9)', () => {
  it('montre les réglages, leurs valeurs par défaut, le cache et le thème', async () => {
    mockApi({})
    renderApp('/reglages')
    expect(screen.getByRole('heading', { level: 1, name: 'Réglages' })).toBeInTheDocument()
    expect(document.title).toBe('Réglages · forceupdate')
    expect(screen.getByLabelText('Chargement des réglages')).toBeInTheDocument()
    const minor = await screen.findByRole('radio', { name: /Correctifs et mineures \(par défaut\)/ })
    expect(minor).toBeChecked()
    expect(screen.getByRole('radio', { name: /^Correctifs 2\.3\.1/ })).not.toBeChecked()
    expect(screen.getByRole('switch', { name: 'Seulement les corrections de failles' })).not.toBeChecked()
    expect(screen.getByRole('switch', { name: "Analyser aussi les dossiers de tests et d'exemples" })).not.toBeChecked()
    const ignore = screen.getByRole('textbox', { name: 'Un par ligne' , description: /Un paquet/ })
    expect(ignore).toHaveValue('')
    expect(screen.getByRole('spinbutton', { name: 'Délai des outils de lockfile' })).toHaveValue(600)
    expect(screen.getByRole('spinbutton', { name: "Délai d'un clone ou d'un push" })).toHaveValue(600)
    expect(screen.getByText(/C:\/Users\/moi\/AppData\/Local\/forceupdate\/forceupdate\.toml/)).toBeInTheDocument()
    const cache = screen.getByRole('region', { name: 'Cache' })
    expect(cache).toHaveTextContent('412 réponses gardées, 3,5 Mo')
    expect(cache).toHaveTextContent(/du 30 oct\. 2026 à \d\d:00 au 2 nov\. 2026 à \d\d:15/)
    expect(screen.getByRole('radio', { name: 'Celui du système (par défaut)' })).toBeChecked()
    // Une seule action principale.
    expect(screen.getByRole('button', { name: 'Enregistrer' })).toHaveClass('bg-primary')
    expect(screen.queryByText('Modifications non enregistrées.')).toBeNull()
  })

  it('enregistre ce qui a été changé', async () => {
    const user = userEvent.setup()
    const calls = mockApi({
      'PUT /api/settings': ({ init }: { init: RequestInit }) => {
        const sent = body(init)
        return settingsDocument({
          values: {
            ...settingsDocument().values,
            ignore: sent.ignore ?? [],
            selection: (sent.selection ?? []).map((rule) => ({
              ecosystem: rule.ecosystem ?? null,
              level: rule.level ?? null,
              security_only: rule.security_only ?? null,
            })),
            include_tests: sent.include_tests ?? false,
            excluded_repositories: sent.excluded_repositories ?? [],
            lock_timeout: sent.lock_timeout ?? 600,
            clone_timeout: sent.clone_timeout ?? 600,
            rust_default_toolchain: sent.rust_default_toolchain ?? false,
          },
        })
      },
    })
    renderApp('/reglages')
    await user.click(await screen.findByRole('radio', { name: /^Correctifs 2\.3\.1/ }))
    expect(screen.getByText('Modifications non enregistrées.')).toBeInTheDocument()
    const ignore = screen.getByRole('textbox', { name: 'Un par ligne', description: /Un paquet/ })
    await user.type(ignore, 'lodash{Enter}{Enter}  django@>=5  ')
    await user.click(screen.getByRole('switch', { name: "Analyser aussi les dossiers de tests et d'exemples" }))
    await user.click(screen.getByText('Régler un écosystème à part'))
    await user.selectOptions(
      screen.getByRole('combobox', { name: 'JavaScript (npm) : seulement les corrections de failles' }),
      'Seulement les failles',
    )
    const repositories = screen.getByRole('textbox', { name: 'Un par ligne', description: /github\.com/ })
    await user.type(repositories, 'github.com/octo/ancien')
    const lock = screen.getByRole('spinbutton', { name: 'Délai des outils de lockfile' })
    await user.clear(lock)
    await user.type(lock, '900')
    await user.click(screen.getByRole('switch', { name: /^Rust\s:\slancer cargo avec ma chaîne d'outils par défaut$/ }))
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))

    await screen.findByText(/Enregistré : vaut pour les analyses et les plans qui suivent\./)
    const put = calls.find((call) => call.method === 'PUT')
    expect(put && body(put.init)).toEqual({
      ignore: ['lodash', 'django@>=5'],
      include_tests: true,
      selection: [
        { ecosystem: null, level: 'patch', security_only: false },
        { ecosystem: 'npm', level: null, security_only: true },
      ],
      excluded_repositories: ['github.com/octo/ancien'],
      lock_timeout: 900,
      clone_timeout: 600,
      rust_default_toolchain: true,
    })
    expect(screen.queryByText('Modifications non enregistrées.')).toBeNull()
  })

  it('une valeur refusée : sous son champ, avec sa ligne, et le focus dessus', async () => {
    const user = userEvent.setup()
    mockApi({
      'PUT /api/settings': new Status(400, {
        detail: "Une valeur est refusée : rien n'est enregistré.",
        fields: [
          {
            field: 'ignore',
            index: 1,
            message: '« deux mots » : un nom de paquet sans espace est attendu (lodash, django@>=5).',
          },
        ],
      }),
    })
    renderApp('/reglages')
    const ignore = await screen.findByRole('textbox', { name: 'Un par ligne', description: /Un paquet/ })
    await user.type(ignore, 'lodash{Enter}{Enter}deux mots')
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("Réglages non enregistrés1 valeur refusée : rien n'est enregistré.")
    expect(ignore).toHaveFocus()
    expect(ignore).toHaveAttribute('aria-invalid', 'true')
    expect(ignore).toHaveAccessibleDescription(/Ligne 3\s:\s« deux mots » : un nom de paquet sans espace/)
  })

  it("un délai qui n'est pas un nombre n'est pas envoyé", async () => {
    const user = userEvent.setup()
    const calls = mockApi({})
    renderApp('/reglages')
    const clone = await screen.findByRole('spinbutton', { name: "Délai d'un clone ou d'un push" })
    await user.clear(clone)
    await user.click(screen.getByRole('button', { name: 'Enregistrer' }))
    expect(clone).toHaveFocus()
    expect(clone).toHaveAccessibleDescription(/Un nombre entier de secondes est attendu\./)
    expect(calls.some((call) => call.method === 'PUT')).toBe(false)
  })

  it('enregistrement impossible : une alerte avec la raison', async () => {
    const user = userEvent.setup()
    mockApi({
      'PUT /api/settings': new Status(409, {
        detail: 'Réglages non enregistrés dans C:/forceupdate.toml : Accès refusé.',
      }),
    })
    renderApp('/reglages')
    await user.click(await screen.findByRole('button', { name: 'Enregistrer' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Réglages non enregistrés dans C:/forceupdate.toml : Accès refusé.',
    )
  })

  it('« Valeurs par défaut » remplit le formulaire, sans enregistrer', async () => {
    const user = userEvent.setup()
    const calls = mockApi({
      'GET /api/settings': settingsDocument({
        values: { ...settingsDocument().values, ignore: ['lodash'], lock_timeout: 60 },
      }),
    })
    renderApp('/reglages')
    const ignore = await screen.findByRole('textbox', { name: 'Un par ligne', description: /Un paquet/ })
    expect(ignore).toHaveValue('lodash')
    await user.click(screen.getByRole('button', { name: 'Valeurs par défaut' }))
    expect(ignore).toHaveValue('')
    expect(screen.getByRole('spinbutton', { name: 'Délai des outils de lockfile' })).toHaveValue(600)
    expect(screen.getByText('Modifications non enregistrées.')).toBeInTheDocument()
    expect(calls.some((call) => call.method === 'PUT')).toBe(false)
  })

  it('les réglages en partie illisibles le disent', async () => {
    mockApi({
      'GET /api/settings': settingsDocument({
        problems: ['forceupdate.toml : lock-timeout : 2 s : entre 10 et 86400 secondes.'],
      }),
    })
    renderApp('/reglages')
    const status = await screen.findByText(/Réglages en partie illisibles/)
    expect(status.closest('[role=status]')).toHaveTextContent('forceupdate.toml : lock-timeout : 2 s')
  })

  it('vide le cache après confirmation', async () => {
    const user = userEvent.setup()
    const cleared = { ...settingsDocument().cache, entries: 0, size: 4096, oldest: null, newest: null }
    const calls = mockApi({ 'DELETE /api/cache': cleared })
    renderApp('/reglages')
    await user.click(await screen.findByRole('button', { name: 'Vider le cache…' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Vider le cache ?' })
    expect(dialog).toHaveTextContent('412 réponses effacées')
    await user.click(within(dialog).getByRole('button', { name: 'Annuler' }))
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    await user.click(screen.getByRole('button', { name: 'Vider le cache…' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Vider le cache' }))
    expect(await screen.findByText(/Cache vidé : la prochaine analyse redemande tout\./)).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Cache' })).toHaveTextContent('Contenuvide')
    expect(screen.getByRole('button', { name: 'Vider le cache…' })).toBeDisabled()
  })

  it('le thème change tout de suite', async () => {
    const user = userEvent.setup()
    mockApi({})
    renderApp('/reglages')
    await user.click(await screen.findByRole('radio', { name: 'Sombre' }))
    expect(document.documentElement).toHaveClass('dark')
    expect(localStorage.getItem('forceupdate-theme')).toBe('dark')
    await user.click(screen.getByRole('radio', { name: 'Clair' }))
    expect(document.documentElement).not.toHaveClass('dark')
  })

  it("l'option « dossiers de tests » de l'accueil suit les réglages", async () => {
    mockApi({
      'GET /api/settings': settingsDocument({ values: { ...settingsDocument().values, include_tests: true } }),
      'GET /api/scans': [],
      'GET /api/fs': { path: null, parent: null, entries: [], recent: [] },
    })
    renderApp('/')
    await waitFor(() =>
      expect(screen.getByLabelText("Analyser aussi les dossiers de tests et d'exemples")).toBeChecked(),
    )
  })
})
