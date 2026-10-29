import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, queryKeys } from '@/api/client'
import type { ProposalRequest, RepositoryKey } from '@/api/types'

/** Toutes les combien de millisecondes un récapitulatif est relu pendant son envoi. */
export const PROPOSAL_POLL = 1000

/** Un récapitulatif de PR, relu chaque seconde tant que son envoi tourne. */
export function useProposal(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.proposal(id),
    queryFn: () => api.getProposal(id),
    enabled,
    refetchInterval: (query) => (query.state.data?.status === 'running' ? PROPOSAL_POLL : false),
  })
}

/** Prépare un récapitulatif : rien n'est cloné ni poussé. */
export function useCreateProposal() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (request: ProposalRequest) => api.createProposal(request),
    onSuccess: (proposal) => {
      client.setQueryData(queryKeys.proposal(proposal.id), proposal)
      // Les PR déjà ouvertes qu'il a trouvées s'affichent dans la liste des dépôts.
      void client.invalidateQueries({ queryKey: queryKeys.repositories })
    },
  })
}

/** Envoie les dépôts cochés d'un récapitulatif. */
export function useSendProposal(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (repositories: RepositoryKey[]) => api.sendProposal(id, repositories),
    onSuccess: (proposal) => client.setQueryData(queryKeys.proposal(id), proposal),
  })
}
