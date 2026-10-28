import { resolve } from 'node:path'
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { TOKEN } from '../playwright.config.ts'

/**
 * L'accessibilité des écrans 1 à 4 (MASTER, « Accessibilité ») : axe-core, règles WCAG 2.1 A et
 * AA (contrastes compris), en clair et en sombre, au large et à 375 px.
 */
const VULNERABLE = resolve(import.meta.dirname, '../../tests/projects/vulnerable').replaceAll('\\', '/')

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
