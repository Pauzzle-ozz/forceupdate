import { LoaderCircle } from 'lucide-react'
import { cn } from 'cn'
import type { ScanSummary } from '@/api/types'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { basename } from '@/lib/format'
import { Breadcrumb, Container, useDocumentTitle } from '@/shell/Page'

const STEPS = ['Choisir', 'Vérifier', 'Appliquer', 'Résultat']
/** Les étapes d'une PR : choisir (facultatif), le récapitulatif, l'envoi, le résultat. */
export const REQUEST_STEPS = ['Choisir', 'Récapitulatif', 'Envoi', 'Résultat']

/** Le nom de ce qui est mis à jour : le dossier, le nom du fichier envoyé, ou `owner/nom`. */
export function sourceName(scan: ScanSummary): string {
  return scan.kind === 'upload' || scan.repository ? scan.source : basename(scan.source)
}

/**
 * Le fil d'étapes (MASTER, « Fil d'étapes ») : Choisir → Vérifier → Appliquer → Résultat, deux
 * étapes seulement pour un fichier envoyé ; l'étape en cours en `aria-current="step"`. Sous
 * 640 px, sans traits entre les étapes.
 */
export function Stepper({ current, upload = false, steps: given }: { current: number; upload?: boolean; steps?: string[] }) {
  const steps = given ?? (upload ? STEPS.slice(0, 2) : STEPS)
  return (
    <ol aria-label="Étapes" className="flex flex-wrap gap-x-4 gap-y-2 sm:gap-x-2">
      {steps.map((label, index) => {
        const done = index < current
        const now = index === current
        return (
          <li
            key={label}
            aria-current={now ? 'step' : undefined}
            className={cn(
              'flex items-center gap-2 text-sm font-medium text-fg-muted',
              'sm:not-first:before:mr-1 sm:not-first:before:block sm:not-first:before:h-px sm:not-first:before:w-6 sm:not-first:before:bg-control',
              now && 'font-semibold text-fg',
            )}
          >
            <span
              className={cn(
                'grid size-6 place-content-center rounded-full border-[1.5px] border-control text-xs tabular-nums',
                now && 'border-primary bg-primary text-on-primary',
                done && 'border-success bg-success-bg text-success',
              )}
              aria-hidden="true"
            >
              {index + 1}
            </span>
            {label}
            {done && <span className="sr-only"> (fait)</span>}
          </li>
        )
      })}
    </ol>
  )
}

/**
 * L'en-tête de l'écran 5 : fil d'Ariane, titre, étapes. Un dépôt d'une forge se met à jour par
 * une PR : ses étapes sont celles de l'écran 8.
 */
export function UpdateHeader({ scan, step }: { scan: ScanSummary; step: number }) {
  const name = sourceName(scan)
  const repository = scan.repository
  useDocumentTitle(`${repository ? 'PR' : 'Mise à jour'} · ${name}`)
  return (
    <>
      <Breadcrumb
        items={[
          repository ? { label: 'Mes dépôts', to: '/depots' } : { label: 'Analyser', to: '/' },
          { label: name, to: `/analyses/${scan.id}`, mono: true },
          { label: repository ? 'PR' : 'Mise à jour' },
        ]}
      />
      <div className="mb-6 flex flex-col gap-2">
        <h1 className="text-2xl [overflow-wrap:anywhere]">
          {repository ? 'Préparer la PR de ' : 'Mettre à jour '}
          <span className="font-mono">{name}</span>
        </h1>
        <Stepper current={step} upload={scan.kind === 'upload'} steps={repository ? REQUEST_STEPS : undefined} />
      </div>
    </>
  )
}

/** Le chargement de l'écran, avant de savoir de quelle analyse il s'agit. */
export function UpdateSkeleton() {
  useDocumentTitle('Mise à jour')
  return (
    <Container>
      <div className="mb-6 flex flex-col gap-2">
        <Skeleton className="h-3.5 w-48" />
        <Skeleton className="h-7 w-64 max-w-full" />
        <Skeleton className="h-6 w-80 max-w-full" />
      </div>
      <div className="flex flex-col gap-3" aria-busy="true" aria-label="Chargement de la mise à jour">
        {[0, 1, 2].map((index) => (
          <Card key={index} className="flex flex-col gap-3">
            <Skeleton className="w-2/5" />
            <Skeleton />
            <Skeleton className="w-3/5" />
          </Card>
        ))}
      </div>
    </Container>
  )
}

/**
 * « Préparation du plan… » : le serveur réécrit à blanc et relit ; squelettes des diffs. Le
 * récapitulatif des PR (`label`) se prépare de même, et cherche les PR déjà ouvertes.
 */
export function PreparingPlan({
  label = 'Préparation du plan',
  text = 'Préparation du plan : réécriture à blanc, vérification par les parseurs…',
}: { label?: string; text?: string } = {}) {
  return (
    <div className="flex max-w-215 flex-col gap-4" aria-busy="true" aria-label={label}>
      <p className="flex items-center gap-2 text-fg-muted" role="status">
        <LoaderCircle className="size-5 animate-spin" aria-hidden="true" />
        {text}
      </p>
      {[0, 1].map((index) => (
        <div key={index} className="overflow-hidden rounded-md border border-border bg-surface">
          <div className="border-b border-border bg-surface-2 px-4 py-2">
            <Skeleton className="w-36" />
          </div>
          <div className="flex flex-col gap-2 px-4 py-3">
            <Skeleton />
            <Skeleton className="w-4/5" />
            <Skeleton className="w-3/5" />
          </div>
        </div>
      ))}
    </div>
  )
}
