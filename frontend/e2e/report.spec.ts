import { resolve } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { TOKEN } from '../playwright.config.ts'

/** Le mini-projet `vulnerable` : lodash 4.17.15 et flask 0.12, 28 failles connues. */
const VULNERABLE = resolve(import.meta.dirname, '../../tests/projects/vulnerable').replaceAll('\\', '/')

/** Les erreurs de la console (une ressource refusée par la CSP en est une). */
function watchConsole(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}

async function enter(page: Page) {
  // L'adresse affichée par « forceupdate ui » pose le cookie, puis renvoie vers « / ».
  await page.goto(`/?token=${TOKEN}`)
  await expect(page).toHaveURL(/\/$/)
}

test('choisir un mini-projet, voir le bon rapport, sous la CSP du serveur', async ({ page }) => {
  const errors = watchConsole(page)
  await enter(page)
  await expect(page.getByRole('heading', { level: 1, name: 'Analyser du code' })).toBeVisible()

  // Écran 2 : coller le chemin, voir ses fichiers de dépendances, analyser le dossier.
  await page.getByRole('link', { name: 'Choisir un dossier' }).click()
  await page.getByLabel('Dossier ouvert').fill(VULNERABLE)
  await page.getByLabel('Dossier ouvert').press('Enter')
  const list = page.getByRole('list', { name: `Contenu de ${VULNERABLE}` })
  await expect(list.getByRole('button', { name: /requirements\.in/ })).toBeVisible()
  await expect(list.getByRole('button', { name: /package-lock\.json/ })).toBeVisible()
  await page.getByRole('button', { name: 'Analyser ce dossier' }).click()

  // Écran 3, puis 4 à la même adresse.
  await expect(page).toHaveURL(/\/analyses\/[0-9a-f]+$/)
  const title = page.getByRole('heading', { level: 1, name: 'vulnerable' })
  await expect(title).toBeVisible({ timeout: 30_000 })

  const counters = page.getByRole('group', { name: /Constats par type/ })
  await expect(counters.getByRole('button', { name: /Failles/ })).toContainText('28')
  await expect(counters.getByRole('button', { name: /Failles/ })).toContainText('13 élevées · 14 moyennes · 1 faible')
  await expect(counters.getByRole('button', { name: /Plus récentes/ })).toContainText('1 majeure · 1 mineure')
  await expect(page.getByRole('link', { name: /Mettre à jour/ })).toContainText('3 cochées')

  const rows = page.getByRole('table').getByRole('row')
  await expect(rows).toHaveCount(8)
  await expect(rows.nth(1)).toContainText('flask')
  await expect(rows.nth(1)).toContainText('correctif · corrige 1 faille sur 4')
  await expect(rows.nth(3)).toContainText('lodash')
  await expect(rows.nth(3)).toContainText('4.17.15')
  await expect(rows.nth(4)).toContainText('proposée, pas cochée')

  // Le détail de flask, dans un panneau ; Échap le ferme.
  await page.getByRole('button', { name: 'flask, voir le détail' }).click()
  const detail = page.getByRole('dialog', { name: 'flask' })
  await expect(detail).toBeVisible()
  await expect(detail.getByRole('heading', { name: /5.constats/ })).toBeVisible()
  await expect(page).toHaveURL(/paquet=PyPI%3Aflask/)
  await page.keyboard.press('Escape')
  await expect(detail).toBeHidden()

  // L'accueil retrouve l'analyse de la session et le chemin récent.
  await page.getByRole('navigation', { name: 'Navigation principale' }).getByRole('link', { name: 'Analyser' }).click()
  await expect(page.getByRole('heading', { name: 'Cette session' })).toBeVisible()
  await expect(page.getByText('28 failles').first()).toBeVisible()
  await expect(page.getByRole('button', { name: /^vulnerable, analyser de nouveau/ })).toBeVisible()

  expect(errors).toEqual([])
})

test('à 375 px : des cartes, sans défilement horizontal ; le thème sombre est gardé', async ({ page }) => {
  const errors = watchConsole(page)
  await page.setViewportSize({ width: 375, height: 800 })
  await enter(page)
  await page.getByRole('button', { name: /^Thème/ }).click() // clair
  await page.getByRole('button', { name: /^Thème/ }).click() // sombre
  await expect(page.locator('html')).toHaveClass(/dark/)

  await page.getByLabel("Chemin absolu d'un dossier ou d'un fichier").fill(VULNERABLE)
  await page.getByRole('button', { name: 'Analyser', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'vulnerable' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('list', { name: 'Dépendances' }).getByRole('listitem')).toHaveCount(7)
  await expect(page.getByRole('table')).toHaveCount(0)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)

  // Le choix tient au rechargement (public/theme.js le pose avant l'affichage).
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)
  expect(errors).toEqual([])
})
