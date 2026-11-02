import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, queryKeys } from '@/api/client'
import type { SettingsDocument, SettingsRequest } from '@/api/types'

/** Les réglages de la personne et l'état du cache (`GET /api/settings`). */
export function useSettings() {
  return useQuery({ queryKey: queryKeys.settings, queryFn: api.getSettings })
}

/** Enregistre les réglages ; la réponse remplace ceux qu'on avait. */
export function useSaveSettings() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: SettingsRequest) => api.saveSettings(body),
    onSuccess: (document) => client.setQueryData(queryKeys.settings, document),
  })
}

/** Vide le cache disque ; son nouvel état remplace l'ancien. */
export function useClearCache() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: api.clearCache,
    onSuccess: (cache) =>
      client.setQueryData<SettingsDocument>(queryKeys.settings, (document) =>
        document ? { ...document, cache } : document,
      ),
  })
}
