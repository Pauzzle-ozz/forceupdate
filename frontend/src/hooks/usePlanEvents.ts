import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { api, queryKeys } from '@/api/client'
import type { ScanEvent } from '@/api/types'

/** Ce que disent les événements d'une application, jusqu'ici. */
export interface ApplyProgress {
  /** `written` : le nombre de fichiers réécrits ; `null` avant. */
  written: number | null
  /** Lockfiles régénérés sur le total (`regenerating` : `done` déjà faits). */
  done: number
  total: number
  /** Le lockfile dont l'outil tourne. */
  running: string | null
  finished: boolean
  /** Le flux est perdu et le serveur ne répond plus. */
  lost: boolean
}

const START: ApplyProgress = { written: null, done: 0, total: 0, running: null, finished: false, lost: false }

export function reduce(state: ApplyProgress, event: ScanEvent): ApplyProgress {
  switch (event.kind) {
    case 'written':
      return { ...state, written: event.total }
    case 'regenerating':
      return { ...state, done: event.done, total: event.total, running: event.name }
    case 'finished':
      return { ...state, done: state.total, running: null, finished: true }
    default:
      return state
  }
}

/**
 * La progression d'une application (`GET /api/updates/{id}/events`, Server-Sent Events), comme
 * `useScanEvents` : l'`EventSource` est fermé à `end`, puis le plan est relu (ses `results`).
 * Si le flux se coupe, on demande au serveur où en est le plan : fini, on le relit ; serveur
 * muet, la coquille le dit ; sinon `EventSource` se rebranche seul (`Last-Event-ID`).
 */
export function usePlanEvents(planId: string, onEnd?: () => void): ApplyProgress {
  const client = useQueryClient()
  const [state, setState] = useState<ApplyProgress>(START)
  const ended = useRef(onEnd)

  useEffect(() => {
    ended.current = onEnd
  }, [onEnd])

  useEffect(() => {
    const source = new EventSource(api.planEventsUrl(planId))
    // Comme `useScanEvents` : un AbortController, pas un `let` réaffecté dans le nettoyage.
    const closed = new AbortController()
    const close = () => {
      closed.abort()
      source.close()
    }
    const finish = () => {
      if (closed.signal.aborted) return
      close()
      ended.current?.()
      void client.invalidateQueries({ queryKey: queryKeys.plan(planId) })
    }
    source.addEventListener('progress', (message) => {
      const event = JSON.parse((message as MessageEvent<string>).data) as ScanEvent
      setState((current) => reduce(current, event))
    })
    source.addEventListener('end', finish)
    source.addEventListener('error', () => {
      if (closed.signal.aborted) return
      api
        .getPlan(planId)
        .then((plan) => {
          if (plan.status !== 'running') finish()
        })
        .catch(() => {
          close()
          setState((current) => ({ ...current, lost: true }))
        })
    })
    return close
  }, [planId, client])

  return state
}
