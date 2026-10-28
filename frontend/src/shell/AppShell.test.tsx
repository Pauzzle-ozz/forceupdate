import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { THEME_KEY } from '@/hooks/useTheme'
import { listing, mockApi, renderApp } from '@/test/api'
import { display } from '@/test/display'

describe('la coquille', () => {
  it('le lien d’évitement, la marque, la navigation, le pied de page avec la devise', () => {
    mockApi({ 'GET /api/scans': [], 'GET /api/fs': listing() })
    renderApp('/')
    expect(screen.getByRole('link', { name: 'Aller au contenu' })).toHaveAttribute('href', '#contenu')
    expect(screen.getByRole('link', { name: 'forceupdate, accueil' })).toHaveAttribute('href', '/')
    const nav = screen.getByRole('navigation', { name: 'Navigation principale' })
    expect(nav).toHaveTextContent('AnalyserDépôtsComptesRéglages')
    expect(screen.getByRole('main')).toHaveAttribute('id', 'contenu')
    expect(screen.getByText('Que la Force soit avec tes dépendances.')).toBeInTheDocument()
  })

  it('le thème : système, puis clair, sombre, et de nouveau système ; gardé dans le navigateur', async () => {
    mockApi({ 'GET /api/scans': [], 'GET /api/fs': listing() })
    display.dark = true
    const user = userEvent.setup()
    renderApp('/')
    const html = document.documentElement
    const toggle = () => screen.getByRole('button', { name: /^Thème/ })
    expect(html).toHaveClass('dark')
    expect(toggle()).toHaveAccessibleName('Thème : celui du système. Passer au thème clair')

    await user.click(toggle())
    expect(html).not.toHaveClass('dark')
    expect(localStorage.getItem(THEME_KEY)).toBe('light')

    await user.click(toggle())
    expect(html).toHaveClass('dark')
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')

    await user.click(toggle())
    expect(localStorage.getItem(THEME_KEY)).toBeNull()
    expect(html).toHaveClass('dark') // le système est sombre
  })

  it('sous 900 px, la navigation passe dans un menu', async () => {
    mockApi({ 'GET /api/scans': [], 'GET /api/fs': listing() })
    const user = userEvent.setup()
    renderApp('/')
    const menu = screen.getByRole('button', { name: 'Menu' })
    expect(menu).toHaveAttribute('aria-expanded', 'false')
    await user.click(menu)
    expect(menu).toHaveAttribute('aria-expanded', 'true')
    await user.keyboard('{Escape}')
    expect(menu).toHaveAttribute('aria-expanded', 'false')
  })

  it('une adresse inconnue : la page introuvable', () => {
    renderApp('/nulle-part')
    expect(screen.getByRole('heading', { level: 1, name: "Ce n'est pas la page que vous cherchez." })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: "Retour à l'accueil" })).toHaveAttribute('href', '/')
  })

  it('les écrans des étapes suivantes le disent, au lieu d’une page vide', () => {
    renderApp('/analyses/a1/mise-a-jour')
    expect(screen.getByRole('heading', { level: 1, name: 'Mise à jour' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Revenir au rapport' })).toHaveAttribute('href', '/analyses/a1')
  })
})
