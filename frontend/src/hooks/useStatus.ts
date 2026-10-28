import { useSyncExternalStore } from 'react'
import { connectionStore, type Connection } from '@/api/client'

function subscribeOnline(listener: () => void) {
  window.addEventListener('online', listener)
  window.addEventListener('offline', listener)
  return () => {
    window.removeEventListener('online', listener)
    window.removeEventListener('offline', listener)
  }
}

/** Le réseau de la machine (le serveur est sur la même : c'est aussi le sien). */
export function useOnline(): boolean {
  return useSyncExternalStore(
    subscribeOnline,
    () => navigator.onLine,
    () => true,
  )
}

/** Où en est la liaison avec le serveur local : répond, arrêté, session terminée. */
export function useConnection(): Connection {
  return useSyncExternalStore(connectionStore.subscribe, connectionStore.get, () => 'ok' as Connection)
}
