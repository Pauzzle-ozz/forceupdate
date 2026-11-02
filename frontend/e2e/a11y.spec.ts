import { mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { TOKEN } from '../playwright.config.ts'
import { copyProject, gitWithChange, removeCopies } from './helpers.ts'

/**
 * L'accessibilité des écrans 1 à 5 (MASTER, « Accessibilité ») : axe-core, règles WCAG 2.1 A et
 * AA (contrastes compris), en clair et en sombre, au large et à 375 px.
 */
const VULNERABLE = resolve(import.meta.dirname, '../../tests/projects/vulnerable').replaceAll('\\', '/')
const EOL = resolve(import.meta.dirname, '../../tests/projects/eol').replaceAll('\\', '/')

async function audit(page: Page, where: string) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  const found = results.violations.map(
    (violation) => `${where} : ${violation.id} (${violation.nodes.length}) ${violation.nodes[0]?.target.join(' ')}`,
  )
  expect(found).toEqual([])
}

for (const scheme of ['light', 'dark'] as const) {
  for (const width of [1440, 375]) {
    test(`écrans 1 à 4, ${scheme === 'light' ? 'clair' : 'sombre'}, ${width} px`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
      await page.setViewportSize({ width, height: 900 })
      await page.goto(`/?token=${TOKEN}`)
      await expect(page.getByRole('heading', { level: 1, name: 'Analyser du code' })).toBeVisible()
      await audit(page, 'accueil')

      await page.goto(`/choisir?mode=dossier&chemin=${encodeURIComponent(VULNERABLE)}`)
      await expect(page.getByRole('button', { name: /requirements\.in/ })).toBeVisible()
      await audit(page, 'choisir')

      await page.goto('/')
      await page.getByLabel("Chemin absolu d'un dossier ou d'un fichier").fill(VULNERABLE)
      await page.getByRole('button', { name: 'Analyser', exact: true }).click()
      await expect(page.getByRole('heading', { level: 1, name: 'vulnerable' })).toBeVisible({ timeout: 30_000 })
      await audit(page, 'rapport')

      await page.getByRole('button', { name: 'flask, voir le détail' }).click()
      await expect(page.getByRole('dialog', { name: 'flask' })).toBeVisible()
      await audit(page, 'détail')
    })
  }
}

for (const scheme of ['light', 'dark'] as const) {
  for (const width of [1440, 375]) {
    test(`écran 4, fins de vie, ${scheme === 'light' ? 'clair' : 'sombre'}, ${width} px`, async ({ page }) => {
      // E27 : Python 3.8, Node.js 16 et Django 3.2 en fin de vie (tests/projects/eol).
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
      await page.setViewportSize({ width, height: 900 })
      await page.goto(`/?token=${TOKEN}`)
      await page.getByLabel("Chemin absolu d'un dossier ou d'un fichier").fill(EOL)
      await page.getByRole('button', { name: 'Analyser', exact: true }).click()
      await expect(page.getByRole('heading', { level: 1, name: 'eol', exact: true })).toBeVisible({ timeout: 30_000 })
      const section = page.locator('section#fins-de-vie')
      await expect(section.getByRole('listitem')).toHaveCount(3)
      await expect(section).toContainText('Fin de vie depuis le 7 oct. 2024.')
      await audit(page, 'rapport, fins de vie')
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow).toBeLessThanOrEqual(0)
    })
  }
}

test.afterAll(removeCopies)

for (const scheme of ['light', 'dark'] as const) {
  for (const width of [1440, 375]) {
    test(`écran 5, ${scheme === 'light' ? 'clair' : 'sombre'}, ${width} px`, async ({ page }) => {
      // Une copie dans git, avec un changement pas encore commité : le garde-fou et sa confirmation.
      // Sa CI en Node 22 (E32) : la case « npm 10 » du plan, et la relecture dans le résultat.
      const root = copyProject('vulnerable')
      mkdirSync(join(root, '.github', 'workflows'), { recursive: true })
      writeFileSync(
        join(root, '.github', 'workflows', 'ci.yml'),
        'jobs:\n  test:\n    steps:\n      - uses: actions/setup-node@v4\n        with:\n          node-version: 22\n',
      )
      gitWithChange(root, 'requirements.in')
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
      await page.setViewportSize({ width, height: 900 })
      await page.goto(`/?token=${TOKEN}`)
      await page.getByLabel("Chemin absolu d'un dossier ou d'un fichier").fill(root)
      await page.getByRole('button', { name: 'Analyser', exact: true }).click()
      await expect(page.getByRole('heading', { level: 1, name: 'vulnerable' })).toBeVisible({ timeout: 30_000 })

      await page.getByRole('link', { name: /Mettre à jour/ }).click()
      await page.getByRole('radio', { name: /^3\.1\.3,/ }).check()
      await expect(page.getByText('Une majeure est cochée')).toBeVisible()
      await audit(page, 'choisir')

      await page.getByRole('button', { name: 'Vérifier le plan' }).click()
      await expect(page.getByRole('region', { name: 'Diff de package.json' })).toBeVisible()
      await expect(page.getByRole('checkbox', { name: 'Régénérer avec npm 10, celui du projet' })).toBeChecked()
      await audit(page, 'vérifier')

      await page.getByRole('button', { name: 'Appliquer quand même…' }).click()
      await expect(page.getByRole('alertdialog')).toBeVisible()
      await audit(page, 'confirmation')

      await page.getByRole('alertdialog').getByRole('button', { name: 'Appliquer quand même' }).click()
      await expect(page.getByText('Mise à jour appliquée')).toBeVisible({ timeout: 30_000 })
      await expect(page.getByText(/: accepté\.$/)).toBeVisible()
      await audit(page, 'résultat')
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow).toBeLessThanOrEqual(0)
    })
  }
}

test('le clavier : lien d’évitement, focus visible, Échap, focus rendu', async ({ page }) => {
  await page.goto(`/?token=${TOKEN}`)
  await page.keyboard.press('Tab')
  const skip = page.getByRole('link', { name: 'Aller au contenu' })
  await expect(skip).toBeFocused()
  await expect(skip).toBeInViewport()
  const outline = await skip.evaluate((element) => getComputedStyle(element).outlineStyle)
  expect(outline).toBe('solid')
  await page.keyboard.press('Enter')
  await expect(page.locator('#contenu')).toBeFocused()

  await page.getByLabel("Chemin absolu d'un dossier ou d'un fichier").fill(VULNERABLE)
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: 'vulnerable' })).toBeVisible({ timeout: 30_000 })
  const opener = page.getByRole('button', { name: 'lodash, voir le détail' })
  await opener.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'lodash', level: 2 })).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(opener).toBeFocused()
})
