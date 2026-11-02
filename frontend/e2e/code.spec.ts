import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'
import { TOKEN } from '../playwright.config.ts'
import { PROJECTS, copyProject, removeCopies, watchConsole } from './helpers.ts'

/**
 * Un fichier de code choisi seul (E28), de bout en bout sur le vrai serveur : déposé sur la page
 * (un script à bloc PEP 723 : le plan, puis sa version réécrite à télécharger), choisi dans un
 * projet (analysé via son manifeste), ou sans projet autour (ses imports, sans version). Les
 * copies sont dans un dossier temporaire, hors du dépôt : dans le dépôt, un `.py` serait
 * analysé à travers le `pyproject.toml` de forceupdate lui-même.
 */

test.afterAll(removeCopies)

/** Glisse un fichier sur la page puis le dépose, comme le ferait l'explorateur de fichiers. */
async function dropFile(page: Page, name: string, content: string) {
  const transfer = await page.evaluateHandle(
    ([fileName, text]) => {
      const data = new DataTransfer()
      data.items.add(new File([text], fileName, { type: 'text/plain' }))
      return data
    },
    [name, content] as const,
  )
  await page.dispatchEvent('body', 'dragenter', { dataTransfer: transfer })
  await expect(page.getByTestId('drop-overlay')).toContainText('Déposer pour analyser ce fichier')
  await page.dispatchEvent('body', 'dragover', { dataTransfer: transfer })
  await page.dispatchEvent('body', 'drop', { dataTransfer: transfer })
}

async function analyze(page: Page, path: string, title: string) {
  await page.goto(`/?token=${TOKEN}`)
  await page.getByLabel("Chemin absolu d'un dossier ou d'un fichier").fill(path)
  await page.getByRole('button', { name: 'Analyser', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1, name: title, exact: true })).toBeVisible({ timeout: 30_000 })
}

test('déposer un script à bloc PEP 723 : son bloc est son manifeste, sa version réécrite se télécharge', async ({
  page,
}) => {
  const errors = watchConsole(page)
  const content = readFileSync(join(PROJECTS, 'scripts', 'pep723.py'), 'utf-8')
  await page.goto(`/?token=${TOKEN}`)
  await page.goto('/choisir?mode=fichier')
  await dropFile(page, 'pep723.py', content)
  await expect(page.getByRole('heading', { level: 1, name: 'pep723.py', exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/Script à bloc PEP 723/)).toContainText('tient lieu de manifeste, comme pour uv run')
  await expect(page.getByRole('button', { name: /Versions non fixées/ })).toContainText('1')
  await expect(page.getByText('1 version non fixée')).toBeVisible()

  await page.getByRole('link', { name: /Mettre à jour/ }).click()
  await page.getByRole('button', { name: 'Vérifier le plan' }).click()
  await expect(page.getByText(/Fichier envoyé/)).toBeVisible()
  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Télécharger pep723.py' }).click()
  const file = await download
  expect(file.suggestedFilename()).toBe('pep723.py')
  const rewritten = readFileSync(await file.path(), 'utf-8').split('\n')
  const original = content.split('\n')
  // Seule la ligne de flask change, dans le bloc.
  const changed = original.flatMap((line, index) => (line === rewritten[index] ? [] : [index]))
  expect(changed).toEqual([4])
  expect(rewritten[4]).toMatch(/^# {3}"flask>=\d/)

  expect(errors).toEqual([])
})

test('un fichier de code dans un projet : analysé via son manifeste', async ({ page }) => {
  const errors = watchConsole(page)
  const root = copyProject('eol')
  await analyze(page, `${root}/app/__init__.py`, '__init__.py')
  await expect(page.getByText(/Fichier de code dans un projet/)).toContainText('analysé via pyproject.toml')
  await expect(page.locator('section#fins-de-vie').getByRole('listitem')).toHaveCount(3)
  expect(errors).toEqual([])
})

for (const scheme of ['light', 'dark'] as const) {
  for (const width of [1440, 375]) {
    test(`ses imports seulement, ${scheme === 'light' ? 'clair' : 'sombre'}, ${width} px`, async ({ page }) => {
      const errors = watchConsole(page)
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' })
      await page.setViewportSize({ width, height: 900 })
      const root = copyProject('scripts')
      await analyze(page, `${root}/imports.py`, 'imports.py')
      await expect(page.getByText('Fichier de code sans projet autour : ses imports, sans version.')).toBeVisible()
      await expect(page.getByText('4 versions non fixées')).toBeVisible()
      await expect(page.getByText('Rien à mettre à jour')).toHaveCount(0)
      const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
      expect(results.violations.map((violation) => `${violation.id} ${violation.nodes[0]?.target.join(' ')}`)).toEqual([])
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow).toBeLessThanOrEqual(0)
      expect(errors).toEqual([])
    })
  }
}
