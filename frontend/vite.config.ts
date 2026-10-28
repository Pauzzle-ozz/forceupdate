/// <reference types="vitest/config" />
import { readFileSync } from 'node:fs'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type ProxyOptions } from 'vite'

const root = import.meta.dirname

/** La version de forceupdate, lue dans pyproject.toml (le seul endroit où elle est écrite). */
function version(): string {
  const pyproject = readFileSync(`${root}/../pyproject.toml`, 'utf-8')
  return /^version = "(.+)"$/m.exec(pyproject)?.[1] ?? '0.0.0'
}

/**
 * En dev, le serveur de Vite passe /api au serveur de `forceupdate ui`, dont l'adresse
 * d'entrée (jeton compris) est dans FORCEUPDATE_URL. Le garde du serveur refuse un `Host` ou
 * une `Origin` qui ne sont pas les siens : le proxy les réécrit vers son adresse, et porte le
 * jeton en `Authorization: Bearer`. Le garde n'est jamais affaibli pour le dev.
 */
function apiProxy(entry: string | undefined): Record<string, ProxyOptions> | undefined {
  if (!entry) return undefined
  const url = new URL(entry)
  const token = url.searchParams.get('token')
  if (!token) throw new Error("FORCEUPDATE_URL : l'adresse affichée par « forceupdate ui », jeton compris")
  return {
    '/api': {
      target: url.origin,
      changeOrigin: true,
      configure(proxy) {
        proxy.on('proxyReq', (request) => {
          request.setHeader('origin', url.origin)
          request.setHeader('authorization', `Bearer ${token}`)
        })
      },
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': `${root}/src` } },
  define: { __FORCEUPDATE_VERSION__: JSON.stringify(version()) },
  build: {
    // Le front construit est servi par forceupdate ui, et livré dans le paquet Python.
    outDir: '../src/forceupdate/web/static',
    emptyOutDir: true,
    // CSP du serveur (default-src 'self') : pas de data: (polices, images) dans le CSS.
    assetsInlineLimit: 0,
  },
  server: { proxy: apiProxy(process.env.FORCEUPDATE_URL) },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
