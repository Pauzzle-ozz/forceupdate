import { useQuery } from '@tanstack/react-query'
import { api, queryKeys } from '@/api/client'

/** Toutes les combien de millisecondes une connexion en attente est relue. */
export const CONNECTION_POLL = 2000

/** Les forges et les comptes connectés (`GET /api/accounts`). */
export function useAccounts() {
  return useQuery({ queryKey: queryKeys.accounts, queryFn: api.listAccounts })
}

/**
 * Une connexion (OAuth ou device flow), relue tant qu'elle attend : c'est le serveur qui attend
 * l'autorisation auprès de la forge. Finie, elle ne change plus.
 */
export function useAccountConnection(id: string | null) {
  return useQuery({
    queryKey: queryKeys.connection(id ?? ''),
    queryFn: () => api.getConnection(id ?? ''),
    enabled: id !== null,
    refetchInterval: (query) => (query.state.data?.status === 'pending' ? CONNECTION_POLL : false),
    staleTime: (query) => (query.state.data && query.state.data.status !== 'pending' ? Infinity : 0),
  })
}

/** Quitter la page pour une autre adresse (la page d'autorisation de la forge). Les tests le remplacent. */
export const browser = {
  go(url: string) {
    window.location.assign(url)
  },
}
