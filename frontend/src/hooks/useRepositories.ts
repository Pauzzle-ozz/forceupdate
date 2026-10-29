import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, queryKeys } from '@/api/client'
import type { BatchRequest, RepositoryList } from '@/api/types'

/** Toutes les combien de millisecondes la liste est relue pendant une analyse. */
export const REPOSITORIES_POLL = 1000

/** Une analyse de la liste tourne encore (en lot ou seule). */
export function analyzing(list: RepositoryList | undefined): boolean {
  if (!list) return false
  return list.batch?.status === 'running' || list.repositories.some((row) => row.state === 'running')
}

/**
 * Les dépôts des comptes connectés (`GET /api/repositories`), relus tant qu'une analyse tourne :
 * la progression par dépôt et la synthèse viennent du serveur.
 */
export function useRepositories({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: queryKeys.repositories,
    queryFn: () => api.listRepositories(),
    enabled,
    refetchInterval: (query) => (analyzing(query.state.data) ? REPOSITORIES_POLL : false),
  })
}

/** Redemande la liste aux forges. */
export function useReloadRepositories() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.listRepositories(true),
    onSuccess: (list) => client.setQueryData(queryKeys.repositories, list),
  })
}

/** Lance une analyse groupée ; la liste relue montre aussitôt les dépôts en cours. */
export function useStartBatch() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (request: BatchRequest) => api.startBatch(request),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.repositories })
      void client.invalidateQueries({ queryKey: queryKeys.scans })
    },
  })
}

export function useCancelBatch() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.cancelBatch(id),
    onSuccess: () => void client.invalidateQueries({ queryKey: queryKeys.repositories }),
  })
}
