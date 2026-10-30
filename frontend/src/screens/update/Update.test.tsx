import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Report, UpdatePlan } from '@/api/types'
import { Status, VULNERABLE, mockApi, planDocument, regenerated, renderApp, scanDetail } from '@/test/api'
import { FakeEventSource } from '@/test/events'

const CHOOSE = '/analyses/a1/mise-a-jour'

/** Une ligne du récapitulatif, par son libellé. */
function recapLine(label: string) {
  const aside = screen.getByRole('complementary', { name: 'Récapitulatif' })
  const line = within(aside).getByText(label).closest('li')
  if (!line) throw new Error(label)
  return line
}

function radio(name: string, version: string) {
  return within(screen.getByRole('radiogroup', { name: `Version visée pour ${name}` })).getByRole('radio', {
    name: new RegExp(`^${version.replaceAll('.', '\\.')}\\b`),
  })
}

function event(kind: string, done = 0, total = 0, name: string | null = null) {
  return { kind, done, total, ecosystem: null, name }
}

/** Le rapport de `vulnerable`, avec les cas que le vrai n'a pas : option à la main, faille apportée, notes. */
function specialCases(): Report {
  const report = structuredClone(VULNERABLE)
  const [project] = report.projects
  for (const update of project.updates) {
    if (update.name === 'lodash') {
      const [patch] = update.options
      update.options.unshift({
        ...patch,
        version: '4.17.21',
        fixes: [],
        unfixed: [...patch.fixes, ...patch.unfixed],
        reasons: [],
        manual: "forceupdate ne sait pas réécrire la contrainte de package.json : la modifier soi-même.",
      })
      patch.introduced = ['CVE-2026-0001']
      patch.warnings = ['Faille connue dans cette version : CVE-2026-0001.']
    }
    if (update.name === 'flask') update.note = 'Aucune version corrigée connue pour CVE-2026-0002.'
    if (update.name === 'werkzeug') {
      update.options = []
      update.note = 'Code malveillant (MAL-2026-1) : retirer ce paquet, aucune version sûre connue.'
    }
  }
  return report
}

describe('la mise à jour (écran 5), une indirecte écrite dans le manifeste', () => {
  it('Go : une indirecte (// indirect) se réécrit dans go.mod, pas par le lockfile seul', async () => {
    const report = structuredClone(VULNERABLE)
    const [project] = report.projects
    const lodash = project.updates.find((update) => update.name === 'lodash')!
    const jinja2 = project.updates.find((update) => update.name === 'jinja2')!
    jinja2.options = jinja2.options.map((option) => ({ ...option, edits: lodash.options[0].edits }))
    mockApi({ 'GET /api/scans/a1': scanDetail({ report }) })
    renderApp(CHOOSE)
    const card = await screen.findByRole('article', { name: 'jinja2' })
    expect(card).toHaveTextContent('indirecte')
    expect(card).not.toHaveTextContent('par le lockfile seul')
  })
})

describe('la mise à jour (écran 5), étape Choisir', () => {
  it('groupe les mises à jour par lockfile, pré-coche la sélection proposée, et la compte', async () => {
    mockApi({ 'GET /api/scans/a1': scanDetail() })
    renderApp(CHOOSE)
    expect(await screen.findByRole('heading', { level: 1, name: 'Mettre à jour vulnerable' })).toBeInTheDocument()
    expect(document.title).toBe('Mise à jour · vulnerable · forceupdate')
    const steps = screen.getByRole('list', { name: 'Étapes' })
    expect(within(steps).getByText('Choisir').closest('li')).toHaveAttribute('aria-current', 'step')
    expect(within(steps).getAllByRole('listitem')).toHaveLength(4)

    expect(screen.getAllByRole('heading', { level: 2 }).map((heading) => heading.textContent)).toEqual([
      'npmpackage-lock.json',
      'PyPIrequirements.txt',
      'Récapitulatif',
    ])
    expect(screen.getByRole('checkbox', { name: 'lodash' })).toBeChecked()
    expect(radio('lodash', '4.18.1')).toBeChecked()
    expect(radio('lodash', '4.17.23')).not.toBeChecked()
    expect(radio('flask', '0.12.5')).toBeChecked()
    expect(radio('jinja2', '2.11.3')).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'werkzeug' })).not.toBeChecked()

    const lodash = screen.getByRole('article', { name: 'lodash' })
    expect(lodash).toHaveTextContent('utilisée 4.17.15 · 6 failles')
    expect(lodash).toHaveTextContent('Corrige 4 failles sur 6, en laisse 2')
    expect(lodash).toHaveTextContent('Corrige les 6 failles')
    expect(lodash).toHaveTextContent('package.json :4.17.154.18.1')
    const jinja2 = screen.getByRole('article', { name: 'jinja2' })
    expect(jinja2).toHaveTextContent('par le lockfile seul')
    expect(jinja2).toHaveTextContent('aucun manifeste réécrit : requirements.txt seul')
    expect(jinja2).toHaveTextContent("Dépendance indirecte : le paquet qui la tire devra peut-être monter aussi.")

    expect(recapLine('Mises à jour cochées')).toHaveTextContent('3 sur 4')
    expect(recapLine('Failles corrigées')).toHaveTextContent('9 sur 28')
    expect(recapLine('Failles laissées')).toHaveTextContent('19')
    expect(recapLine('Majeures cochées')).toHaveTextContent('0')
    expect(screen.getByText('package.json, requirements.in')).toBeInTheDocument()
    expect(screen.getByText('package-lock.json, requirements.txt')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Vérifier le plan' })).toBeEnabled()
  })

  it('au plus une option par paquet : choisir, décocher, recocher, tout décocher, revenir à la proposée', async () => {
    mockApi({ 'GET /api/scans/a1': scanDetail() })
    const user = userEvent.setup()
    renderApp(CHOOSE)
    await user.click(await screen.findByRole('radio', { name: /^3\.1\.3\b/ }))
    expect(radio('flask', '0.12.5')).not.toBeChecked()
    expect(recapLine('Majeures cochées')).toHaveTextContent('1')
    expect(recapLine('Failles corrigées')).toHaveTextContent('12 sur 28')
    expect(screen.getByText('Une majeure est cochée')).toBeInTheDocument()

    const lodash = screen.getByRole('checkbox', { name: 'lodash' })
    await user.click(lodash)
    expect(lodash).not.toBeChecked()
    expect(within(screen.getByRole('radiogroup', { name: 'Version visée pour lodash' })).getAllByRole('radio').every((r) => !(r as HTMLInputElement).checked)).toBe(true)
    expect(recapLine('Mises à jour cochées')).toHaveTextContent('2 sur 4')
    await user.click(lodash)
    expect(radio('lodash', '4.18.1')).toBeChecked()

    // Rien de proposé pour werkzeug (une majeure seulement) : le cocher prend sa seule option.
    await user.click(screen.getByRole('checkbox', { name: 'werkzeug' }))
    expect(radio('werkzeug', '3.1.9')).toBeChecked()

    await user.click(screen.getByRole('button', { name: 'Tout décocher' }))
    expect(recapLine('Mises à jour cochées')).toHaveTextContent('0 sur 4')
    expect(screen.getByRole('button', { name: 'Vérifier le plan' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Sélection proposée' }))
    expect(recapLine('Mises à jour cochées')).toHaveTextContent('3 sur 4')
    expect(radio('flask', '0.12.5')).toBeChecked()
  })

  it('montre l’option à faire à la main, la faille apportée et les notes', async () => {
    mockApi({ 'GET /api/scans/a1': scanDetail({ report: specialCases() }) })
    renderApp(CHOOSE)
    const manual = await screen.findByRole('radio', { name: /^4\.17\.21\b/ })
    expect(manual).toBeDisabled()
    expect(manual).toHaveAccessibleDescription(/forceupdate ne sait pas réécrire la contrainte/)
    expect(manual.closest('label')).toHaveTextContent('à faire à la main')
    const brings = screen.getByText('Faille connue dans cette version : CVE-2026-0001.')
    expect(brings).toHaveClass('text-danger')
    expect(screen.getByText('Aucune version corrigée connue pour CVE-2026-0002.')).toBeInTheDocument()

    const werkzeug = screen.getByRole('article', { name: 'werkzeug' })
    expect(within(werkzeug).getByRole('checkbox', { name: 'werkzeug' })).toBeDisabled()
    expect(within(werkzeug).queryByRole('radiogroup')).toBeNull()
    expect(within(werkzeug).getByText(/Code malveillant/)).toHaveClass('text-danger')
    expect(within(werkzeug).getByText('Élevée')).toBeInTheDocument()
    expect(recapLine('Mises à jour cochées')).toHaveTextContent('3 sur 3')
  })

  it('le lien du panneau de détail donne le focus à la carte du paquet', async () => {
    mockApi({ 'GET /api/scans/a1': scanDetail() })
    renderApp(`${CHOOSE}?paquet=${encodeURIComponent('.|PyPI|jinja2|2.10')}`)
    await waitFor(() => expect(screen.getByRole('article', { name: 'jinja2' })).toHaveFocus())
  })

  it('reprend la sélection d’un plan (« Modifier la sélection »)', async () => {
    mockApi({
      'GET /api/scans/a1': scanDetail(),
      'GET /api/updates/p1': planDocument({ selection: { '.|PyPI|flask': '3.1.3' } }),
    })
    renderApp(`${CHOOSE}?plan=p1`)
    expect(await screen.findByRole('radio', { name: /^3\.1\.3\b/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'lodash' })).not.toBeChecked()
    expect(recapLine('Mises à jour cochées')).toHaveTextContent('1 sur 4')
  })

  it('le dit quand il n’y a rien à mettre à jour, ou quand l’analyse est en partie non concluante', async () => {
    const empty = structuredClone(VULNERABLE)
    empty.projects[0].updates = []
    mockApi({ 'GET /api/scans/a1': scanDetail({ report: empty }) })
    const view = renderApp(CHOOSE)
    expect(await screen.findByRole('heading', { name: 'Rien à mettre à jour' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Retour au rapport' })).toHaveAttribute('href', '/analyses/a1')
    view.unmount()

    const partial = structuredClone(VULNERABLE)
    partial.projects[0].notices = [
      { file: 'requirements.txt', message: 'Failles non vérifiées pour 4 versions proposées. OSV : délai dépassé.' },
    ]
    mockApi({ 'GET /api/scans/a1': scanDetail({ report: partial }) })
    renderApp(CHOOSE)
    const alert = await screen.findByText('Analyse en partie non concluante')
    expect(alert.closest('[role="status"]')).toHaveTextContent('Failles non vérifiées pour 4 versions proposées')
    expect(screen.getByRole('button', { name: "Relancer l'analyse d'abord" })).toBeInTheDocument()
  })

  it('« Vérifier le plan » envoie la sélection, puis montre le plan à son adresse', async () => {
    const calls = mockApi({
      'GET /api/scans/a1': scanDetail(),
      'POST /api/updates/plan': planDocument(),
      'GET /api/updates/p1': planDocument(),
    })
    const user = userEvent.setup()
    renderApp(CHOOSE)
    await user.click(await screen.findByRole('button', { name: 'Vérifier le plan' }))
    expect(await screen.findByRole('heading', { name: 'Ce qui sera fait' })).toBeInTheDocument()
    const sent = calls.find((call) => call.method === 'POST')
    expect(JSON.parse(String(sent?.init.body))).toEqual({
      scan: 'a1',
      selection: { '.|npm|lodash': '4.18.1', '.|PyPI|flask': '0.12.5', '.|PyPI|jinja2|2.10': '2.11.3' },
    })
    expect(within(screen.getByRole('list', { name: 'Étapes' })).getByText('Vérifier').closest('li')).toHaveAttribute(
      'aria-current',
      'step',
    )
  })

  it('dit pourquoi le plan est refusé, près du bouton', async () => {
    mockApi({
      'GET /api/scans/a1': scanDetail(),
      'POST /api/updates/plan': new Status(400, { detail: "Lodash : la version 9.9.9 n'est pas proposée." }),
    })
    const user = userEvent.setup()
    renderApp(CHOOSE)
    await user.click(await screen.findByRole('button', { name: 'Vérifier le plan' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("Le plan n'a pas pu être préparé")
    expect(alert).toHaveTextContent("Lodash : la version 9.9.9 n'est pas proposée.")
  })
})

describe('la mise à jour (écran 5), étape Vérifier', () => {
  function withPlan(plan: UpdatePlan, scan = scanDetail()) {
    return mockApi({ 'GET /api/scans/a1': scan, 'GET /api/updates/p1': plan })
  }

  it('montre ce qui sera fait, les diffs, les lockfiles et le garde-fou git', async () => {
    withPlan(planDocument())
    renderApp('/plans/p1')
    const done = await screen.findByRole('heading', { name: 'Ce qui sera fait' })
    const list = done.parentElement?.querySelector('ul')
    expect(list).toHaveTextContent('flask0.120.12.5requirements.in, requirements.txt')
    expect(list).toHaveTextContent('jinja22.102.11.3requirements.txt seul')
    expect(list).toHaveTextContent('lodash4.17.154.18.1package.json, package-lock.json')

    const diff = screen.getByRole('region', { name: 'Diff de package.json' })
    expect(diff).toHaveAttribute('tabindex', '0')
    expect(within(diff).getAllByRole('row')).toHaveLength(8)
    expect(screen.getAllByText(/^1\sligne ajoutée, 1\sretirée$/)).toHaveLength(2)

    expect(screen.getByText('npm trouvé')).toBeInTheDocument()
    expect(screen.getByText('uv trouvé')).toBeInTheDocument()
    expect(screen.getByText('npm install --package-lock-only --ignore-scripts')).toBeInTheDocument()
    expect(screen.getByText(/Pas repris de l'en-tête de requirements\.txt/)).toBeInTheDocument()
    expect(screen.getByText('Git peut tout défaire')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Appliquer' })).toBeEnabled()
    expect(screen.getByRole('link', { name: 'Modifier la sélection' })).toHaveAttribute('href', '/analyses/a1/mise-a-jour?plan=p1')
  })

  it('les garde-fous : hors de git, outil absent, hors ligne, option sautée', async () => {
    const plan = planDocument({
      uncommitted: null,
      skipped: [{ update: '.|PyPI|flask', version: '0.12.5', reason: 'ligne à --hash : à faire à la main' }],
    })
    plan.lockfiles[1].available = false
    Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => false })
    withPlan(plan)
    renderApp('/plans/p1')
    expect(await screen.findByText("Hors d'un dépôt git")).toBeInTheDocument()
    expect(screen.getByText('uv absent')).toBeInTheDocument()
    expect(screen.getByText(/uv n'est pas installé/).closest('p')).toHaveTextContent('lancer ensuite cette commande dans C:/Projets/vulnerable')
    const action = screen.getByRole('complementary', { name: 'Appliquer' })
    expect(within(action).getByText('Lockfiles régénérés').closest('li')).toHaveTextContent('1 (et 1 commande)')
    expect(screen.getByText('Pas de réseau').closest('[role="status"]')).toHaveTextContent('npm en a besoin')
    expect(screen.getByRole('heading', { name: 'Pas appliqué' }).parentElement).toHaveTextContent(
      'flask 0.12.5 : ligne à --hash : à faire à la main',
    )
  })

  it('des changements non commités : « Appliquer quand même… », confirmé, avec force', async () => {
    const calls = mockApi({
      'GET /api/scans/a1': scanDetail(),
      'GET /api/updates/p1': planDocument({ uncommitted: ['requirements.in'] }),
      'POST /api/updates/apply': planDocument({ status: 'running', uncommitted: ['requirements.in'], applicable: false }),
    })
    const user = userEvent.setup()
    renderApp('/plans/p1')
    expect(await screen.findByText('Changements pas encore commités')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Appliquer' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Appliquer quand même…' }))
    const dialog = screen.getByRole('alertdialog', { name: /Appliquer malgré les changements non commités/ })
    expect(dialog).toHaveAccessibleDescription(/par-dessus les changements en attente de requirements\.in/)
    expect(within(dialog).getByRole('button', { name: 'Annuler' })).toHaveFocus()
    await user.click(within(dialog).getByRole('button', { name: 'Annuler' }))
    expect(dialog).not.toHaveAttribute('open')
    expect(calls.some((call) => call.method === 'POST')).toBe(false)

    await user.click(screen.getByRole('button', { name: 'Appliquer quand même…' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Appliquer quand même' }))
    expect(await screen.findByRole('heading', { name: 'Application en cours' })).toBeInTheDocument()
    const post = calls.find((call) => call.method === 'POST')
    expect(JSON.parse(String(post?.init.body))).toEqual({ plan: 'p1', force: true })
  })

  it('un 409 en appliquant : le message, et le plan relu montre le garde-fou', async () => {
    let plan = planDocument()
    mockApi({
      'GET /api/scans/a1': scanDetail(),
      'GET /api/updates/p1': () => plan,
      'POST /api/updates/apply': () => {
        plan = planDocument({ uncommitted: ['requirements.in'] })
        return new Status(409, {
          detail: "requirements.in : des changements que git n'a pas en commit. Les commiter (ou les mettre de côté) d'abord, ou appliquer avec « force ».",
        })
      },
    })
    const user = userEvent.setup()
    renderApp('/plans/p1')
    await user.click(await screen.findByRole('button', { name: 'Appliquer' }))
    expect(await screen.findByRole('button', { name: 'Appliquer quand même…' })).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent("des changements que git n'a pas en commit")
  })

  it('un plan échoué (fichier changé depuis le diff) : rien n’a été écrit', async () => {
    withPlan(
      planDocument({
        status: 'failed',
        applicable: false,
        error: "requirements.in a changé depuis le calcul du diff : rien n'est écrit, relancer la mise à jour.",
      }),
    )
    renderApp('/plans/p1')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent("Rien n'a été écrit")
    expect(alert).toHaveTextContent('requirements.in a changé depuis le calcul du diff')
    expect(within(alert).getByRole('button', { name: "Relancer l'analyse" })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Appliquer' })).toBeDisabled()
  })

  it('un fichier envoyé : deux étapes, et « Télécharger » au lieu d’« Appliquer »', async () => {
    withPlan(
      planDocument({ files: [planDocument().files[1]], lockfiles: [], uncommitted: null, applicable: false }),
      scanDetail({ kind: 'upload', source: 'requirements.in' }),
    )
    renderApp('/plans/p1')
    expect(await screen.findByRole('heading', { level: 1, name: 'Mettre à jour requirements.in' })).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Étapes' })).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText(/Fichier envoyé/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Télécharger requirements.in' })).toHaveAttribute(
      'href',
      '/api/updates/p1/files/requirements.in',
    )
    expect(screen.queryByRole('button', { name: /^Appliquer/ })).toBeNull()
    expect(screen.queryByText("Hors d'un dépôt git")).toBeNull()
    expect(screen.queryByRole('heading', { name: 'Lockfiles régénérés' })).toBeNull()
  })

  it('un plan oublié par le serveur', async () => {
    mockApi({ 'GET /api/updates/p9': new Status(404, { detail: 'Plan inconnu.' }) })
    renderApp('/plans/p9')
    expect(await screen.findByRole('heading', { level: 1, name: "Ce plan n'existe plus" })).toBeInTheDocument()
  })
})

describe('la mise à jour (écran 5), étapes Appliquer et Résultat', () => {
  it('suit l’application, ferme le flux à « end », puis montre le résultat', async () => {
    let plan = planDocument()
    const calls = mockApi({
      'GET /api/scans/a1': scanDetail(),
      'GET /api/updates/p1': () => plan,
      'POST /api/updates/apply': () => {
        plan = planDocument({ status: 'running', applicable: false })
        return plan
      },
    })
    const user = userEvent.setup()
    renderApp('/plans/p1')
    await user.click(await screen.findByRole('button', { name: 'Appliquer' }))
    expect(JSON.parse(String(calls.find((call) => call.method === 'POST')?.init.body))).toEqual({ plan: 'p1', force: false })

    const title = await screen.findByRole('heading', { name: 'Application en cours' })
    expect(title).toHaveFocus()
    expect(screen.queryByRole('button', { name: /Annuler/ })).toBeNull()
    expect(screen.getByText(/ne s'interrompt pas/)).toBeInTheDocument()
    const blade = screen.getByRole('progressbar', { name: 'Lockfiles régénérés' })
    expect(blade).not.toHaveAttribute('aria-valuenow')

    const source = FakeEventSource.last('/api/updates/p1/events')
    act(() => {
      source.emit('progress', event('written', 0, 2))
      source.emit('progress', event('regenerating', 0, 2, 'package-lock.json'))
    })
    expect(screen.getByText('Manifestes réécrits', { exact: false })).toBeInTheDocument()
    expect(blade).toHaveAttribute('aria-valuenow', '0')
    expect(blade).toHaveAttribute('aria-valuemax', '2')
    expect(screen.getByText('1 sur 2')).toBeInTheDocument()
    expect(screen.getByText('Régénération de package-lock.json par npm.')).toBeInTheDocument()

    act(() => source.emit('progress', event('regenerating', 1, 2, 'requirements.txt')))
    expect(screen.getByText('package-lock.json').closest('li')).toHaveTextContent('package-lock.json régénéré par npm (fait)')
    expect(screen.getByText('2 sur 2')).toBeInTheDocument()

    plan = planDocument({ status: 'done', applicable: false, results: regenerated(), finished_at: '2026-10-28T17:32:00+00:00' })
    act(() => {
      source.emit('progress', event('finished'))
      source.emit('end', { status: 'done', error: null })
    })
    expect(source.closed).toBe(true)
    const outcome = await screen.findByText('Mise à jour appliquée')
    expect(outcome.closest('[role="status"]')).toHaveFocus()
    expect(outcome.closest('[role="status"]')).toHaveTextContent('3 mises à jour, toutes à la version demandée.')
    expect(screen.getAllByText('version exacte')).toHaveLength(3)
    expect(screen.getAllByText("Rien d'autre n'a changé dans le lockfile.")).toHaveLength(2)
    expect(screen.getByRole('button', { name: "Relancer l'analyse" })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: "Revoir l'ancien rapport" })).toHaveAttribute('href', '/analyses/a1')
  })

  it('Go : les autres changements sont relus dans go.mod', async () => {
    const plan = planDocument({ status: 'done', applicable: false, results: regenerated() })
    plan.lockfiles[0] = { ...plan.lockfiles[0], kind: 'go', tool: 'Go' }
    mockApi({ 'GET /api/scans/a1': scanDetail(), 'GET /api/updates/p1': plan })
    renderApp('/plans/p1')
    await screen.findByText('Mise à jour appliquée')
    expect(screen.getByText("Rien d'autre n'a changé dans go.mod.")).toBeInTheDocument()
    expect(screen.getByText("Rien d'autre n'a changé dans le lockfile.")).toBeInTheDocument()
  })

  it('une commande reste à lancer : la copier', async () => {
    const plan = planDocument({ status: 'done', applicable: false })
    plan.lockfiles[1].available = false
    const results = regenerated()
    results[1] = { ...results[1], status: 'tool_missing', installed: [] }
    plan.results = results
    mockApi({ 'GET /api/scans/a1': scanDetail(), 'GET /api/updates/p1': plan })
    const user = userEvent.setup()
    renderApp('/plans/p1')
    const outcome = await screen.findByText('Appliquée, une commande reste à lancer')
    expect(outcome.closest('[role="status"]')).toHaveTextContent("requirements.txt attend sa régénération (uv n'est pas installé).")
    expect(screen.getByText('commande à lancer')).toBeInTheDocument()
    const copy = screen.getByRole('button', { name: 'Copier la commande de requirements.txt' })
    await user.click(copy)
    expect(await navigator.clipboard.readText()).toBe(plan.lockfiles[1].command)
    expect(screen.getByRole('button', { name: 'Copié' })).toBeInTheDocument()
    expect(screen.getByText('Commande copiée.')).toBeInTheDocument()
  })

  it('un outil échoue : ce qu’il a dit, les fichiers remis, réessayer', async () => {
    const output = [...Array.from({ length: 14 }, (_, index) => `  ligne ${index + 1}`), 'error: Failed to fetch'].join('\n')
    const results = regenerated()
    results[1] = { ...results[1], status: 'failed', installed: [], error: output, restored: ['requirements.in', 'requirements.txt'] }
    mockApi({
      'GET /api/scans/a1': scanDetail(),
      'GET /api/updates/p1': planDocument({ status: 'done', applicable: false, results }),
    })
    renderApp('/plans/p1')
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('uv pip compile a échoué : ses fichiers sont remis comme avant')
    expect(alert).toHaveTextContent("requirements.in et requirements.txt sont revenus à leur état d'avant.")
    expect(alert).toHaveTextContent('package-lock.json, qui ne dépend pas d')
    const shown = screen.getByRole('region', { name: 'Sortie de uv pip compile' })
    expect(shown.textContent?.split('\n')).toHaveLength(12)
    expect(shown).toHaveTextContent('error: Failed to fetch')
    expect(screen.getByText('échec, fichiers remis')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Réessayer' })).toHaveAttribute('href', '/analyses/a1/mise-a-jour?plan=p1')
  })

  it('une version obtenue autre que choisie : plus haute, ou retenue', async () => {
    const results = regenerated()
    results[1].installed = [
      { update: '.|PyPI|flask', version: '0.12.6', versions: ['0.12.6'], reach: 'above', held_by: [] },
      { update: '.|PyPI|jinja2|2.10', version: '2.10.1', versions: ['2.10.1'], reach: 'below', held_by: ['flask 0.12.6'] },
    ]
    results[1].changed = ['markupsafe 1.1.0 → 1.1.1']
    mockApi({
      'GET /api/scans/a1': scanDetail(),
      'GET /api/updates/p1': planDocument({ status: 'done', applicable: false, results }),
    })
    renderApp('/plans/p1')
    const outcome = await screen.findByText('Mise à jour appliquée')
    expect(outcome.closest('[role="status"]')).toHaveTextContent('dont 2 à une autre version que celle demandée')
    expect(screen.getByText('plus haute que choisie (0.12.5)')).toBeInTheDocument()
    expect(screen.getByText('retenue par flask 0.12.6')).toBeInTheDocument()
    expect(screen.getByText('markupsafe 1.1.0 → 1.1.1')).toBeInTheDocument()
  })
})
