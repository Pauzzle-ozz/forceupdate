import { MapPinOff } from 'lucide-react'
import { Link } from 'react-router'
import { EmptyState } from '@/components/EmptyState'
import { buttonVariants } from '@/components/ui/button'
import { Container, useDocumentTitle } from './Page'

/** Adresse inconnue du front (le serveur rend index.html pour toute adresse). */
export function NotFound() {
  useDocumentTitle('Page introuvable')
  return (
    <Container narrow>
      <EmptyState
        icon={MapPinOff}
        level="h1"
        title="Ce n'est pas la page que vous cherchez."
        actions={
          <Link to="/" className={buttonVariants({ variant: 'primary' })}>
            Retour à l'accueil
          </Link>
        }
      >
        <p>Cette adresse ne correspond à aucun écran de forceupdate.</p>
      </EmptyState>
    </Container>
  )
}
