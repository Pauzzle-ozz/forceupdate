import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { TOKEN } from '../playwright.config.ts'
import { watchConsole } from './helpers.ts'

/**
 * Les écrans 6 (Comptes) et 7 (Mes dépôts) contre le vrai serveur, GitHub simulé
 * (tests/e2e_server.py : la page d'autorisation est sur `localhost`, un autre site que 127.0.0.1 ;
 * elle renvoie aussitôt vers le serveur ; les dépôts sont des mini-projets de tests/projects). Le
 * trousseau du serveur est partagé : ces tests se suivent dans ce seul fichier, et chacun
 * commence déconnecté.
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

// -- Écran 7 : Mes dépôts -------------------------------------------------------------

/** Connecté avec un token classic (`repo`, `read:org`), sur l'écran des dépôts. */
async function repositories(page: Page) {
  await page.goto(`/?token=${TOKEN}`)
  await page.request.delete('/api/accounts/github')
  const response = await page.request.post('/api/accounts/github/token', { data: { token: 'ghp_e2e_classic' } })
  expect(response.status()).toBe(201)
  await page.goto('/depots')
  await expect(page.getByRole('heading', { level: 2, name: 'Synthèse' })).toBeVisible()
}

function row(page: Page, name: string) {
  return page.getByRole('row').filter({ has: page.locator('.font-mono', { hasText: new RegExp(`^${name}$`) }) })
}

test('mes dépôts : la liste, l’analyse groupée sans cloner, la synthèse, puis un rapport', async ({ page }) => {
  const errors = watchConsole(page)
  await repositories(page)
  await expect(page.getByText('6 dépôts sur 1 compte.', { exact: false })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Comptes connectés' }).getByText('octo-e2e')).toBeVisible()
  await expect(page.getByText("L'organisation nord-e2e limite l'accès des applications")).toBeVisible()
  await expect(page.getByText('requêtes restantes sur 5', { exact: false })).toContainText('API GitHub')
  await expect(page.getByText(/4\saffichés · 2\smasqués \(1\sarchivé, 1\svide\)/)).toBeVisible()
  await expect(row(page, 'octo-e2e/vulnerable').getByRole('img', { name: 'privé' })).toBeVisible()
  await expect(row(page, 'atelier-e2e/outils').getByText('pas encore analysé')).toBeVisible()

  await page.getByRole('checkbox', { name: /Tout sélectionner/ }).check()
  const bar = page.getByRole('region', { name: 'Actions sur la sélection' })
  await expect(bar.getByText('4 dépôts sélectionnés', { exact: false })).toBeVisible()
  await bar.getByRole('button', { name: 'Analyser ces 4 dépôts' }).click()

  const batch = page.getByRole('region', { name: /Analyse de 4\sdépôts/ })
  await expect(batch.getByRole('heading', { name: /terminée à/ })).toBeVisible({ timeout: 30_000 })
  await expect(batch).toContainText("requêtes d'API utilisées")
  const vulnerable = row(page, 'octo-e2e/vulnerable')
  await expect(vulnerable.getByText(/^28\sfailles$/)).toBeVisible()
  await expect(vulnerable.getByText(/à mettre à jour/)).toBeVisible()
  await expect(row(page, 'octo-e2e/a-jour').getByText('à jour', { exact: true })).toBeVisible()
  await expect(row(page, 'octo-e2e/docs').getByText('aucun fichier de dépendances')).toBeVisible()
  await expect(row(page, 'atelier-e2e/outils').getByText('lecture seule')).toBeVisible()
  const stats = page.getByRole('group', { name: /Synthèse des dépôts/ })
  await expect(stats.getByRole('button', { name: /^Failles/ })).toContainText('dans 1')
  await expect(stats.getByText(/4\sanalysés · 2\ssautés/)).toBeVisible()

  await vulnerable.getByRole('link', { name: 'octo-e2e/vulnerable', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'octo-e2e/vulnerable' })).toBeVisible()
  await expect(page.getByRole('link', { name: /Voir sur GitHub/ })).toHaveAttribute('href', 'https://github.com/octo-e2e/vulnerable')
  await expect(page.getByRole('navigation', { name: "Fil d'Ariane" }).getByRole('link', { name: 'Mes dépôts' })).toBeVisible()
  await expect(page.getByRole('link', { name: /Mettre à jour/ })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /Préparer la PR/ })).toBeVisible()
  const counters = page.getByRole('group', { name: /Constats par type/ })
  await expect(counters.getByRole('button', { name: /Failles/ })).toContainText('28')
  expect(errors).toEqual([])
})

test('un dépôt public d’un autre compte, par son adresse', async ({ page }) => {
  const errors = watchConsole(page)
  await repositories(page)
  await page.getByLabel('Dépôt public : owner/nom ou adresse').fill('https://github.com/pallets-e2e/inconnu')
  await page.getByRole('button', { name: 'Analyser', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'Dépôt introuvable sur GitHub' })).toBeVisible()
  await page.getByLabel('Dépôt public : owner/nom ou adresse').fill('https://github.com/pallets-e2e/flask')
  await page.getByRole('button', { name: 'Analyser', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'pallets-e2e/flask' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText("dépôt GitHub, lu par l'API sans le cloner", { exact: false })).toBeVisible()
  // Pas dans la liste du compte : la liste ne change pas.
  await page.goto('/depots')
  await expect(page.getByText('6 dépôts sur 1 compte.', { exact: false })).toBeVisible()
  // Le navigateur consigne la réponse 404 du dépôt inconnu : c'est la seule erreur attendue.
  expect(errors).toEqual(['Failed to load resource: the server responded with a status of 404 (Not Found)'])
})

// -- Écran 8 : une PR par dépôt -------------------------------------------------------

/** Analyse `octo-e2e/vulnerable` (par l'API), si un test d'avant ne l'a pas déjà fait. */
async function analyzeVulnerable(page: Page) {
  const response = await page.request.post('/api/repositories/batches', {
    data: { forge: 'github', repositories: ['octo-e2e/vulnerable'] },
  })
  expect(response.status()).toBe(202)
  const { id } = (await response.json()) as { id: string }
  await expect
    .poll(async () => ((await (await page.request.get(`/api/repositories/batches/${id}`)).json()) as { status: string }).status, {
      timeout: 30_000,
    })
    .toBe('done')
}

test('une PR par dépôt : le récapitulatif, l’envoi, la PR ouverte ; relancer met à jour la même', async ({ page }) => {
  const errors = watchConsole(page)
  await repositories(page)
  await analyzeVulnerable(page)
  await page.reload()

  // Écran 7 : deux dépôts sélectionnés, dont un en lecture seule.
  await page.getByRole('checkbox', { name: 'Sélectionner octo-e2e/vulnerable' }).check()
  await page.getByRole('checkbox', { name: 'Sélectionner atelier-e2e/outils' }).check()
  const bar = page.getByRole('region', { name: 'Actions sur la sélection' })
  await expect(bar.getByRole('button', { name: 'Analyser ces 2 dépôts' })).toBeVisible()
  await bar.getByRole('button', { name: 'Préparer 2 PR' }).click()

  // Le récapitulatif : rien n'est poussé avant « Envoyer ».
  await expect(page.getByRole('heading', { level: 1, name: 'Préparer les PR' })).toBeVisible()
  await expect(page).toHaveURL(/\/pr\/[0-9a-f]+$/)
  const card = page.locator('[data-slot="card"]').filter({ has: page.getByRole('heading', { name: 'octo-e2e/vulnerable' }) })
  await expect(card.getByText('nouvelle PR')).toBeVisible()
  await expect(card.getByRole('checkbox', { name: 'Envoyer la PR de octo-e2e/vulnerable' })).toBeChecked()
  await expect(card.getByText('lodash', { exact: true })).toBeVisible()
  await expect(card.getByText('régénéré par npm')).toBeVisible()
  await expect(card.getByText('régénéré par uv pip compile')).toBeVisible()
  const skipped = page.locator('section').filter({ has: page.getByRole('heading', { name: 'Sautés' }) })
  await expect(skipped.getByText('lecture seule : pas de droit de push')).toBeVisible()
  await page.getByRole('button', { name: 'Envoyer la PR' }).click()

  // L'envoi, puis le résultat avec le lien de la PR.
  await expect(page.getByRole('heading', { level: 1, name: 'PR envoyées' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('1 PR ouverte', { exact: false })).toBeVisible()
  const link = page.getByRole('link', { name: /Voir la PR #41 sur GitHub/ })
  await expect(link).toHaveAttribute('href', 'https://github.com/octo-e2e/vulnerable/pull/41')
  await expect(page.getByText(/package-lock\.json/).first()).toBeVisible()

  // Écran 7 : la colonne PR et le compteur.
  await page.getByRole('link', { name: 'Retour à mes dépôts' }).click()
  await expect(row(page, 'octo-e2e/vulnerable').getByRole('link', { name: /PR #41 de octo-e2e\/vulnerable/ })).toBeVisible()
  await expect(page.getByRole('group', { name: /Synthèse des dépôts/ }).getByText('PR ouvertes')).toBeVisible()

  // Relancer depuis le rapport du dépôt : la même PR, mise à jour.
  await row(page, 'octo-e2e/vulnerable').getByRole('link', { name: 'octo-e2e/vulnerable', exact: true }).click()
  await page.getByRole('link', { name: /Préparer la PR/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: /Préparer la PR de/ })).toBeVisible()
  await page.getByRole('button', { name: 'Préparer la PR' }).first().click()
  await expect(page.getByRole('heading', { level: 1, name: 'Préparer les PR' })).toBeVisible()
  await expect(page.getByText('met à jour la PR #41')).toBeVisible()
  await page.getByRole('button', { name: 'Envoyer la PR' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'PR envoyées' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/PR #41 mise à jour/).first()).toBeVisible()
  await expect(page.getByRole('link', { name: /Voir la PR #41 sur GitHub/ })).toBeVisible()
  expect(errors).toEqual([])
})

for (const scheme of ['light', 'dark'] as const) {
  for (const width of [1440, 375]) {
    test(`écran 8, ${scheme === 'light' ? 'clair' : 'sombre'}, ${width} px`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
      await page.setViewportSize({ width, height: 900 })
      await repositories(page)
      await analyzeVulnerable(page)
      await page.goto('/pr?forge=github&depots=octo-e2e/vulnerable,atelier-e2e/outils')
      await expect(page.getByRole('button', { name: 'Envoyer la PR' })).toBeVisible()
      await page.locator('details').first().evaluate((element) => element.setAttribute('open', ''))
      await audit(page, 'récapitulatif')
      await page.getByRole('button', { name: 'Envoyer la PR' }).click()
      await expect(page.getByRole('heading', { level: 1, name: 'PR envoyées' })).toBeVisible({ timeout: 30_000 })
      await audit(page, 'résultat')
    })
  }
}

for (const scheme of ['light', 'dark'] as const) {
  for (const width of [1440, 375]) {
    test(`écran 7, ${scheme === 'light' ? 'clair' : 'sombre'}, ${width} px`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
      await page.setViewportSize({ width, height: 900 })
      await repositories(page)
      await audit(page, 'liste')
      await page.getByRole('button', { name: 'Les afficher' }).click()
      await page.getByRole('checkbox', { name: /Sélectionner octo-e2e\/docs/ }).check()
      await expect(page.getByRole('region', { name: 'Actions sur la sélection' })).toBeVisible()
      await audit(page, 'sélection')
    })
  }
}

test('écran 7 sans compte, et de 375 à 1440 px sans défilement horizontal', async ({ page }) => {
  await page.goto(`/?token=${TOKEN}`)
  await page.request.delete('/api/accounts/github')
  await page.goto('/depots')
  await expect(page.getByRole('heading', { level: 2, name: 'Aucun compte connecté' })).toBeVisible()
  await audit(page, 'sans compte')
  await repositories(page)
  for (const width of [375, 640, 768, 1024, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, `${width} px`).toBe(0)
  }
})
