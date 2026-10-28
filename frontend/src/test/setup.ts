/**
 * Mise en place des tests de composants (Vitest, jsdom). jsdom n'a ni `matchMedia`, ni
 * `EventSource`, ni `<dialog>` modal : de petits simulateurs les remplacent. Aucun test ne
 * touche le réseau : `fetch` est simulé par test (src/test/api.ts).
 */
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'
import { connectionStore } from '@/api/client'
import { display } from './display'
import { FakeEventSource } from './events'

function matchMedia(query: string): MediaQueryList {
  const min = /min-width:\s*(\d+)px/.exec(query)
  const matches = min ? display.wide && Number(min[1]) <= 1440 : query.includes('dark') ? display.dark : false
  return {
    matches,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }
}

Object.defineProperty(window, 'matchMedia', { configurable: true, value: matchMedia })
Object.defineProperty(window, 'EventSource', { configurable: true, value: FakeEventSource })
window.scrollTo = () => {}
window.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
Element.prototype.scrollIntoView = () => {}

// Le <dialog> modal : ouvert / fermé, avec ses événements.
HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
  this.setAttribute('open', '')
}
HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
  if (!this.hasAttribute('open')) return
  this.removeAttribute('open')
  this.dispatchEvent(new Event('close'))
}

beforeEach(() => {
  display.wide = true
  display.dark = false
  localStorage.clear()
  document.documentElement.className = ''
  connectionStore.set('ok')
  FakeEventSource.reset()
  Object.defineProperty(navigator, 'onLine', { configurable: true, get: () => true })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})
