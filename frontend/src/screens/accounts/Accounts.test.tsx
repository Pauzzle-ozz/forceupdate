import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { browser } from '@/hooks/useAccounts'
import {
  DOWN,
  Status,
  account,
  BITBUCKET_TOKEN_SCOPES,
  accountList,
  bitbucketAccount,
  deviceConnection,
  gitlabAccount,
  mockApi,
  renderApp,
} from '@/test/api'

function github() {
  return screen.getByRole('region', { name: 'GitHub' })
}

function gitlab() {
  return screen.getByRole('region', { name: 'GitLab' })
}

function bitbucket() {
  return screen.getByRole('region', { name: 'Bitbucket' })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('les comptes (écran 6)', () => {
  it('sans compte : GitHub, GitLab et Bitbucket et leurs façons de se connecter', async () => {
    mockApi({})
    renderApp('/comptes')
    expect(await screen.findByRole('heading', { level: 1, name: 'Comptes' })).toBeInTheDocument()
    expect(document.title).toBe('Comptes · forceupdate')
    expect(screen.getByText(/Le token reste dans le trousseau de cet ordinateur/)).toBeInTheDocument()
    const card = await screen.findByRole('region', { name: 'GitHub' })
    expect(within(card).getByText('Non connecté')).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Se connecter avec GitHub' })).toHaveClass('bg-primary')
    expect(within(card).getByRole('heading', { level: 3, name: 'Autres façons de se connecter' })).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Se connecter avec un code' })).not.toHaveClass('bg-primary')
    expect(within(card).getByLabelText('Token GitHub')).toHaveAttribute('type', 'password')
    expect(within(card).getByRole('link', { name: /Créer un token sur github\.com/ })).toHaveAttribute(
      'href',
      'https://github.com/settings/tokens/new?scopes=repo,read:org&description=forceupdate',
    )
    expect(within(card).queryByRole('button', { name: 'Reprendre le compte de gh' })).toBeNull()
    const lab = gitlab()
    expect(within(lab).getByText('Non connecté')).toBeInTheDocument()
    expect(within(lab).getByRole('button', { name: 'Se connecter avec GitLab' })).toHaveClass('bg-primary')
    expect(within(lab).getByText(/y ouvrir des MR\. Portée demandée/)).toBeInTheDocument()
    expect(within(lab).queryByRole('button', { name: 'Se connecter avec un code' })).toBeNull()
    expect(within(lab).getByLabelText('Token GitLab')).toHaveAttribute('type', 'password')
    expect(within(lab).getByRole('link', { name: /Créer un token sur gitlab\.com/ })).toHaveAttribute(
      'href',
      'https://gitlab.com/-/user_settings/personal_access_tokens?name=forceupdate&scopes=api',
    )
    const instances = within(lab).getByRole('group', { name: 'Instances auto-hébergées' })
    expect(within(instances).getByLabelText("Adresse de l'instance")).toHaveAttribute('type', 'url')
    expect(within(instances).getByRole('button', { name: "Connecter l'instance" })).toBeDisabled()
    const cloud = bitbucket()
    expect(within(cloud).getByText('Non connecté')).toBeInTheDocument()
    expect(within(cloud).getByRole('button', { name: 'Se connecter avec Bitbucket' })).toHaveClass('bg-primary')
    expect(within(cloud).queryByRole('button', { name: 'Se connecter avec un code' })).toBeNull()
    expect(within(cloud).queryByRole('group', { name: 'Instances auto-hébergées' })).toBeNull()
    expect(screen.queryByText('Bientôt')).toBeNull()
  })

  it('Bitbucket : un token d’API Atlassian, ses portées, et où le créer', async () => {
    mockApi({})
    renderApp('/comptes')
    await screen.findByRole('region', { name: 'Bitbucket' })
    const cloud = bitbucket()
    expect(within(cloud).getByText(/y ouvrir des PR\. Portées demandées/)).toBeInTheDocument()
    expect(within(cloud).getByLabelText('Token Bitbucket')).toHaveAttribute('type', 'password')
    const help = within(cloud).getByText(/Un token d'API Atlassian avec les portées/)
    for (const scope of BITBUCKET_TOKEN_SCOPES) expect(within(help).getByText(scope)).toBeInTheDocument()
    expect(help).toHaveTextContent(/read:pullrequest:bitbucket\set\swrite:pullrequest:bitbucket/)
    expect(help).toHaveTextContent(/les app passwords ne marchent plus/)
    expect(within(cloud).getByRole('link', { name: /Créer un token sur id\.atlassian\.com/ })).toHaveAttribute(
      'href',
      'https://id.atlassian.com/manage-profile/security/api-tokens',
    )
  })

  it('Bitbucket : se déconnecter ne révoque pas le token, un lien pour retirer l’accès', async () => {
    let connected = true
    mockApi({
      'GET /api/accounts': () => accountList({}, null, {}, { account: connected ? bitbucketAccount() : null }),
      'POST /api/accounts/bitbucket/verify': bitbucketAccount(),
      'DELETE /api/accounts/bitbucket': () => {
        connected = false
        return {
          forge: 'bitbucket',
          host: 'bitbucket.org',
          login: 'ecureuil',
          revoked: false,
          message:
            "Déconnecté de Bitbucket : token effacé de cet ordinateur. Bitbucket ne permet pas de le révoquer d'ici : retirer l'accès de forceupdate dans ses réglages (applications autorisées).",
        }
      },
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    const cloud = await screen.findByRole('region', { name: 'Bitbucket' })
    expect(await within(cloud).findByText('@ecureuil')).toBeInTheDocument()
    expect(within(cloud).getByText('Lecture et PR')).toBeInTheDocument()
    await user.click(within(cloud).getByRole('button', { name: 'Se déconnecter…' }))
    const dialog = screen.getByRole('alertdialog', { name: 'Se déconnecter de Bitbucket ?' })
    expect(dialog).toHaveTextContent("Bitbucket ne permet pas de le révoquer d'ici")
    expect(dialog).not.toHaveTextContent('révoqué auprès de')
    await user.click(within(dialog).getByRole('button', { name: 'Se déconnecter' }))
    const notice = await within(bitbucket()).findByText('Déconnecté de Bitbucket')
    expect(notice.closest('[role="status"]')).toHaveClass('bg-warning-bg')
    expect(within(bitbucket()).getByRole('link', { name: "Retirer l'accès sur bitbucket.org (nouvel onglet)" })).toHaveAttribute(
      'href',
      'https://bitbucket.org/account/settings/app-authorizations/',
    )
  })

  it('« Se connecter avec GitHub » part vers la page d’autorisation', async () => {
    const go = vi.spyOn(browser, 'go').mockImplementation(() => {})
    const url = 'https://github.com/login/oauth/authorize?client_id=x&state=s'
    const calls = mockApi({
      'POST /api/accounts/github/oauth': deviceConnection({ method: 'oauth', authorize_url: url, user_code: null }),
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    await user.click(await screen.findByRole('button', { name: 'Se connecter avec GitHub' }))
    await waitFor(() => expect(go).toHaveBeenCalledWith(url))
    expect(calls.some((call) => call.method === 'POST' && call.url.pathname === '/api/accounts/github/oauth')).toBe(true)
    expect(screen.getByRole('button', { name: 'Ouverture de GitHub…' })).toBeDisabled()
  })

  it('une autorisation refusée par le serveur se dit près du bouton', async () => {
    mockApi({
      'POST /api/accounts/github/oauth': new Status(409, {
        detail: 'GitHub ne revient que vers 127.0.0.1 : ouvrir l’interface par http://127.0.0.1:8765.',
      }),
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    await user.click(await screen.findByRole('button', { name: 'Se connecter avec GitHub' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('GitHub ne revient que vers 127.0.0.1')
  })

  it('device flow : le code en grand, « Copier », le lien, l’attente, « Annuler »', async () => {
    let cancelled = false
    const calls = mockApi({
      'POST /api/accounts/github/device': deviceConnection(),
      'GET /api/accounts/connections/c1': () => deviceConnection({ status: cancelled ? 'cancelled' : 'pending' }),
      'DELETE /api/accounts/connections/c1': () => {
        cancelled = true
        return deviceConnection({ status: 'cancelled' })
      },
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    await user.click(await screen.findByRole('button', { name: 'Se connecter avec un code' }))
    const card = github()
    expect(await within(card).findByText('WDJB-MJHT')).toBeInTheDocument()
    expect(within(card).getByText('Connexion en cours')).toBeInTheDocument()
    await user.click(within(card).getByRole('button', { name: 'Copier le code' }))
    expect(await navigator.clipboard.readText()).toBe('WDJB-MJHT')
    expect(within(card).getByText('Code copié.')).toBeInTheDocument()
    const open = within(card).getByRole('link', { name: 'Ouvrir github.com/login/device (nouvel onglet)' })
    expect(open).toHaveAttribute('href', 'https://github.com/login/device')
    expect(open).toHaveAttribute('target', '_blank')
    expect(within(card).getByRole('progressbar', { name: "En attente de l'autorisation sur GitHub" })).toBeInTheDocument()
    expect(within(card).getByText(/Le code expire à/)).toBeInTheDocument()
    await user.click(within(card).getByRole('button', { name: 'Annuler' }))
    expect(await within(card).findByRole('button', { name: 'Se connecter avec un code' })).toBeInTheDocument()
    expect(within(card).queryByText('WDJB-MJHT')).toBeNull()
    expect(calls.some((call) => call.method === 'DELETE')).toBe(true)
  })

  it('device flow : une fois le code tapé, le compte est connecté', async () => {
    let connected = false
    mockApi({
      'GET /api/accounts': () => accountList({ account: connected ? account({ method: 'device' }) : null }),
      'POST /api/accounts/github/device': deviceConnection(),
      'GET /api/accounts/connections/c1': () => {
        connected = true
        return deviceConnection({ status: 'done', account: account({ method: 'device' }) })
      },
      'POST /api/accounts/github/verify': account({ method: 'device' }),
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    await user.click(await screen.findByRole('button', { name: 'Se connecter avec un code' }))
    const card = github()
    expect(await within(card).findByText('Connecté à GitHub')).toBeInTheDocument()
    expect(within(card).getByText('Compte @octo.')).toBeInTheDocument()
    expect(await within(card).findByText('par un code (device flow)', { exact: false })).toBeInTheDocument()
  })

  it('device flow refusé sur GitHub : l’erreur, et « Réessayer »', async () => {
    mockApi({
      'POST /api/accounts/github/device': deviceConnection(),
      'GET /api/accounts/connections/c1': deviceConnection({ status: 'failed', error: 'Autorisation refusée sur GitHub.' }),
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    await user.click(await screen.findByRole('button', { name: 'Se connecter avec un code' }))
    const alert = await within(github()).findByRole('alert')
    expect(alert).toHaveTextContent('Connexion impossible')
    expect(alert).toHaveTextContent('Autorisation refusée sur GitHub.')
    expect(within(alert).getByRole('button', { name: 'Réessayer' })).toBeEnabled()
  })

  it('un device flow en attente se retrouve après un rechargement', async () => {
    mockApi({
      'GET /api/accounts': accountList({ connection: deviceConnection() }),
      'GET /api/accounts/connections/c1': deviceConnection(),
    })
    renderApp('/comptes')
    expect(await screen.findByText('WDJB-MJHT')).toBeInTheDocument()
  })

  it('retour d’OAuth réussi : « Connecté à GitHub », puis « Fermer »', async () => {
    mockApi({
      'GET /api/accounts': accountList({ account: account() }),
      'GET /api/accounts/connections/c2': deviceConnection({
        id: 'c2',
        method: 'oauth',
        status: 'done',
        user_code: null,
        account: account(),
      }),
      'POST /api/accounts/github/verify': account(),
    })
    const user = userEvent.setup()
    renderApp('/comptes?connexion=c2')
    const card = await screen.findByRole('region', { name: 'GitHub' })
    expect(await within(card).findByText('Connecté à GitHub')).toBeInTheDocument()
    await user.click(within(card).getByRole('button', { name: 'Fermer' }))
    expect(within(card).queryByText('Connecté à GitHub')).toBeNull()
    expect(within(card).getByText('Connecté')).toBeInTheDocument()
  })

  it('retour d’OAuth refusé : la raison, et « Réessayer »', async () => {
    mockApi({
      'GET /api/accounts/connections/c2': deviceConnection({
        id: 'c2',
        method: 'oauth',
        status: 'failed',
        user_code: null,
        error: 'Autorisation refusée sur GitHub.',
      }),
    })
    renderApp('/comptes?connexion=c2')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Autorisation refusée sur GitHub.')
    expect(within(alert).getByRole('button', { name: 'Réessayer' })).toBeInTheDocument()
  })

  it('token collé : masqué, affichable, envoyé, puis effacé du champ', async () => {
    let connected = false
    const calls = mockApi({
      'GET /api/accounts': () => accountList({ account: connected ? account({ method: 'token' }) : null }),
      'POST /api/accounts/github/token': () => {
        connected = true
        return account({ method: 'token' })
      },
      'POST /api/accounts/github/verify': account({ method: 'token' }),
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    const field = await screen.findByLabelText('Token GitHub')
    expect(within(github()).getByRole('button', { name: 'Connecter avec ce token' })).toBeDisabled()
    await user.type(field, 'ghp_secret')
    const toggle = within(github()).getByRole('button', { name: 'Afficher le token' })
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-pressed', 'true')
    expect(field).toHaveAttribute('type', 'text')
    await user.click(within(github()).getByRole('button', { name: 'Connecter avec ce token' }))
    expect(await within(github()).findByText('Connecté à GitHub')).toBeInTheDocument()
    const sent = calls.find((call) => call.url.pathname === '/api/accounts/github/token')
    expect(JSON.parse(String(sent?.init.body))).toEqual({ token: 'ghp_secret', url: null })
    expect(await within(github()).findByText('par un token collé', { exact: false })).toBeInTheDocument()
    expect(screen.queryByDisplayValue('ghp_secret')).toBeNull()
  })

  it('token refusé par GitHub : l’erreur sous le champ', async () => {
    mockApi({
      'POST /api/accounts/github/token': new Status(400, {
        detail: 'GitHub refuse le token (401) : révoqué, expiré, ou mal copié. Se reconnecter.',
      }),
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    const field = await screen.findByLabelText('Token GitHub')
    await user.type(field, 'ghp_faux')
    await user.click(within(github()).getByRole('button', { name: 'Connecter avec ce token' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('GitHub refuse le token (401)')
    expect(field).toHaveAttribute('aria-invalid', 'true')
    expect(field).toHaveAccessibleDescription(expect.stringContaining('GitHub refuse le token'))
  })

  it('gh installé : « Reprendre le compte de gh », et son erreur', async () => {
    mockApi({
      'GET /api/accounts': accountList({ methods: ['oauth', 'device', 'token', 'gh'] }),
      'POST /api/accounts/github/gh': new Status(400, {
        detail: "gh n'est pas connecté à github.com : lancer « gh auth login », ou se connecter autrement.",
      }),
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    await user.click(await screen.findByRole('button', { name: 'Reprendre le compte de gh' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("gh n'est pas connecté à github.com")
  })

  it('sans secret d’application : le code devient l’action principale', async () => {
    mockApi({ 'GET /api/accounts': accountList({ methods: ['device', 'token'] }) })
    renderApp('/comptes')
    expect(await screen.findByRole('button', { name: 'Se connecter avec un code' })).toHaveClass('bg-primary')
    expect(screen.queryByRole('button', { name: 'Se connecter avec GitHub' })).toBeNull()
    expect(screen.getByRole('heading', { level: 3, name: 'Se connecter' })).toBeInTheDocument()
  })

  it('connecté : le compte, ses droits, et une vérification à l’ouverture', async () => {
    const calls = mockApi({
      'GET /api/accounts': accountList({ account: account() }),
      'POST /api/accounts/github/verify': account({ checked_at: new Date().toISOString() }),
    })
    renderApp('/comptes')
    const card = await screen.findByRole('region', { name: 'GitHub' })
    expect(within(card).getByText('Connecté')).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: '@octo (nouvel onglet)' })).toHaveAttribute('href', 'https://github.com/octo')
    expect(within(card).getByText('Octo Cat')).toBeInTheDocument()
    expect(within(card).getByText('Lecture et PR')).toBeInTheDocument()
    expect(within(card).getByText('dépôts publics et privés')).toBeInTheDocument()
    expect(within(card).getByText('repo')).toBeInTheDocument()
    expect(within(card).getByText('read:org')).toBeInTheDocument()
    expect(within(card).getByText(/28 oct\. 2026 à \d\d:30, par autorisation \(OAuth\)/)).toBeInTheDocument()
    await waitFor(() => expect(within(card).getByText('maintenant')).toBeInTheDocument())
    expect(calls.filter((call) => call.url.pathname === '/api/accounts/github/verify')).toHaveLength(1)
    expect(within(card).queryByRole('button', { name: 'Se connecter avec GitHub' })).toBeNull()
  })

  it('token fine-grained : « Droits non vérifiés », en non concluant', async () => {
    const fine = account({
      access: 'unknown',
      scopes: null,
      method: 'token',
      warnings: ['Token fine-grained : GitHub ne dit pas ses droits.'],
    })
    mockApi({ 'GET /api/accounts': accountList({ account: fine }), 'POST /api/accounts/github/verify': fine })
    renderApp('/comptes')
    const card = await screen.findByRole('region', { name: 'GitHub' })
    expect(within(card).getByText('Droits non vérifiés')).toHaveClass('border-dashed')
    expect(within(card).getByText('non données par la forge (token fine-grained)')).toBeInTheDocument()
    expect(within(card).getByText('Token fine-grained : GitHub ne dit pas ses droits.')).toBeInTheDocument()
  })

  it('token révoqué sur GitHub : l’alerte, et « Se reconnecter »', async () => {
    const go = vi.spyOn(browser, 'go').mockImplementation(() => {})
    mockApi({
      'GET /api/accounts': accountList({ account: account() }),
      'POST /api/accounts/github/verify': account({ problem: 'GitHub refuse le token (401) : révoqué, expiré, ou mal copié. Se reconnecter.' }),
      'POST /api/accounts/github/oauth': deviceConnection({ method: 'oauth', authorize_url: 'https://github.com/x', user_code: null }),
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('GitHub refuse le token')
    await user.click(within(alert).getByRole('button', { name: 'Se reconnecter' }))
    await waitFor(() => expect(go).toHaveBeenCalledWith('https://github.com/x'))
  })

  it('GitHub injoignable à la vérification : le compte reste, « Droits non revérifiés »', async () => {
    mockApi({
      'GET /api/accounts': accountList({ account: account() }),
      'POST /api/accounts/github/verify': new Status(502, { detail: 'GitHub ne répond pas : api.github.com injoignable.' }),
    })
    renderApp('/comptes')
    expect(await screen.findByText('Droits non revérifiés')).toBeInTheDocument()
    expect(screen.getByText('GitHub ne répond pas : api.github.com injoignable.')).toBeInTheDocument()
    expect(screen.getByText('Lecture et PR')).toBeInTheDocument()
  })

  it('« Se déconnecter… » demande confirmation, puis dit ce qui a été fait', async () => {
    let connected = true
    const calls = mockApi({
      'GET /api/accounts': () => accountList({ account: connected ? account() : null }),
      'POST /api/accounts/github/verify': account(),
      'DELETE /api/accounts/github': () => {
        connected = false
        return {
          forge: 'github',
          login: 'octo',
          revoked: true,
          message: 'Déconnecté de GitHub : token effacé de cet ordinateur et révoqué.',
        }
      },
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    const disconnect = await screen.findByRole('button', { name: 'Se déconnecter…' })
    expect(disconnect).toHaveClass('text-danger')
    await user.click(disconnect)
    const dialog = screen.getByRole('alertdialog', { name: 'Se déconnecter de GitHub ?' })
    expect(dialog).toHaveTextContent('Le token du compte @octo est effacé du trousseau de cet ordinateur.')
    expect(dialog).toHaveTextContent('Il est aussi révoqué auprès de GitHub.')
    expect(within(dialog).getByRole('button', { name: 'Annuler' })).toHaveFocus()
    await user.click(within(dialog).getByRole('button', { name: 'Annuler' }))
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    await user.click(disconnect)
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Se déconnecter' }))
    const card = github()
    expect(await within(card).findByText('Déconnecté de GitHub')).toBeInTheDocument()
    expect(within(card).getByText('Déconnecté de GitHub : token effacé de cet ordinateur et révoqué.')).toBeInTheDocument()
    expect(await within(card).findByText('Non connecté')).toBeInTheDocument()
  })

  it('un token collé : la confirmation dit qu’il reste valable sur GitHub ; non révoqué : avertissement', async () => {
    mockApi({
      'GET /api/accounts': accountList({ account: account({ method: 'token' }) }),
      'POST /api/accounts/github/verify': account({ method: 'token' }),
      'DELETE /api/accounts/github': {
        forge: 'github',
        login: 'octo',
        revoked: false,
        message: 'Déconnecté de GitHub : token effacé de cet ordinateur, mais GitHub ne l’a pas révoqué.',
      },
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    await user.click(await screen.findByRole('button', { name: 'Se déconnecter…' }))
    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveTextContent('Ce token collé reste valable sur GitHub')
    await user.click(within(dialog).getByRole('button', { name: 'Se déconnecter' }))
    const notice = await within(github()).findByText('Déconnecté de GitHub')
    expect(notice.closest('[role="status"]')).toHaveClass('bg-warning-bg')
  })

  it('hors ligne : les connexions désactivées avec la raison', async () => {
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => false })
    const calls = mockApi({})
    renderApp('/comptes')
    const card = await screen.findByRole('region', { name: 'GitHub' })
    expect(within(card).getByText(/Pas de réseau : GitHub est injoignable/)).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Se connecter avec GitHub' })).toBeDisabled()
    expect(within(card).getByRole('button', { name: 'Se connecter avec un code' })).toBeDisabled()
    expect(calls.some((call) => call.method === 'POST')).toBe(false)
  })

  it('trousseau indisponible : l’alerte, et rien ne se connecte', async () => {
    mockApi({ 'GET /api/accounts': accountList({}, "Aucun trousseau du système n'est utilisable.") })
    renderApp('/comptes')
    expect(await screen.findByRole('heading', { level: 1, name: 'Comptes' })).toBeInTheDocument()
    expect(await screen.findByText('Trousseau indisponible')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Se connecter avec GitHub' })).toBeDisabled()
  })

  it('comptes indisponibles : l’erreur et « Réessayer »', async () => {
    mockApi({ 'GET /api/accounts': new Status(500, { detail: 'Erreur du serveur.' }) })
    renderApp('/comptes')
    expect(await screen.findByText('Comptes indisponibles')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Réessayer' })).toBeInTheDocument()
  })

  it('serveur arrêté : le bandeau commun', async () => {
    mockApi({ 'GET /api/accounts': DOWN })
    renderApp('/comptes')
    expect(await screen.findByText('Le serveur local ne répond plus')).toBeInTheDocument()
  })

  it('l’accueil montre le compte connecté', async () => {
    mockApi({
      'GET /api/accounts': accountList({ account: account() }),
      'GET /api/scans': [],
      'GET /api/fs': { path: null, parent: null, entries: [], truncated: false, home: 'C:/Users/moi', recent: [] },
    })
    renderApp('/')
    expect(await screen.findByText('@octo')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Gérer les comptes' })).toHaveAttribute('href', '/comptes')
  })

  it('GitLab : le compte de gitlab.com et celui d’une instance, chacun ses droits et sa déconnexion', async () => {
    const instance = gitlabAccount({ host: 'git.example.com', method: 'token', warnings: ['Ce token expire le 01/03/2027.'] })
    const calls = mockApi({
      'GET /api/accounts': accountList({}, null, { account: gitlabAccount(), instances: [instance] }),
      'POST /api/accounts/gitlab/verify': ({ url }) => (url.searchParams.get('host') ? instance : gitlabAccount()),
      'DELETE /api/accounts/gitlab': {
        forge: 'gitlab',
        host: 'git.example.com',
        login: 'renard',
        revoked: null,
        message: 'Déconnecté de GitLab (git.example.com) : token effacé de cet ordinateur.',
      },
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    const lab = await screen.findByRole('region', { name: 'GitLab' })
    const profiles = await within(lab).findAllByRole('link', { name: '@renard (nouvel onglet)' })
    expect(profiles.map((link) => link.getAttribute('href'))).toEqual(['https://gitlab.com/renard', 'https://gitlab.com/renard'])
    expect(within(lab).getAllByText('Lecture et MR')).toHaveLength(2)
    const instances = within(lab).getByRole('group', { name: 'Instances auto-hébergées' })
    expect(within(instances).getByRole('heading', { level: 4, name: /git\.example\.com/ })).toBeInTheDocument()
    expect(within(instances).getByText('Ce token expire le 01/03/2027.')).toBeInTheDocument()
    await waitFor(() => {
      const verified = calls.filter((call) => call.url.pathname === '/api/accounts/gitlab/verify')
      expect(verified.map((call) => call.url.searchParams.get('host'))).toEqual(expect.arrayContaining([null, 'git.example.com']))
    })
    const buttons = within(instances).getAllByRole('button', { name: 'Se déconnecter…' })
    await user.click(buttons[0])
    await user.click(await screen.findByRole('button', { name: 'Se déconnecter' }))
    expect(await within(instances).findByText('Déconnecté de GitLab (git.example.com)')).toBeInTheDocument()
    const gone = calls.find((call) => call.method === 'DELETE')
    expect(gone?.url.search).toBe('?host=git.example.com')
  })

  it('une instance GitLab : son adresse et un token, le lien pour créer le token', async () => {
    const calls = mockApi({
      'POST /api/accounts/gitlab/token': gitlabAccount({ host: 'git.example.com', method: 'token' }),
    })
    const user = userEvent.setup()
    renderApp('/comptes')
    const lab = await screen.findByRole('region', { name: 'GitLab' })
    const instances = within(lab).getByRole('group', { name: 'Instances auto-hébergées' })
    await user.type(within(instances).getByLabelText("Adresse de l'instance"), 'https://git.example.com')
    expect(within(instances).getByRole('link', { name: /Créer un token sur git\.example\.com/ })).toHaveAttribute(
      'href',
      'https://git.example.com/-/user_settings/personal_access_tokens?name=forceupdate&scopes=api',
    )
    await user.type(within(instances).getByLabelText("Token de l'instance"), 'glpat-secret')
    await user.click(within(instances).getByRole('button', { name: "Connecter l'instance" }))
    expect(await within(instances).findByText('Connecté à GitLab (git.example.com)')).toBeInTheDocument()
    const sent = calls.find((call) => call.url.pathname === '/api/accounts/gitlab/token')
    expect(JSON.parse(String(sent?.init.body))).toEqual({ token: 'glpat-secret', url: 'https://git.example.com' })
    expect(screen.queryByDisplayValue('glpat-secret')).toBeNull()
  })

  it('le retour d’OAuth de GitLab ne se montre que sur sa carte', async () => {
    mockApi({
      'GET /api/accounts': accountList({}, null, { account: gitlabAccount() }),
      'GET /api/accounts/connections/c9': deviceConnection({
        id: 'c9',
        forge: 'gitlab',
        method: 'oauth',
        status: 'done',
        user_code: null,
        verification_uri: null,
        account: gitlabAccount(),
      }),
      'POST /api/accounts/gitlab/verify': gitlabAccount(),
    })
    renderApp('/comptes?connexion=c9')
    expect(await within(await screen.findByRole('region', { name: 'GitLab' })).findByText('Connecté à GitLab')).toBeInTheDocument()
    expect(within(github()).queryByText(/Connecté à/)).toBeNull()
  })
})
