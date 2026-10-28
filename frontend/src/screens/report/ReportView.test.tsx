import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Report } from '@/api/types'
import { NBSP } from '@/lib/format'
import { Status, VULNERABLE, mockApi, renderApp, scanDetail } from '@/test/api'
import { display } from '@/test/display'

function withReport(report: Report | null, overrides = {}) {
  return mockApi({ 'GET /api/scans/a1': scanDetail({ report, ...overrides }) })
}

describe('le rapport (écran 4)', () => {
  it('montre la synthèse, les projets et les dépendances de vulnerable, comme la maquette', async () => {
    withReport(VULNERABLE)
    renderApp('/analyses/a1')
    expect(await screen.findByRole('heading', { level: 1, name: 'vulnerable' })).toBeInTheDocument()
    expect(document.title).toBe('Rapport · vulnerable · forceupdate')

    const counters = screen.getByRole('group', { name: /Constats par type/ })
    const failles = within(counters).getByRole('button', { name: /Failles/ })
    expect(failles).toHaveTextContent('28')
    expect(failles).toHaveTextContent('13 élevées · 14 moyennes · 1 faible')
    expect(within(counters).getByRole('button', { name: /Plus récentes/ })).toHaveTextContent('1 majeure · 1 mineure')
    // Un zéro reste là, sans être un bouton.
    expect(within(counters).getByText('Fins de vie').closest('button')).toBeNull()

    expect(
      screen.getByRole('img', {
        name: `Gravité des 30${NBSP}constats${NBSP}: 0 critique, 13 élevées, 14 moyennes, 2 faibles, 1 information`,
      }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Mettre à jour/ })).toHaveTextContent('3 cochées')
    expect(screen.getByRole('link', { name: /Mettre à jour/ })).toHaveAttribute('href', '/analyses/a1/mise-a-jour')

    const table = screen.getByRole('table')
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((row) => within(row).getAllByRole('button')[0].getAttribute('aria-label'))).toEqual([
      'flask, voir le détail',
      'jinja2, voir le détail',
      'lodash, voir le détail',
      'werkzeug, voir le détail',
      'click, voir le détail',
      'itsdangerous, voir le détail',
      'markupsafe, voir le détail',
    ])
    expect(rows[0]).toHaveTextContent('4 failles')
    expect(rows[0]).toHaveTextContent('3.1.3majeure')
    expect(rows[0]).toHaveTextContent('Élevée')
    expect(rows[0]).toHaveTextContent('correctif · corrige 1 faille sur 4')
    expect(rows[1]).toHaveTextContent('mineure · lockfile seul · corrige 2 failles sur 6')
    expect(rows[2]).toHaveTextContent('corrige les 6 failles')
    expect(rows[3]).toHaveTextContent('proposée, pas cochée')
    expect(rows[4]).toHaveTextContent('Aucune faille connue')
    expect(rows[4]).toHaveTextContent('version non vérifiée (indirecte)')
    expect(within(table).getByRole('columnheader', { name: /Gravité/ })).toHaveAttribute('aria-sort', 'descending')
  })

  it('filtre le tableau par un compteur, et le dit', async () => {
    withReport(VULNERABLE)
    const user = userEvent.setup()
    renderApp('/analyses/a1')
    const recent = await screen.findByRole('button', { name: /Plus récentes/ })
    await user.click(recent)
    expect(recent).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('2 dépendances sur 7')).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(3)
    await user.click(screen.getByRole('button', { name: 'Tout afficher' }))
    expect(screen.getByText('7 dépendances')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Filtrer par nom'), 'zzz')
    expect(screen.getByRole('heading', { name: 'Aucune dépendance ne correspond' })).toBeInTheDocument()
  })

  it('trie par nom', async () => {
    withReport(VULNERABLE)
    const user = userEvent.setup()
    renderApp('/analyses/a1')
    await user.click(await screen.findByRole('button', { name: /^Paquet/ }))
    const header = screen.getByRole('columnheader', { name: /Paquet/ })
    expect(header).toHaveAttribute('aria-sort', 'ascending')
    const first = within(screen.getByRole('table')).getAllByRole('row')[1]
    expect(first).toHaveTextContent('click')
  })

  it('ouvre le détail d’une dépendance dans un panneau, et le ferme avec Échap', async () => {
    withReport(VULNERABLE)
    const user = userEvent.setup()
    renderApp('/analyses/a1')
    const opener = await screen.findByRole('button', { name: 'flask, voir le détail' })
    await user.click(opener)
    const dialog = screen.getByRole('dialog', { name: 'flask' })
    expect(dialog).toHaveAttribute('open')
    expect(within(dialog).getByRole('heading', { name: `5${NBSP}constats` })).toBeInTheDocument()
    expect(within(dialog).getByText('CVE-2018-1000656')).toBeInTheDocument()
    expect(within(dialog).getByText('Flask is vulnerable to Denial of Service via incorrect encoding of JSON data')).toHaveAttribute('lang', 'en')
    expect(within(dialog).getByText('pré-cochée')).toBeInTheDocument()
    const links = within(dialog).getAllByRole('link', { name: /avis sur osv\.dev/ })
    expect(links[0]).toHaveAccessibleName('avis sur osv.dev (nouvel onglet)')
    expect(links[0]).toHaveAttribute('rel', 'noreferrer')
    expect(within(dialog).getByRole('heading', { name: 'flask' })).toHaveFocus()
    dialog.dispatchEvent(new Event('cancel', { cancelable: true }))
    await waitFor(() => expect(dialog).not.toHaveAttribute('open'))
    expect(opener).toHaveFocus()
  })

  it('sous 768 px, une vraie liste de cartes', async () => {
    display.wide = false
    withReport(VULNERABLE)
    renderApp('/analyses/a1')
    const list = await screen.findByRole('list', { name: 'Dépendances' })
    expect(screen.queryByRole('table')).toBeNull()
    const cards = within(list).getAllByRole('listitem')
    expect(cards).toHaveLength(7)
    expect(within(cards[0]).getByText('Utilisée')).toBeInTheDocument()
    expect(within(cards[0]).getByText('0.12', { selector: 'span' })).toBeInTheDocument()
  })

  it('rien à mettre à jour : dit ce qui a été vérifié, et ce qui ne l’a pas été', async () => {
    const report = structuredClone(VULNERABLE)
    report.projects[0].findings = []
    report.projects[0].updates = []
    report.summary = {
      ...report.summary,
      findings: { vulnerable: 0, eol: 0, yanked: 0, deprecated: 0, outdated: 0, unverifiable: 0, inconclusive: 0 },
      outdated: { major: 0, minor: 0, patch: 0 },
      severities: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
      vulnerabilities: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
      to_update: 0,
    }
    withReport(report)
    renderApp('/analyses/a1')
    expect(await screen.findByText('Rien à mettre à jour')).toBeInTheDocument()
    expect(screen.getByText(/n'ont pas été comparées aux registres/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Relancer avec les indirectes' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Mettre à jour/ })).toBeNull()
    expect(screen.getByText('7 dépendances auditées')).toBeInTheDocument()
  })

  it('aucun projet : l’état vide, avec de quoi relancer', async () => {
    const report = { ...structuredClone(VULNERABLE), projects: [], ignored_manifests: ['tests/a/package.json'] }
    withReport(report)
    renderApp('/analyses/a1')
    expect(await screen.findByRole('heading', { name: 'Aucun fichier de dépendances dans ce dossier' })).toBeInTheDocument()
    expect(screen.getByText(/1 manifeste rangé dans des dossiers de tests a été écarté/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyser aussi les dossiers de tests' })).toBeInTheDocument()
  })

  it('hors ligne : la date des données du cache, et « Relancer en ligne »', async () => {
    const report = structuredClone(VULNERABLE)
    report.options = { ...report.options!, offline: true }
    report.oldest_data = '2026-10-21T07:12:00+00:00'
    withReport(report)
    renderApp('/analyses/a1')
    expect(await screen.findByText(/Analyse hors ligne/, { selector: 'p' })).toBeInTheDocument()
    expect(screen.getByText(/la plus ancienne donnée date du 21 oct. 2026/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Relancer en ligne' })).toBeInTheDocument()
  })

  it('non concluant : l’alerte dit lesquels et pourquoi, et filtre le tableau', async () => {
    const report = structuredClone(VULNERABLE)
    const project = report.projects[0]
    const lodash = project.dependencies.find((dependency) => dependency.name === 'lodash')!
    project.findings = project.findings.filter((finding) => finding.dependency?.name !== 'lodash')
    project.findings.push({
      kind: 'inconclusive',
      severity: 'info',
      message: 'Failles non vérifiées. OSV : pas de réponse.',
      dependency: lodash,
      current_version: '4.17.15',
      current_is_approximate: false,
      target_version: null,
      wanted_version: null,
      gap: null,
      identifiers: [],
      cvss_score: null,
      detail: null,
      url: null,
    })
    report.summary = { ...report.summary, findings: { ...report.summary.findings, inconclusive: 1 } }
    withReport(report)
    const user = userEvent.setup()
    renderApp('/analyses/a1')
    expect(await screen.findByText('1 constat non concluant')).toBeInTheDocument()
    expect(screen.getByText('Failles non vérifiées. OSV : pas de réponse.', { selector: 'li' , exact: false })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Voir les non concluants' }))
    const rows = within(screen.getByRole('table')).getAllByRole('row')
    expect(rows).toHaveLength(2)
    expect(rows[1]).toHaveTextContent('Inconnue')
  })

  it('les états échouée, annulée et introuvable', async () => {
    mockApi({
      'GET /api/scans/a1': scanDetail({ status: 'failed', error: 'Accès refusé.', report: null }),
      'GET /api/scans/a2': scanDetail({ id: 'a2', status: 'cancelled', report: null }),
      'GET /api/scans/a3': new Status(404, { detail: 'Analyse inconnue.' }),
    })
    const { unmount } = renderApp('/analyses/a1')
    expect(await screen.findByText("L'analyse a échoué")).toBeInTheDocument()
    expect(screen.getByText('Accès refusé.')).toBeInTheDocument()
    unmount()
    const second = renderApp('/analyses/a2')
    expect(await screen.findByRole('heading', { name: 'Analyse annulée' })).toBeInTheDocument()
    second.unmount()
    renderApp('/analyses/a3')
    expect(await screen.findByRole('heading', { name: "Cette analyse n'existe plus" })).toBeInTheDocument()
  })
})
