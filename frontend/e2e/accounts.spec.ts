import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { TOKEN } from '../playwright.config.ts'
import { watchConsole } from './helpers.ts'

/**
 * L'écran 6 (Comptes) contre le vrai serveur, GitHub simulé (tests/e2e_server.py : la page
 * d'autorisation est sur `localhost`, un autre site que 127.0.0.1 ; elle renvoie aussitôt vers le
 * serveur). Le trousseau du serveur est partagé : ces tests se suivent, et chacun commence
 * déconnecté.
 */
test.describe.configure({ mode: 'serial' })

async function start(page: Page) {
  await page.goto(`/?token=${TOKEN}`)
  await page.request.delete('/api/accounts/github')
  await page.goto('/comptes')
  await expect(page.getByRole('heading', { level: 1, name: 'Comptes' })).toBeVisible()
  return page.getByRole('region', { name: 'GitHub' })
}

test('OAuth : autoriser sur la forge, revenir connecté, puis se déconnecter', async ({ page }) => {
  const errors = watchConsole(page)
  const card = await start(page)
  await card.getByRole('button', { name: 'Se connecter avec GitHub' }).click()
  // github.com (ici localhost) renvoie vers /oauth/github/callback, qui renvoie vers /comptes.
  await expect(page).toHaveURL(/\/comptes\?connexion=[0-9a-f]+$/)
  await expect(card.getByText('Connecté à GitHub')).toBeVisible()
  await expect(card.getByText('Compte @octo-e2e.')).toBeVisible()
  await expect(card.getByRole('link', { name: '@octo-e2e (nouvel onglet)' })).toBeVisible()
  await expect(card.getByText('par autorisation (OAuth)', { exact: false })).toBeVisible()
  await expect(card.getByText('Lecture et PR')).toBeVisible()

  await card.getByRole('button', { name: 'Se déconnecter…' }).click()
  const dialog = page.getByRole('alertdialog', { name: 'Se déconnecter de GitHub ?' })
  await expect(dialog).toContainText('Il est aussi révoqué auprès de GitHub.')
  await dialog.getByRole('button', { name: 'Se déconnecter' }).click()
  await expect(card.getByText('Déconnecté de GitHub : token effacé de cet ordinateur et révoqué.')).toBeVisible()
  await expect(card.getByText('Non connecté')).toBeVisible()
  expect(errors).toEqual([])
})

test('une adresse de retour rejouée ne connecte rien', async ({ page }) => {
  const card = await start(page)
  await page.goto('/oauth/github/callback?code=e2e-code&state=inconnu')
  await expect(page).toHaveURL(/\/comptes$/)
  await expect(card.getByText('Non connecté')).toBeVisible()
})

test('device flow : le code, puis connecté', async ({ page }) => {
  const errors = watchConsole(page)
  const card = await start(page)
  await card.getByRole('button', { name: 'Se connecter avec un code' }).click()
  await expect(card.getByText('WDJB-MJHT')).toBeVisible()
  await expect(card.getByRole('link', { name: 'Ouvrir github.com/login/device (nouvel onglet)' })).toBeVisible()
  await expect(card.getByText('Connecté à GitHub')).toBeVisible({ timeout: 20_000 })
  await expect(card.getByText('par un code (device flow)', { exact: false })).toBeVisible()
  expect(errors).toEqual([])
})

test('token collé : refusé, puis accepté ; fine-grained : droits non vérifiés', async ({ page }) => {
  const card = await start(page)
  const field = card.getByLabel('Token GitHub')
  await field.fill('ghp_faux')
  await card.getByRole('button', { name: 'Connecter avec ce token' }).click()
  await expect(card.getByRole('alert')).toContainText('GitHub refuse le token (401)')
  await field.fill('github_pat_e2e')
  await card.getByRole('button', { name: 'Connecter avec ce token' }).click()
  await expect(card.getByText('Connecté à GitHub')).toBeVisible()
  await expect(card.getByText('Droits non vérifiés')).toBeVisible()
  // Le token n'est jamais renvoyé au navigateur.
  const listing = await (await page.request.get('/api/accounts')).text()
  expect(listing).not.toContain('github_pat_e2e')
})

test('gh : reprendre son compte ; l’accueil le montre', async ({ page }) => {
  const card = await start(page)
  await card.getByRole('button', { name: 'Reprendre le compte de gh' }).click()
  await expect(card.getByText('depuis GitHub CLI (gh)', { exact: false })).toBeVisible()
  await page.getByRole('link', { name: 'forceupdate, accueil' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Analyser du code' })).toBeVisible()
  await expect(page.getByText('@octo-e2e', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Gérer les comptes' })).toBeVisible()
})

async function audit(page: Page, where: string) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  const found = results.violations.map(
    (violation) => `${where} : ${violation.id} (${violation.nodes.length}) ${violation.nodes[0]?.target.join(' ')}`,
  )
  expect(found).toEqual([])
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, `${where} : défilement horizontal`).toBe(0)
}

for (const scheme of ['light', 'dark'] as const) {
  for (const width of [1440, 375]) {
    test(`écran 6, ${scheme === 'light' ? 'clair' : 'sombre'}, ${width} px`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
      await page.setViewportSize({ width, height: 900 })
      const card = await start(page)
      await audit(page, 'non connecté')

      await card.getByRole('button', { name: 'Se connecter avec un code' }).click()
      await expect(card.getByText('WDJB-MJHT')).toBeVisible()
      await audit(page, 'device flow')
      await card.getByRole('button', { name: 'Annuler' }).click()
      await expect(card.getByText('Non connecté')).toBeVisible()

      await card.getByLabel('Token GitHub').fill('ghp_e2e_classic')
      await card.getByRole('button', { name: 'Connecter avec ce token' }).click()
      await expect(card.getByText('Connecté à GitHub')).toBeVisible()
      await audit(page, 'connecté')

      await card.getByRole('button', { name: 'Se déconnecter…' }).click()
      await expect(page.getByRole('alertdialog')).toBeVisible()
      await audit(page, 'confirmation')
      await page.getByRole('alertdialog').getByRole('button', { name: 'Annuler' }).click()
    })
  }
}
