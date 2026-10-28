import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { TOKEN } from '../playwright.config.ts'
import { PROJECTS, copyProject, gitWithChange, removeCopies, watchConsole } from './helpers.ts'

/**
 * L'écran 5 de bout en bout : choisir → analyser → cocher → voir le diff → appliquer, sur une
 * copie du mini-projet `vulnerable` (npm et Python), dans un dossier temporaire. Le serveur de
 * test (tests/e2e_server.py) simule npm et uv : jamais de vrai outil de lockfile.
 */

test.afterAll(removeCopies)

async function analyze(page: Page, path: string) {
  await page.goto(`/?token=${TOKEN}`)
  await page.getByLabel("Chemin absolu d'un dossier ou d'un fichier").fill(path)
  await page.getByRole('button', { name: 'Analyser', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'vulnerable' })).toBeVisible({ timeout: 30_000 })
}

test('appliquer la sélection proposée sur une copie de vulnerable, sous la CSP du serveur', async ({ page }) => {
  const errors = watchConsole(page)
  const root = copyProject('vulnerable')
  await analyze(page, root)

  // Étape Choisir : la sélection proposée, groupée par lockfile.
  await page.getByRole('link', { name: /Mettre à jour/ }).click()
  await expect(page).toHaveURL(/\/analyses\/[0-9a-f]+\/mise-a-jour$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Mettre à jour vulnerable' })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'lodash' })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: 'werkzeug' })).not.toBeChecked()
  const recap = page.getByRole('complementary', { name: 'Récapitulatif' })
  await expect(recap).toContainText('3 sur 4')
  await expect(recap).toContainText('9 sur 28')

  // Étape Vérifier : les diffs, les lockfiles, le garde-fou (la copie est hors de git).
  await page.getByRole('button', { name: 'Vérifier le plan' }).click()
  await expect(page).toHaveURL(/\/plans\/[0-9a-f]+$/)
  await expect(page.getByRole('region', { name: 'Diff de package.json' })).toContainText('"lodash": "4.18.1"')
  await expect(page.getByRole('region', { name: 'Diff de requirements.in' })).toContainText('flask==0.12.5')
  await expect(page.getByText('npm trouvé')).toBeVisible()
  await expect(page.getByText('uv trouvé')).toBeVisible()
  await expect(page.getByText("Hors d'un dépôt git")).toBeVisible()

  // Appliquer, puis le résultat.
  await page.getByRole('button', { name: 'Appliquer', exact: true }).click()
  await expect(page.getByText('Mise à jour appliquée')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('version exacte')).toHaveCount(3)
  expect(readFileSync(join(root, 'package.json'), 'utf-8')).toContain('"lodash": "4.18.1"')
  expect(readFileSync(join(root, 'package-lock.json'), 'utf-8')).toContain('"version": "4.18.1"')
  expect(readFileSync(join(root, 'requirements.in'), 'utf-8')).toContain('flask==0.12.5')
  const lock = readFileSync(join(root, 'requirements.txt'), 'utf-8')
  expect(lock).toContain('flask==0.12.5')
  expect(lock).toContain('jinja2==2.11.3')

  // Relancer l'analyse : les versions relues sont les nouvelles (les failles qu'elles laissent
  // dépendent de ce que savent les réponses enregistrées d'OSV : seulement les anciennes versions).
  await page.getByRole('button', { name: "Relancer l'analyse" }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'vulnerable' })).toBeVisible({ timeout: 30_000 })
  const rows = page.getByRole('table').getByRole('row')
  await expect(rows.filter({ hasText: 'lodash' })).toContainText('4.18.1')
  await expect(rows.filter({ hasText: 'flask' })).toContainText('0.12.5')
  await expect(page.getByRole('group', { name: /Constats par type/ }).getByRole('button', { name: /Failles/ })).not.toContainText('28')

  expect(errors).toEqual([])
})

test('changer de version, voir son diff, revenir à la sélection : rien n’est écrit', async ({ page }) => {
  const errors = watchConsole(page)
  const root = copyProject('vulnerable')
  await analyze(page, root)
  await page.getByRole('link', { name: /Mettre à jour/ }).click()

  // flask en majeure : l'avertissement ; puis « Modifier la sélection » la retrouve.
  await page.getByRole('radio', { name: /^3\.1\.3,/ }).check()
  await expect(page.getByText('Une majeure est cochée')).toBeVisible()
  await page.getByRole('button', { name: 'Vérifier le plan' }).click()
  await expect(page.getByRole('region', { name: 'Diff de requirements.in' })).toContainText('flask==3.1.3')
  await page.getByRole('link', { name: 'Modifier la sélection' }).click()
  await expect(page.getByRole('radio', { name: /^3\.1\.3,/ })).toBeChecked()
  await page.goBack()
  await expect(page.getByRole('region', { name: 'Diff de requirements.in' })).toBeVisible()
  expect(readFileSync(join(root, 'requirements.in'), 'utf-8')).toContain('flask==0.12\n')

  expect(errors).toEqual([])
})

test('des changements pas encore commités : appliquer quand même, après confirmation', async ({ page }) => {
  const errors = watchConsole(page)
  const root = copyProject('vulnerable')
  gitWithChange(root, 'requirements.in')

  await analyze(page, root)
  await page.getByRole('link', { name: /Mettre à jour/ }).click()
  await page.getByRole('button', { name: 'Vérifier le plan' }).click()
  await expect(page.getByText('Changements pas encore commités')).toBeVisible()
  const force = page.getByRole('button', { name: 'Appliquer quand même…' })
  await force.click()
  const dialog = page.getByRole('alertdialog', { name: /Appliquer malgré les changements non commités/ })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Annuler' })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(force).toBeFocused()

  await force.click()
  await dialog.getByRole('button', { name: 'Appliquer quand même' }).click()
  await expect(page.getByText('Mise à jour appliquée')).toBeVisible({ timeout: 30_000 })
  const written = readFileSync(join(root, 'requirements.in'), 'utf-8')
  expect(written).toContain('flask==0.12.5')
  expect(written).toContain('# en cours')

  expect(errors).toEqual([])
})

test('de 375 à 1440 px : pas de défilement horizontal ; la barre collante sous 1024 px', async ({ page }) => {
  await analyze(page, `${PROJECTS}/vulnerable`.replaceAll('\\', '/'))
  await page.getByRole('link', { name: /Mettre à jour/ }).click()
  const choose = page.url()
  for (const width of [375, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 800 })
    await page.goto(choose)
    await expect(page.getByRole('heading', { level: 1, name: 'Mettre à jour vulnerable' })).toBeVisible()
    // Sous 1024 px, « Vérifier le plan » est dans la barre collante, en bas de l'écran.
    await expect(page.getByRole('region', { name: 'Sélection' })).toHaveCount(width < 1024 ? 1 : 0)
    if (width < 1024) {
      const bar = await page.getByRole('region', { name: 'Sélection' }).boundingBox()
      expect(bar && bar.y + bar.height).toBeLessThanOrEqual(800)
    }
    let overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, `choisir, ${width} px`).toBeLessThanOrEqual(0)
    await page.getByRole('button', { name: 'Vérifier le plan' }).click()
    await expect(page.getByRole('region', { name: 'Diff de package.json' })).toBeVisible()
    overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, `vérifier, ${width} px`).toBeLessThanOrEqual(0)
  }
})

test('un fichier envoyé : le plan, puis télécharger sa version mise à jour', async ({ page }) => {
  const errors = watchConsole(page)
  await page.goto(`/?token=${TOKEN}`)
  await page.goto('/choisir?mode=fichier')
  await page.locator('input[type="file"]').setInputFiles(join(PROJECTS, 'vulnerable', 'requirements.in'))
  await expect(page.getByRole('heading', { level: 1, name: 'requirements.in' })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('link', { name: /Mettre à jour/ }).click()
  await expect(page.getByRole('list', { name: 'Étapes' }).getByRole('listitem')).toHaveCount(2)
  await page.getByRole('button', { name: 'Vérifier le plan' }).click()
  await expect(page.getByText(/Fichier envoyé/)).toBeVisible()
  await expect(page.getByRole('button', { name: /^Appliquer/ })).toHaveCount(0)

  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Télécharger requirements.in' }).click()
  const file = await download
  expect(file.suggestedFilename()).toBe('requirements.in')
  expect(readFileSync(await file.path(), 'utf-8')).toContain('flask==0.12.5')

  expect(errors).toEqual([])
})
