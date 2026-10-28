import { useQueryClient } from '@tanstack/react-query'
import { Lock, RefreshCw, ServerOff } from 'lucide-react'
import { useState } from 'react'
import { api } from '@/api/client'
import { Alert, AlertActions, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useConnection } from '@/hooks/useStatus'
import { fr } from '@/lib/format'

/**
 * Les états communs de la coquille (ECRANS.md) : serveur arrêté (`fetch` qui échoue), session
 * terminée (`401`). En bandeau sous l'en-tête, au-dessus de l'écran.
 */
export function Banners() {
  const connection = useConnection()
  const client = useQueryClient()
  const [retrying, setRetrying] = useState(false)

  async function retry() {
    setRetrying(true)
    try {
      await api.listScans()
      await client.refetchQueries({ type: 'active' })
    } catch {
      // toujours arrêté : le bandeau reste
    } finally {
      setRetrying(false)
    }
  }

  if (connection === 'down') {
    return (
      <Alert variant="danger" banner role="alert">
        <ServerOff aria-hidden="true" />
        <AlertTitle>Le serveur local ne répond plus</AlertTitle>
        <AlertDescription>
          <p>
            Il a sans doute été arrêté (Ctrl+C dans le terminal). Le relancer avec{' '}
            <code>forceupdate ui</code>, puis ouvrir l'adresse qu'il affiche.
          </p>
        </AlertDescription>
        <AlertActions>
          <Button size="sm" onClick={retry} disabled={retrying}>
            <RefreshCw className={retrying ? 'animate-spin' : undefined} aria-hidden="true" />
            Réessayer
          </Button>
        </AlertActions>
      </Alert>
    )
  }
  if (connection === 'session') {
    return (
      <Alert variant="warning" banner role="alert">
        <Lock aria-hidden="true" />
        <AlertTitle>Session terminée</AlertTitle>
        <AlertDescription>
          <p>
            {fr("Le serveur a redémarré : son jeton a changé. Ouvrir l'adresse que")}{' '}
            <code>forceupdate ui</code>{' '}
            {fr(
              'affiche dans le terminal (elle contient le nouveau jeton). Les analyses de la session précédente sont perdues ; les chemins récents restent.',
            )}
          </p>
        </AlertDescription>
      </Alert>
    )
  }
  return null
}
