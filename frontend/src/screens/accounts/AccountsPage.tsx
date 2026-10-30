import { CircleX, Clock, ShieldCheck } from 'lucide-react'
import { useCallback } from 'react'
import { useSearchParams } from 'react-router'
import type { ForgeStatus } from '@/api/types'
import { ForgeLogo } from '@/components/ForgeLogo'
import { Alert, AlertActions, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useAccounts } from '@/hooks/useAccounts'
import { fr } from '@/lib/format'
import { Container, PageHead, Section, useDocumentTitle } from '@/shell/Page'
import { ForgeCard, errorText } from './ForgeCard'

/**
 * Écran 6 : connecter ou déconnecter GitHub, GitLab, Bitbucket ; qui est connecté, avec quels
 * droits (ECRANS.md). `?connexion=<id>` : le retour d'une autorisation OAuth, dont on montre
 * l'issue.
 */
export function AccountsPage() {
  useDocumentTitle('Comptes')
  const accounts = useAccounts()
  const [params, setParams] = useSearchParams()
  const returned = params.get('connexion')
  const forgetReturn = useCallback(() => {
    setParams(
      (current) => {
        current.delete('connexion')
        return current
      },
      { replace: true },
    )
  }, [setParams])

  const forges = accounts.data?.forges ?? []
  const available = forges.filter((forge) => forge.available)
  const soon = forges.filter((forge) => !forge.available)

  return (
    <Container narrow>
      <PageHead>
        <h1 className="text-2xl">Comptes</h1>
        <p className="text-fg-muted">
          {fr('Connecter une forge pour lister ses dépôts, les analyser sans les cloner, et y ouvrir des PR (des MR sur GitLab).')}
        </p>
        <p className="flex items-start gap-2 text-sm text-fg-muted">
          <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {fr(
            "Le token reste dans le trousseau de cet ordinateur : il ne va jamais au navigateur, et forceupdate ne l'affiche jamais.",
          )}
        </p>
      </PageHead>

      {accounts.isPending && <CardsSkeleton />}

      {accounts.isError && (
        <Alert variant="danger" role="alert">
          <CircleX aria-hidden="true" />
          <AlertTitle>Comptes indisponibles</AlertTitle>
          <AlertDescription>
            <p>{errorText(accounts.error)}</p>
          </AlertDescription>
          <AlertActions>
            <Button size="sm" onClick={() => void accounts.refetch()}>
              Réessayer
            </Button>
          </AlertActions>
        </Alert>
      )}

      {accounts.data && (
        <>
          {accounts.data.keyring && (
            <Alert variant="danger" role="alert" className="mb-6">
              <CircleX aria-hidden="true" />
              <AlertTitle>Trousseau indisponible</AlertTitle>
              <AlertDescription>
                <p>{accounts.data.keyring}</p>
              </AlertDescription>
            </Alert>
          )}
          <div className="flex flex-col gap-4">
            {available.map((forge) => (
              <ForgeCard
                key={forge.forge}
                status={forge}
                keyring={accounts.data.keyring}
                returned={returned}
                onForgetReturn={forgetReturn}
              />
            ))}
          </div>
          {soon.length > 0 && (
            <Section aria-labelledby="bientot-titre">
              <h2 id="bientot-titre" className="text-lg">
                Bientôt
              </h2>
              <div className="grid gap-4 sm:grid-cols-2">
                {soon.map((forge) => (
                  <SoonCard key={forge.forge} status={forge} />
                ))}
              </div>
            </Section>
          )}
        </>
      )}
    </Container>
  )
}

/** Une forge dont la connexion n'est pas prête (aucune depuis E20 : le serveur peut encore le dire). */
function SoonCard({ status }: { status: ForgeStatus }) {
  const id = `${status.forge}-titre`
  return (
    <section aria-labelledby={id} className="flex flex-col gap-2 rounded-md border border-border bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={id} className="flex items-center gap-2 text-base">
          <ForgeLogo forge={status.forge} />
          {status.name}
        </h3>
        <Badge variant="neutral">
          <Clock aria-hidden="true" />
          Bientôt
        </Badge>
      </div>
      <p className="text-sm text-fg-muted">
        {fr(`La connexion à ${status.name} arrive bientôt.`)}
      </p>
    </section>
  )
}

function CardsSkeleton() {
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label="Chargement des comptes">
      <Skeleton className="h-64 w-full rounded-md" />
      <div className="grid gap-4 sm:grid-cols-2">
        <Skeleton className="h-24 w-full rounded-md" />
        <Skeleton className="h-24 w-full rounded-md" />
      </div>
    </div>
  )
}
