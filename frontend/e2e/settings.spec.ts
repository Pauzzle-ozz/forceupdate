import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { TOKEN } from '../playwright.config.ts'
import { copyProject, removeCopies, watchConsole } from './helpers.ts'

/**
 * L'écran 9, Réglages (E29), sur le vrai serveur : ses réglages sont ceux du serveur de test (un
 * fichier de son dossier temporaire), partagés avec les autres tests, qui tournent en même temps.
 * On n'y enregistre que des valeurs sans effet sur eux ni sur leurs rapports (des délais, un dépôt
 * qui n'existe pas ; pas de paquet ignoré : leurs rapports le diraient), et on remet les valeurs
 * par défaut à la fin.
 */

test.describe.configure({ mode: 'serial' })
test.afterAll(removeCopies)

/** Le lien « Réglages » de la navigation (un rapport peut en avoir un aussi). */
function navigation(page: Page) {
  return page.getByRole('navigation', { name: 'Navigation principale' }).getByRole('link', { name: 'Réglages' })
}

async function open(page: Page) {
  await page.goto(`/?token=${TOKEN}`)
  await navigation(page).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Réglages' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Enregistrer' })).toBeVisible()
}

function ignoreField(page: Page) {
  return page.getByRole('textbox', { name: 'Un par ligne', description: /Un paquet/ })
}

test('les réglages s’enregistrent, et valent après un rechargement', async ({ page }) => {
  const errors = watchConsole(page)
  await open(page)
  const lock = page.getByRole('spinbutton', { name: 'Délai des outils de lockfile' })
  await expect(lock).toHaveValue('600')
  await lock.fill('900')
  const repositories = page.getByRole('textbox', { name: 'Un par ligne', description: /github\.com/ })
  await repositories.fill('github.com/personne-e2e/rien\n\ngitlab.com/personne-e2e/*')
  await expect(page.getByText('Modifications non enregistrées.')).toBeVisible()
  await page.getByRole('button', { name: 'Enregistrer' }).click()
  await expect(page.getByText(/Enregistré\s:\svaut pour les analyses/)).toBeVisible()

  await page.reload()
  await expect(lock).toHaveValue('900')
  await expect(repositories).toHaveValue('github.com/personne-e2e/rien\ngitlab.com/personne-e2e/*')

  // Les valeurs par défaut, remises et enregistrées : les autres tests n'en voient rien.
  await page.getByRole('button', { name: 'Valeurs par défaut' }).click()
  await page.getByRole('button', { name: 'Enregistrer' }).click()
  await expect(page.getByText(/Enregistré\s:\svaut pour les analyses/)).toBeVisible()
  await page.reload()
  await expect(lock).toHaveValue('600')
  await expect(repositories).toHaveValue('')
  expect(errors).toEqual([])
})

test('une valeur refusée par le serveur : sous son champ, avec sa ligne ; rien n’est enregistré', async ({
  page,
}) => {
  const errors = watchConsole(page)
  await open(page)
  await ignoreField(page).fill('lodash\ndeux mots')
  await page.getByRole('button', { name: 'Enregistrer' }).click()
  await expect(page.getByRole('alert')).toContainText('1 valeur refusée')
  await expect(ignoreField(page)).toBeFocused()
  await expect(ignoreField(page)).toHaveAttribute('aria-invalid', 'true')
  await expect(page.getByText(/Ligne 2/)).toContainText('« deux mots » : un nom de paquet sans espace est attendu')
  await page.reload()
  await expect(ignoreField(page)).toHaveValue('')
  // Le refus du serveur, voulu : le navigateur le note dans la console.
  expect(errors).toEqual(['Failed to load resource: the server responded with a status of 400 (Bad Request)'])
})

test('vider le cache, après confirmation', async ({ page }) => {
  const errors = watchConsole(page)
  // Une analyse remplit le cache.
  const root = copyProject('vulnerable')
  await page.goto(`/?token=${TOKEN}`)
  await page.getByLabel("Chemin absolu d'un dossier ou d'un fichier").fill(root)
  await page.getByRole('button', { name: 'Analyser', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'vulnerable', exact: true })).toBeVisible({ timeout: 30_000 })
  // Les réglages remis par défaut au premier test : le rapport n'en dit rien.
  await expect(page.locator('#contenu').getByRole('link', { name: 'Réglages' })).toHaveCount(0)
  await navigation(page).click()
  const cache = page.getByRole('region', { name: 'Cache' })
  await expect(cache).toContainText(/réponses? gardées?/)
  const before = kept(await cache.textContent())
  await cache.getByRole('button', { name: 'Vider le cache…' }).click()
  const dialog = page.getByRole('alertdialog', { name: 'Vider le cache ?' })
  await expect(dialog.getByRole('button', { name: 'Annuler' })).toBeFocused()
  await dialog.getByRole('button', { name: 'Vider le cache' }).click()
  await expect(cache).toContainText('Cache vidé : la prochaine analyse redemande tout.')
  // « vide », ou presque : le serveur est partagé, l'analyse d'un autre test a pu y remettre
  // une réponse aussitôt (vu à E30 : « 1 réponse gardée »).
  await expect.poll(async () => kept(await cache.textContent())).toBeLessThan(before)
  expect(errors).toEqual([])
})

/** Le nombre de réponses gardées que dit la section « Cache » : 0 pour « vide ». */
function kept(text: string | null): number {
  const match = text?.match(/Contenu\s*(?:vide|([\d\s]+?)\sréponses?\sgardées?)/)
  if (!match) throw new Error(`contenu du cache illisible : ${text}`)
  return match[1] ? Number(match[1].replace(/\s/g, '')) : 0
}

test('un projet configuré : le rapport dit son forceupdate.toml, le paquet ignoré garde ses failles', async ({
  page,
}) => {
  const errors = watchConsole(page)
  const root = copyProject('vulnerable')
  writeFileSync(join(root, 'forceupdate.toml'), 'ignore = ["lodash"]\nnouveau = 1\n', 'utf-8')
  await page.goto(`/?token=${TOKEN}`)
  await page.getByLabel("Chemin absolu d'un dossier ou d'un fichier").fill(root)
  await page.getByRole('button', { name: 'Analyser', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'vulnerable', exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/Configuration du projet/)).toContainText(
    'Configuration du projet : forceupdate.toml : ignorés : lodash.',
  )
  await expect(page.getByText('forceupdate.toml : nouveau : clé inconnue, ignorée.')).toBeVisible()
  await expect(page.getByText(/Paquet ignoré : lodash \(forceupdate\.toml\)/)).toBeVisible()
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  expect(results.violations.map((violation) => `${violation.id} ${violation.nodes[0]?.target.join(' ')}`)).toEqual([])
  expect(errors).toEqual([])
})

for (const scheme of ['light', 'dark'] as const) {
  for (const width of [1440, 375]) {
    test(`l'écran Réglages, ${scheme === 'light' ? 'clair' : 'sombre'}, ${width} px`, async ({ page }) => {
      const errors = watchConsole(page)
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
      await page.setViewportSize({ width, height: 900 })
      await page.goto(`/?token=${TOKEN}`)
      await page.goto('/reglages')
      await expect(page.getByRole('button', { name: 'Enregistrer' })).toBeVisible()
      await page.getByText('Régler un écosystème à part').click()
      await expect(page.getByRole('combobox', { name: /JavaScript \(npm\)\s: pré-cocher/ })).toBeVisible()
      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
      expect(results.violations.map((violation) => `${violation.id} ${violation.nodes[0]?.target.join(' ')}`)).toEqual([])
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow).toBeLessThanOrEqual(0)
      expect(errors).toEqual([])
    })
  }
}
