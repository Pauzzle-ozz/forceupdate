import { execFileSync } from 'node:child_process'
import { appendFileSync, cpSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import type { Page } from '@playwright/test'

/** Les mini-projets des tests (tests/projects). */
export const PROJECTS = resolve(import.meta.dirname, '../../tests/projects')

const copies: string[] = []

/**
 * Une copie du mini-projet `name` dans un dossier temporaire, hors de tout dépôt git (la
 * mise à jour l'écrit) ; son chemin au format de l'API. `removeCopies` les efface.
 */
export function copyProject(name: string): string {
  const folder = mkdtempSync(join(tmpdir(), 'forceupdate-e2e-'))
  copies.push(folder)
  cpSync(join(PROJECTS, name), join(folder, name), { recursive: true })
  return join(folder, name).replaceAll('\\', '/')
}

export function removeCopies() {
  for (const folder of copies.splice(0)) rmSync(folder, { recursive: true, force: true })
}

/** Fait de `root` un dépôt git commité, puis y laisse un changement pas encore commité. */
export function gitWithChange(root: string, file: string) {
  const git = (...args: string[]) =>
    execFileSync(
      'git',
      ['-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false', '-c', 'core.autocrlf=false', ...args],
      { cwd: root, stdio: 'ignore' },
    )
  git('init', '-q')
  git('add', '.')
  git('commit', '-q', '-m', 'départ')
  appendFileSync(join(root, file), '# en cours\n')
}

/** Les erreurs de la console (une ressource refusée par la CSP en est une). */
export function watchConsole(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  page.on('pageerror', (error) => errors.push(error.message))
  return errors
}
