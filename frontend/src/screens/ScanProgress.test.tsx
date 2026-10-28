import { act, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { mockApi, renderApp, scanDetail } from '@/test/api'
import { FakeEventSource } from '@/test/events'
import { useThrottled } from './ScanProgress'

const EVENTS = '/api/scans/a1/events'

function running() {
  return scanDetail({
    status: 'running',
    finished_at: null,
    report: null,
    summary: null,
    progress: null,
    started_at: new Date().toISOString(),
  })
}

function event(kind: string, done = 0, total = 0, ecosystem: string | null = null, name: string | null = null) {
  return { kind, done, total, ecosystem, name }
}

describe('l’analyse en cours (écran 3)', () => {
  it('suit les étapes, puis devient le rapport à « end » et ferme le flux', async () => {
    let state = running()
    mockApi({ 'GET /api/scans/a1': () => state })
    renderApp('/analyses/a1')
    expect(await screen.findByRole('heading', { level: 1, name: /Analyse de vulnerable/ })).toBeInTheDocument()
    const blade = screen.getByRole('progressbar', { name: 'Analyse de vulnerable' })
    // Indéterminée tant que le total n'est pas connu.
    expect(blade).not.toHaveAttribute('aria-valuenow')

    const source = FakeEventSource.last(EVENTS)
    act(() => {
      source.emit('progress', event('reading'))
      source.emit('progress', event('projects_found', 0, 1))
      source.emit('progress', event('checking', 0, 3))
      source.emit('progress', event('package_checked', 1, 3, 'npm', 'lodash'))
    })
    expect(screen.getByText('1 projet trouvé')).toBeInTheDocument()
    expect(screen.getByText(/Vérification des paquets et des failles : 1 sur 3/)).toBeInTheDocument()
    expect(screen.getByText('npm lodash')).toBeInTheDocument()
    expect(blade).toHaveAttribute('aria-valuenow', '1')
    expect(blade).toHaveAttribute('aria-valuemax', '3')
    // Le clin d'œil : sous la ligne, jamais annoncé.
    expect(screen.getByText('Recherche d’une perturbation dans la Force…'.replace('’', "'"))).toHaveAttribute('aria-hidden', 'true')
    // L'étape en cours est annoncée, sans les nombres.
    expect(screen.getByText('Vérification des paquets et recherche des failles en cours.')).toBeInTheDocument()

    act(() => {
      source.emit('progress', event('vulnerabilities_checked', 2, 3))
      source.emit('progress', event('package_checked', 3, 3, 'PyPI', 'flask'))
      source.emit('progress', event('finished'))
    })
    state = scanDetail()
    act(() => source.emit('end', { status: 'done', error: null }))
    expect(source.closed).toBe(true)
    const title = await screen.findByRole('heading', { level: 1, name: 'vulnerable' })
    expect(screen.getByText('Synthèse')).toBeInTheDocument()
    // L'analyse a fini sous les yeux : le focus va au titre du rapport.
    await waitFor(() => expect(title).toHaveFocus())
  })

  it('« Annuler » envoie DELETE, passe en « Annulation… », puis montre « Analyse annulée »', async () => {
    let state = running()
    const calls = mockApi({
      'GET /api/scans/a1': () => state,
      'DELETE /api/scans/a1': () => {
        state = scanDetail({ status: 'cancelled', report: null, summary: null })
        return state
      },
    })
    const user = userEvent.setup()
    renderApp('/analyses/a1')
    await user.click(await screen.findByRole('button', { name: 'Annuler' }))
    expect(calls.some((call) => call.method === 'DELETE')).toBe(true)
    expect(screen.getByRole('button', { name: 'Annulation…' })).toBeDisabled()
    act(() => FakeEventSource.last(EVENTS).emit('end', { status: 'cancelled', error: null }))
    expect(await screen.findByRole('heading', { name: 'Analyse annulée' })).toBeInTheDocument()
  })

  it('une analyse échouée montre son erreur, avec « Relancer »', async () => {
    let state = running()
    mockApi({ 'GET /api/scans/a1': () => state })
    renderApp('/analyses/a1')
    await screen.findByRole('button', { name: 'Annuler' })
    state = scanDetail({ status: 'failed', error: 'Lecture impossible : accès refusé.', report: null, summary: null })
    act(() => FakeEventSource.last(EVENTS).emit('end', { status: 'failed', error: state.error }))
    expect(await screen.findByText('Lecture impossible : accès refusé.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: "Relancer l'analyse" })).toBeInTheDocument()
  })

  it('flux coupé : si l’analyse est finie entre-temps, elle est relue', async () => {
    let state = running()
    mockApi({ 'GET /api/scans/a1': () => state })
    renderApp('/analyses/a1')
    await screen.findByRole('button', { name: 'Annuler' })
    const source = FakeEventSource.last(EVENTS)
    state = scanDetail()
    act(() => source.fail())
    expect(await screen.findByText('Synthèse')).toBeInTheDocument()
    expect(source.closed).toBe(true)
  })

  it('hors ligne : le bandeau « cache seulement »', async () => {
    mockApi({
      'GET /api/scans/a1': { ...running(), options: { ...running().options, offline: true } },
    })
    renderApp('/analyses/a1')
    expect(await screen.findByText(/Analyse hors ligne/)).toBeInTheDocument()
  })
})

describe('les annonces du paquet en cours', () => {
  it('au plus une toutes les 5 s, la dernière gagne', () => {
    vi.useFakeTimers()
    const { result, rerender } = renderHook(({ value }) => useThrottled(value, 5000), {
      initialProps: { value: 'npm a' },
    })
    expect(result.current).toBe('npm a')
    rerender({ value: 'npm b' })
    rerender({ value: 'npm c' })
    expect(result.current).toBe('npm a')
    act(() => vi.advanceTimersByTime(5000))
    expect(result.current).toBe('npm c')
  })
})
