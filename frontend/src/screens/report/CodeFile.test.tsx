import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Report } from '@/api/types'
import { EOL, IMPORTS, mockApi, renderApp, scanDetail } from '@/test/api'

function withReport(report: Report, source: string) {
  return mockApi({ 'GET /api/scans/a1': scanDetail({ report, source, kind: 'file' }) })
}

describe('un fichier de code choisi seul (écran 4, E28)', () => {
  it('ses imports : versions non fixées, failles non vérifiables, rien de « à jour »', async () => {
    withReport(IMPORTS, 'C:/Projets/scripts/imports.py')
    renderApp('/analyses/a1')
    expect(await screen.findByRole('heading', { level: 1, name: 'imports.py' })).toBeInTheDocument()
    expect(screen.getByText('Fichier de code sans projet autour : ses imports, sans version.')).toBeInTheDocument()

    const alert = screen.getByText('4 versions non fixées').closest('[role="status"]')!
    expect(alert).toHaveTextContent('seule la dernière publiée est donnée, et les failles ne sont pas vérifiables')
    expect(screen.queryByText('Rien à mettre à jour')).not.toBeInTheDocument()

    const counters = screen.getByRole('group', { name: /Constats par type/ })
    const unpinned = within(counters).getByRole('button', { name: /Versions non fixées/ })
    expect(unpinned).toHaveTextContent('4')
    expect(unpinned).toHaveTextContent('failles non vérifiables')

    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(4)
    const dateutil = rows.find((row) => within(row).queryByRole('button', { name: 'python-dateutil, voir le détail' }))!
    expect(dateutil).toHaveTextContent('non fixée')
    expect(dateutil).toHaveTextContent('un import, sans version')
    expect(dateutil).toHaveTextContent('aucune : un import')
    expect(dateutil).toHaveTextContent('import dateutil')
    expect(dateutil).toHaveTextContent('non fixée · dernière 4.0.0')

    const card = screen.getByText('Fichier de code').nextElementSibling!
    expect(card).toHaveTextContent('imports.py (ses imports, sans version)')
  })

  it('« Voir les versions non fixées » filtre le tableau ; le détail dit l’import', async () => {
    withReport(IMPORTS, 'C:/Projets/scripts/imports.py')
    const user = userEvent.setup()
    renderApp('/analyses/a1')
    await user.click(await screen.findByRole('button', { name: 'Voir les versions non fixées' }))
    expect(screen.getByRole('button', { name: /Versions non fixées/ })).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: 'python-dateutil, voir le détail' }))
    const dialog = screen.getByRole('dialog', { name: 'python-dateutil' })
    const value = (label: string) => within(dialog).getByText(label, { selector: 'dt' }).nextElementSibling
    expect(value('Import')).toHaveTextContent('dateutil dans imports.py')
    expect(value('Utilisée')).toHaveTextContent('non fixée : un import, sans version écrite nulle part')
    expect(value('Dernière')).toHaveTextContent('4.0.0')
    expect(dialog).toHaveTextContent('Version non fixée (importé : dateutil) : la dernière est 4.0.0.')
  })

  it('dans un projet : analysé via son manifeste, la racine dite', async () => {
    const report: Report = {
      ...EOL,
      source: 'C:/Projets/eol/app/__init__.py',
      code: { path: 'app/__init__.py', language: 'Python', reading: 'project', via: ['pyproject.toml'] },
    }
    withReport(report, report.source)
    renderApp('/analyses/a1')
    const line = (await screen.findByText(/Fichier de code dans un projet/)).closest('p')!
    expect(line).toHaveTextContent(
      'Fichier de code dans un projet : analysé via pyproject.toml (dans C:/Projets/eol), le premier manifeste Python au-dessus de lui.',
    )
    expect(screen.getByText('Manifestes')).toBeInTheDocument()
  })

  it('un script à bloc PEP 723 : son bloc tient lieu de manifeste', async () => {
    const report: Report = {
      ...IMPORTS,
      source: 'C:/Projets/scripts/pep723.py',
      code: { path: 'pep723.py', language: 'Python', reading: 'script', via: [] },
    }
    withReport(report, report.source)
    renderApp('/analyses/a1')
    const line = (await screen.findByText(/Script à bloc PEP 723/)).closest('p')!
    expect(line).toHaveTextContent('son bloc # /// script tient lieu de manifeste, comme pour uv run.')
    expect(screen.getByText('Manifeste').nextElementSibling).toHaveTextContent('(son bloc PEP 723)')
  })
})
