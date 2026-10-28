import { useQuery } from '@tanstack/react-query'
import { api, queryKeys } from '@/api/client'

/** Une analyse (`GET /api/scans/{id}`) ; finie, elle ne change plus. */
export function useScan(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.scan(id),
    queryFn: () => api.getScan(id),
    enabled,
    staleTime: (query) => (query.state.data && query.state.data.status !== 'running' ? Infinity : 0),
  })
}

/** Un plan de mise à jour (`GET /api/updates/{id}`) ; appliqué ou échoué, il ne change plus. */
export function usePlan(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.plan(id),
    queryFn: () => api.getPlan(id),
    enabled,
    staleTime: (query) => (query.state.data && ['done', 'failed'].includes(query.state.data.status) ? Infinity : 0),
  })
}
