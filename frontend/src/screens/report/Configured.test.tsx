import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { VULNERABLE, mockApi, renderApp, scanDetail } from '@/test/api'

describe('la configuration du projet et les réglages, sur le rapport (écran 4, E29)', () => {
  it('dit ce qu’ils ont changé, et ce que le fichier du projet a d’illisible', async () => {
    const report = {
      ...VULNERABLE,
      config: {
        file: 'forceupdate.toml',
        ignore: ['lodash', 'django@>=5'],
        exclude: ['legacy'],
        include_tests: true,
        selection: [{ ecosystem: null, level: 'patch' as const, security_only: null }],
        problems: ['forceupdate.toml : cache : clé inconnue, ignorée.'],
      },
      options: { ...VULNERABLE.options!, ignore: ['flask@>=3'], selection: [] },
    }
    mockApi({ 'GET /api/scans/a1': scanDetail({ report }) })
    renderApp('/analyses/a1')
    const line = (await screen.findByText(/Configuration du projet/)).closest('p')!
    expect(line).toHaveTextContent(
      'Configuration du projet : forceupdate.toml : ignorés : lodash, django@>=5 ; dossiers exclus : legacy ; dossiers de tests analysés ; sélection par défaut réglée.',
    )
    const problems = screen.getByText(/forceupdate\.toml\s: des valeurs écartées/).closest('[role="status"]')!
    expect(problems).toHaveTextContent('forceupdate.toml : cache : clé inconnue, ignorée.')
    const link = within(screen.getByRole('main')).getByRole('link', { name: 'Réglages' })
    expect(link).toHaveAttribute('href', '/reglages')
    const mine = link.closest('p')!
    expect(mine).toHaveTextContent('Réglages : ignorés : flask@>=3.')
  })

  it('sans configuration ni réglage : rien', async () => {
    mockApi({ 'GET /api/scans/a1': scanDetail() })
    renderApp('/analyses/a1')
    await screen.findByRole('heading', { level: 1, name: 'vulnerable' })
    expect(screen.queryByText(/Configuration du projet/)).toBeNull()
  })
})
