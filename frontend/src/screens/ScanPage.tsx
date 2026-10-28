import { useQuery } from '@tanstack/react-query'
import { CircleStop, CircleX, History, RefreshCw, ServerOff } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { ApiError, api, queryKeys } from '@/api/client'
import type { ScanDetail } from '@/api/types'
import { EmptyState } from '@/components/EmptyState'
import { Alert, AlertActions, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { rescanRequest, useStartScan } from '@/hooks/useScanActions'
import { basename, fr } from '@/lib/format'
import { Breadcrumb, Container, useDocumentTitle } from '@/shell/Page'
import { ScanProgress } from './ScanProgress'
import { ReportView } from './report/ReportView'

/**
 * `/analyses/{id}` : l'analyse en cours (écran 3) tant que `status` vaut `running`, puis son
 * rapport (écran 4), ou l'état échouée, annulée, introuvable. Quand l'analyse finit sous les
 * yeux, le focus va au titre du rapport.
 */
export function ScanPage() {
  const { id = '' } = useParams()
  const scan = useQuery({
    queryKey: queryKeys.scan(id),
    queryFn: () => api.getScan(id),
    // Un rapport fini ne change plus.
    staleTime: (query) => (query.state.data && query.state.data.status !== 'running' ? Infinity : 0),
  })
  // L'analyse a fini sous les yeux : le focus ira au titre du rapport.
  const [followed, setFollowed] = useState(false)

  if (scan.isPending) return <ReportSkeleton />
  if (scan.isError) return <ScanError error={scan.error} retry={() => void scan.refetch()} />

  const data = scan.data
  if (data.status === 'running') return <ScanProgress key={data.id} scan={data} onEnd={() => setFollowed(true)} />
  if (data.status === 'done' && data.report) {
    return <ReportView key={data.id} scan={data} report={data.report} focusTitle={followed} />
  }
  return <Unfinished scan={data} />
}

function ReportSkeleton() {
  useDocumentTitle('Rapport')
  return (
    <Container>
      <div className="mb-6 flex flex-col gap-2">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-3.5 w-80 max-w-full" />
      </div>
      <div className="flex flex-col gap-4" aria-busy="true" aria-label="Chargement du rapport">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(150px,1fr))]">
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="flex flex-col gap-2 rounded-md border border-border bg-surface px-4 py-3">
              <Skeleton className="w-3/5" />
              <Skeleton className="h-7.5 w-2/5" />
            </div>
          ))}
        </div>
        <Card className="flex flex-col gap-2">
          <Skeleton className="w-[30%]" />
          <Skeleton className="h-3" />
        </Card>
        <div className="flex flex-col gap-2 rounded-md border border-border bg-surface p-4">
          <Skeleton />
          <Skeleton />
          <Skeleton />
          <Skeleton className="w-[70%]" />
        </div>
      </div>
    </Container>
  )
}

function ScanError({ error, retry }: { error: Error; retry: () => void }) {
  useDocumentTitle('Rapport')
  if (error instanceof ApiError && error.status === 404) {
    return (
      <Container narrow>
        <EmptyState
          icon={History}
          level="h1"
          title="Cette analyse n'existe plus"
          actions={
            <Link to="/" className={buttonVariants({ variant: 'primary' })}>
              Retour à l'accueil
            </Link>
          }
        >
          <p>
            {fr(
              "Le serveur ne garde les analyses que le temps de sa session (les 20 plus récentes). Il a peut-être redémarré. Les chemins récents, eux, sont gardés : relancer depuis l'accueil.",
            )}
          </p>
        </EmptyState>
      </Container>
    )
  }
  return (
    <Container narrow>
      <EmptyState
        icon={ServerOff}
        level="h1"
        title="Rapport indisponible"
        actions={
          <Button onClick={retry}>
            <RefreshCw aria-hidden="true" />
            Réessayer
          </Button>
        }
      >
        <p>{error.message}</p>
      </EmptyState>
    </Container>
  )
}

/** Une analyse échouée ou annulée : ce qui s'est passé, et la relancer. */
function Unfinished({ scan }: { scan: ScanDetail }) {
  const upload = scan.kind === 'upload'
  const name = upload ? scan.source : basename(scan.source)
  useDocumentTitle(`Analyse de ${name}`)
  const start = useStartScan()
  const relaunch = upload ? (
    <Link to="/choisir?mode=fichier" className={buttonVariants({ variant: 'primary', size: 'sm' })}>
      Redéposer le fichier
    </Link>
  ) : (
    <Button variant="primary" size="sm" onClick={() => start.mutate(rescanRequest(scan))} disabled={start.isPending}>
      <RefreshCw aria-hidden="true" />
      Relancer l'analyse
    </Button>
  )

  return (
    <Container narrow>
      <Breadcrumb items={[{ label: 'Analyser', to: '/' }, { label: name, mono: true }]} />
      {scan.status === 'cancelled' ? (
        <EmptyState icon={CircleStop} level="h1" title="Analyse annulée" actions={relaunch}>
          <p>{fr(`Analyse de ${name} arrêtée avant la fin. Aucun rapport partiel n'est gardé.`)}</p>
        </EmptyState>
      ) : (
        <>
          <h1 className="mb-4 text-2xl">
            Analyse de <span className="font-mono">{name}</span>
          </h1>
          <Alert variant="danger" role="alert">
            <CircleX aria-hidden="true" />
            <AlertTitle>L'analyse a échoué</AlertTitle>
            <AlertDescription>
              <p>{scan.error ?? "Le serveur n'a pas donné de raison."}</p>
              <p className="text-fg-muted">
                {upload
                  ? 'Vérifier le fichier, puis le déposer de nouveau.'
                  : "Vérifier que le dossier existe et qu'il est lisible, puis relancer."}
              </p>
            </AlertDescription>
            <AlertActions>
              {relaunch}
              <Link to="/choisir?mode=dossier" className={buttonVariants({ variant: 'secondary', size: 'sm' })}>
                Choisir un autre dossier
              </Link>
            </AlertActions>
          </Alert>
        </>
      )}
      {start.error && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {start.error.message}
        </p>
      )}
    </Container>
  )
}
