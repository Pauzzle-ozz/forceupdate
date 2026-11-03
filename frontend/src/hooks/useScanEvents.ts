import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, queryKeys } from '@/api/client'
import type { EventKind, ScanEvent } from '@/api/types'

/** Ce que disent les événements d'une analyse, jusqu'ici. */
export interface ScanProgress {
  /** Les étapes déjà annoncées. */
  seen: ReadonlySet<EventKind>
  /** `projects_found` : le nombre de projets. */
  projects: number | null
  /** Vérifications faites sur le total (une par paquet, plus une pour les failles). */
  done: number
  total: number
  /** Le dernier paquet vérifié. */
  last: { ecosystem: string; name: string } | null
  /** Un dépôt : ses fichiers de dépendances téléchargés sur le total. */
  downloaded: { done: number; total: number } | null
  /** Le flux est perdu et le serveur ne répond plus. */
  lost: boolean
}

const START: ScanProgress = { seen: new Set(), projects: null, done: 0, total: 0, last: null, downloaded: null, lost: false }

export function reduce(state: ScanProgress, event: ScanEvent): ScanProgress {
  const seen = new Set(state.seen).add(event.kind)
  const next: ScanProgress = { ...state, seen }
  if (event.kind === 'projects_found') next.projects = event.total
  if (event.kind === 'downloading') next.downloaded = { done: event.done, total: event.total }
  if (event.kind === 'checking' || event.kind === 'package_checked' || event.kind === 'vulnerabilities_checked') {
    next.done = event.done
    next.total = event.total
  }
  if (event.kind === 'package_checked' && event.ecosystem && event.name) {
    next.last = { ecosystem: event.ecosystem, name: event.name }
  }
  return next
}

/**
 * La progression d'une analyse en cours (`GET /api/scans/{id}/events`, Server-Sent Events).
 * L'`EventSource` est fermé à l'événement `end` (sinon il se rebrancherait) ; l'analyse est
 * alors relue (son statut, son rapport). Si le flux se coupe, on demande au serveur où en est
 * l'analyse : finie, on la relit ; serveur muet, la coquille le dit ; sinon `EventSource` se
 * rebranche seul et reprend après le dernier événement reçu (`Last-Event-ID`).
 */
export function useScanEvents(scanId: string, onEnd?: () => void): ScanProgress {
  const client = useQueryClient()
  const [state, setState] = useState<ScanProgress>(START)
  const ended = useRef(onEnd)

  useEffect(() => {
    ended.current = onEnd
  }, [onEnd])

  useEffect(() => {
    const source = new EventSource(api.scanEventsUrl(scanId))
    // Fermé : à la fin, au flux perdu, au démontage. Un AbortController plutôt qu'un `let` : la
    // règle react(immutability) d'oxlint refuse une variable réaffectée dans le nettoyage.
    const closed = new AbortController()
    const close = () => {
      closed.abort()
      source.close()
    }
    const finish = () => {
      if (closed.signal.aborted) return
      close()
      ended.current?.()
      void client.invalidateQueries({ queryKey: queryKeys.scan(scanId) })
      void client.invalidateQueries({ queryKey: queryKeys.scans })
    }
    source.addEventListener('progress', (message) => {
      const event = JSON.parse((message as MessageEvent<string>).data) as ScanEvent
      setState((current) => reduce(current, event))
    })
    source.addEventListener('end', finish)
    source.addEventListener('error', () => {
      if (closed.signal.aborted) return
      api
        .getScan(scanId)
        .then((scan) => {
          if (scan.status !== 'running') finish()
        })
        .catch(() => {
          close()
          setState((current) => ({ ...current, lost: true }))
        })
    })
    return close
  }, [scanId, client])

  return state
}
