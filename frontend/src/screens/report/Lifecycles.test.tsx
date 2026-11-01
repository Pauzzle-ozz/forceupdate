import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Report } from '@/api/types'
import { EOL, VULNERABLE, mockApi, renderApp, scanDetail } from '@/test/api'

function withReport(report: Report) {
  return mockApi({ 'GET /api/scans/a1': scanDetail({ report }) })
}

describe('les fins de vie dans le rapport (écran 4, E27)', () => {
  it('montre les runtimes et le framework en fin de vie, datés, avec le cycle conseillé', async () => {
    withReport(EOL)
    renderApp('/analyses/a1')
    const section = (await screen.findByRole('heading', { name: 'Fins de vie' })).closest('section')!
    expect(section).toHaveTextContent(`3 cycles, d'après endoflife.date`)
    const items = within(section).getAllByRole('listitem')
    expect(items).toHaveLength(3)

    const [python, node, django] = items
    expect(python).toHaveTextContent('Python 3.8')
    expect(python).toHaveTextContent('runtime')
    expect(python).toHaveTextContent('Fin de vie depuis le 7 oct. 2024.')
    expect(python).toHaveTextContent(`Lu dans .python-version : 3.8`)
    expect(python).toHaveTextContent(`Cycle conseillé : 3.15`)
    expect(python).toHaveTextContent('dernière version 3.15.2')
    expect(within(python).getByRole('link', { name: /Les cycles de Python sur endoflife\.date/ })).toHaveAttribute(
      'href',
      'https://endoflife.date/python',
    )

    expect(node).toHaveTextContent('Node.js 16')
    expect(node).toHaveTextContent('Fin de vie depuis le 11 sept. 2023.')
    expect(within(node).getByText('LTS')).toBeInTheDocument()
    expect(node).toHaveTextContent('dernière version 26.13.0')

    expect(django).toHaveTextContent('Django 3.2')
    expect(django).toHaveTextContent('framework')
    expect(django).toHaveTextContent('Fin de vie depuis le 1 avr. 2024.')
    expect(django).toHaveTextContent('5.2.18 demande Python >=3.10')
  })

  it('le nom du framework ouvre son détail, qui renvoie à endoflife.date', async () => {
    withReport(EOL)
    const user = userEvent.setup()
    renderApp('/analyses/a1')
    const section = (await screen.findByRole('heading', { name: 'Fins de vie' })).closest('section')!
    await user.click(within(section).getByRole('button', { name: 'django, voir le détail' }))
    const dialog = screen.getByRole('dialog', { name: 'django' })
    expect(within(dialog).getByText(/Django 3\.2 : fin de vie depuis le 01\/04\/2024/)).toBeInTheDocument()
    expect(within(dialog).getByRole('link', { name: /cycles sur endoflife\.date/ })).toHaveAttribute(
      'href',
      'https://endoflife.date/django',
    )
  })

  it('les runtimes du projet sont dans sa carte', async () => {
    withReport(EOL)
    renderApp('/analyses/a1')
    const runtimes = (await screen.findByText('Runtimes')).nextElementSibling!
    const lines = within(runtimes as HTMLElement).getAllByRole('listitem')
    expect(lines.map((line) => line.textContent)).toEqual([
      'Python 3.8 et plus (pyproject.toml)',
      'Node.js 16 et plus (package.json)',
      'Node.js 16 (.nvmrc, Dockerfile)',
      'Python 3.8 (.python-version, Dockerfile)',
    ])
  })

  it('le compteur « Fins de vie » filtre le tableau sur le framework', async () => {
    withReport(EOL)
    const user = userEvent.setup()
    renderApp('/analyses/a1')
    const counter = await screen.findByRole('button', { name: /Fins de vie/ })
    expect(counter).toHaveTextContent('3')
    await user.click(counter)
    expect(counter).toHaveAttribute('aria-pressed', 'true')
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toHaveTextContent('django')
  })

  it('sans fin de vie, pas de section', async () => {
    withReport(VULNERABLE)
    renderApp('/analyses/a1')
    await screen.findByRole('heading', { level: 1, name: 'vulnerable' })
    expect(screen.queryByRole('heading', { name: 'Fins de vie' })).not.toBeInTheDocument()
  })
})
