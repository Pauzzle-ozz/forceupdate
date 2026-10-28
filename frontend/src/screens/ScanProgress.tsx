import { useMutation } from '@tanstack/react-query'
import { CircleCheck, CircleDashed, LoaderCircle, WifiOff, type LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { cn } from 'cn'
import { api } from '@/api/client'
import type { ScanDetail } from '@/api/types'
import { Blade } from '@/components/Blade'
import { OptionBadges } from '@/components/OptionBadges'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useScanEvents, type ScanProgress as Progress } from '@/hooks/useScanEvents'
import { basename, count, formatDuration, fr } from '@/lib/format'
import { Breadcrumb, Container, useDocumentTitle } from '@/shell/Page'

/** Le nom du paquet n'est annoncé aux lecteurs d'écran qu'au plus toutes les 5 s. */
const ANNOUNCE_EVERY = 5000

type State = 'done' | 'running' | 'pending'

interface Step {
  key: string
  label: string
  state: State
  detail?: React.ReactNode
}

function steps(progress: Progress): Step[] {
  const { seen } = progress
  const finished = seen.has('finished')
  const checking = seen.has('checking')
  const projects = progress.projects
  return [
    {
      key: 'reading',
      label: 'Lecture des fichiers',
      state: seen.has('projects_found') || finished ? 'done' : 'running',
    },
    {
      key: 'projects',
      label: projects === null ? 'Recherche des projets' : `${count(projects, 'projet')} ${projects >= 2 ? 'trouvés' : 'trouvé'}`,
      state: projects !== null ? 'done' : 'pending',
    },
    {
      key: 'checking',
      label: checking
        ? fr(`Vérification des paquets et des failles : ${progress.done} sur ${progress.total}`)
        : 'Vérification des paquets et des failles',
      state: finished ? 'done' : checking ? 'running' : 'pending',
      detail: progress.last && !finished && (
        <span className="font-mono text-sm text-fg-muted">
          {progress.last.ecosystem} {progress.last.name}
        </span>
      ),
    },
    {
      key: 'vulnerabilities',
      label: 'Recherche des failles (OSV)',
      state: seen.has('vulnerabilities_checked') || finished ? 'done' : checking ? 'running' : 'pending',
    },
  ]
}

const STEP_ICON: Record<State, LucideIcon> = { done: CircleCheck, running: LoaderCircle, pending: CircleDashed }

/** L'étape à annoncer : la dernière commencée (sans les nombres, qui changent sans cesse). */
function announcement(progress: Progress): string {
  const { seen } = progress
  if (seen.has('finished')) return 'Analyse terminée.'
  if (seen.has('vulnerabilities_checked')) return 'Failles cherchées. Vérification des paquets en cours.'
  if (seen.has('checking')) return 'Vérification des paquets et recherche des failles en cours.'
  if (progress.projects !== null) return `${count(progress.projects, 'projet')} ${progress.projects >= 2 ? 'trouvés' : 'trouvé'}.`
  return 'Lecture des fichiers.'
}

/**
 * Écran 3 : voir avancer l'analyse, pouvoir l'annuler (ECRANS.md, pages/analyse-en-cours.md).
 * Une colonne de 640 px au plus ; la lame en grand, indéterminée tant que le total n'est pas
 * connu.
 */
export function ScanProgress({ scan, onEnd }: { scan: ScanDetail; onEnd?: () => void }) {
  const name = scan.kind === 'upload' ? scan.source : basename(scan.source)
  useDocumentTitle(`Analyse de ${name}`)
  const progress = useScanEvents(scan.id, onEnd)
  const cancel = useMutation({ mutationFn: () => api.cancelScan(scan.id) })
  const elapsed = useElapsed(scan.started_at)
  const announcedPackage = useThrottled(progress.last ? `${progress.last.ecosystem} ${progress.last.name}` : '', ANNOUNCE_EVERY)

  const list = steps(progress)
  const searching = list[3].state === 'running'
  const determinate = progress.seen.has('checking') && progress.total > 0

  return (
    <>
      {scan.options.offline && (
        <Alert variant="warning" banner role="status">
          <WifiOff aria-hidden="true" />
          <AlertTitle>{fr('Analyse hors ligne : cache seulement')}</AlertTitle>
          <AlertDescription>
            <p>{fr('Les paquets absents du cache sortiront « non concluant ».')}</p>
          </AlertDescription>
        </Alert>
      )}
      <Container narrow className="max-w-160">
        <Breadcrumb items={[{ label: 'Analyser', to: '/' }, { label: name, mono: true }]} />
        <Card className="flex flex-col gap-5">
          <div className="flex flex-col gap-2">
            <h1 className="text-2xl">
              Analyse de <span className="font-mono">{name}</span>
            </h1>
            <p className="font-mono text-sm break-all text-fg-muted">
              {scan.kind === 'upload' ? 'fichier envoyé' : scan.source}
            </p>
            <OptionBadges options={scan.options} />
          </div>

          <Blade
            large
            label={`Analyse de ${name}`}
            value={determinate ? progress.done : undefined}
            max={determinate ? progress.total : undefined}
            valueText={determinate ? `${progress.done} sur ${progress.total} vérifications` : 'en cours'}
          />

          <ol className="flex flex-col gap-3">
            {list.map((step) => {
              const Icon = STEP_ICON[step.state]
              return (
                <li key={step.key} className={cn('grid grid-cols-[24px_1fr] items-start gap-3', step.state === 'pending' && 'text-fg-muted')}>
                  <Icon
                    className={cn(
                      'mt-0.5 size-5',
                      step.state === 'done' && 'text-success',
                      step.state === 'running' && 'animate-spin text-link',
                    )}
                    aria-hidden="true"
                  />
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="tabular-nums">
                      {step.label}
                      <span className="sr-only">
                        {step.state === 'done' ? ' (fait)' : step.state === 'running' ? ' (en cours)' : ' (à venir)'}
                      </span>
                    </span>
                    {step.detail}
                    {step.key === 'vulnerabilities' && searching && (
                      // Le clin d'œil : sous la ligne fonctionnelle, jamais annoncé.
                      <span className="text-sm text-fg-muted" aria-hidden="true">
                        Recherche d'une perturbation dans la Force…
                      </span>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>

          <div className="sr-only" aria-live="polite">
            {announcement(progress)}
          </div>
          <div className="sr-only" aria-live="polite">
            {announcedPackage && `Paquet vérifié : ${announcedPackage}`}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
            <p className="text-sm text-fg-muted tabular-nums">
              {fr(`Temps écoulé : ${formatDuration(elapsed)}`)}
            </p>
            <Button onClick={() => cancel.mutate()} disabled={cancel.isPending || cancel.isSuccess}>
              {cancel.isPending || cancel.isSuccess ? (
                <>
                  <LoaderCircle className="animate-spin" aria-hidden="true" />
                  Annulation…
                </>
              ) : (
                'Annuler'
              )}
            </Button>
          </div>
          {elapsed > 10_000 && !scan.options.offline && (
            <p className="text-sm text-fg-muted">
              {fr('Les analyses suivantes iront plus vite : les réponses des registres restent en cache une heure.')}
            </p>
          )}
          {cancel.error && (
            <p role="alert" className="text-sm text-danger">
              {cancel.error.message}
            </p>
          )}
        </Card>
      </Container>
    </>
  )
}

/** Le temps écoulé depuis `start`, en millisecondes, mis à jour chaque seconde. */
function useElapsed(start: string): number {
  const origin = new Date(start).getTime()
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  return Math.max(0, now - origin)
}

/** `value`, mais pas plus d'un changement toutes les `every` millisecondes (le dernier gagne). */
export function useThrottled(value: string, every: number): string {
  const [shown, setShown] = useState(value)
  const last = useRef(0)
  useEffect(() => {
    const wait = last.current + every - Date.now()
    if (wait <= 0) {
      last.current = Date.now()
      setShown(value)
      return
    }
    const timer = window.setTimeout(() => {
      last.current = Date.now()
      setShown(value)
    }, wait)
    return () => window.clearTimeout(timer)
  }, [value, every])
  return shown
}
