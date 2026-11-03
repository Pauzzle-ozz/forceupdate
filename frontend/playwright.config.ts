import { defineConfig, devices } from '@playwright/test'

/**
 * Les tests de bout en bout : le vrai serveur de `forceupdate ui` (tests/e2e_server.py : hors
 * ligne, réponses enregistrées, cache et chemins récents dans un dossier temporaire, jeton
 * fixe), qui sert le front construit (`npm run build`) sous sa vraie CSP.
 */
export const PORT = 8799
export const TOKEN = 'jeton-e2e'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  forbidOnly: !!process.env.CI,
  // Tous les tests passent par le même serveur (ses analyses, ses mises à jour, ses comptes) : en
  // parallèle sur une machine de CI lente, l'analyse d'un test attendait celles d'un autre au-delà
  // de son délai (E35, Windows). Un seul à la fois sur la CI ; en parallèle ici.
  workers: process.env.CI ? 1 : undefined,
  // Sur la CI, la durée de chaque test aussi (list), pour comprendre un délai dépassé.
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `uv run python ../tests/e2e_server.py --port ${PORT} --token ${TOKEN}`,
    // Sans jeton, le serveur répond 401 : Playwright le tient pour prêt.
    url: `http://127.0.0.1:${PORT}/api/scans`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
