import { CircleCheck, CircleDashed, LoaderCircle, Terminal, type LucideIcon } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { cn } from 'cn'
import { Blade } from '@/components/Blade'
import { Card } from '@/components/ui/card'
import { usePlanEvents, type ApplyProgress } from '@/hooks/usePlanEvents'
import { fr } from '@/lib/format'
import { Container } from '@/shell/Page'
import { UpdateHeader } from './Layout'
import type { StepProps } from './PlanPage'

type State = 'done' | 'running' | 'pending'

const STATE_ICON: Record<State, LucideIcon> = { done: CircleCheck, running: LoaderCircle, pending: CircleDashed }
const STATE_WORD: Record<State, string> = { done: ' (fait)', running: ' (en cours)', pending: ' (à venir)' }

interface Task {
  key: string
  state: State
  label: React.ReactNode
  aside?: string
}

/** Ce qui est annoncé aux lecteurs d'écran : l'étape en cours, pas chaque nombre. */
function announcement(progress: ApplyProgress, tools: Map<string, string>): string {
  if (progress.finished) return 'Application terminée.'
  if (progress.running) return `Régénération de ${progress.running} par ${tools.get(progress.running) ?? "l'outil"}.`
  if (progress.written !== null) return 'Manifestes réécrits.'
  return 'Réécriture des manifestes.'
}

/**
 * Étape Appliquer (ECRANS.md, écran 5) : les manifestes réécrits (`written`), puis un lockfile
 * après l'autre (`regenerating`), la lame. Pas d'annulation : la page le dit (si un outil
 * échoue, ses fichiers sont remis) ; la mise à jour continue si la page se ferme.
 */
export function ApplyStep({ scan, plan, live }: StepProps) {
  const progress = usePlanEvents(plan.id)
  const title = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (live) title.current?.focus()
  }, [live])

  const runnable = plan.lockfiles.filter((job) => job.available)
  const missing = plan.lockfiles.filter((job) => !job.available)
  const tools = new Map(runnable.map((job) => [job.lockfile, job.tool]))
  const total = progress.total || runnable.length
  const determinate = progress.written !== null && total > 0

  const tasks: Task[] = []
  if (plan.files.length > 0) {
    const files = plan.files.map((file) => file.path).join(', ')
    tasks.push({
      key: 'written',
      state: progress.written !== null ? 'done' : 'running',
      label: (
        <>
          {progress.written !== null ? 'Manifestes réécrits' : 'Réécriture des manifestes'}
          {fr(' : ')}
          <span className="font-mono [overflow-wrap:anywhere]">{files}</span>
        </>
      ),
    })
  }
  runnable.forEach((job, index) => {
    const state: State =
      progress.finished || index < progress.done ? 'done' : progress.running === job.lockfile ? 'running' : 'pending'
    tasks.push({
      key: job.lockfile,
      state,
      label: (
        <>
          <span className="font-mono">{job.lockfile}</span>
          {state === 'done' ? ` régénéré par ${job.tool}` : fr(` : ${job.tool}${state === 'running' ? '…' : ''}`)}
        </>
      ),
      aside: state === 'running' ? `${index + 1} sur ${runnable.length}` : undefined,
    })
  })

  return (
    <Container>
      <UpdateHeader scan={scan} step={2} />
      <Card className="flex max-w-190 flex-col gap-5">
        <h2 ref={title} tabIndex={-1} className="text-lg">
          Application en cours
        </h2>
        <Blade
          large
          label="Lockfiles régénérés"
          value={determinate ? progress.done : undefined}
          max={determinate ? total : undefined}
          valueText={determinate ? `${progress.done} ${progress.done >= 2 ? 'lockfiles' : 'lockfile'} sur ${total}` : 'en cours'}
        />
        <ol className="flex flex-col gap-3">
          {tasks.map((task) => {
            const Icon = STATE_ICON[task.state]
            return (
              <li
                key={task.key}
                className={cn('grid grid-cols-[24px_1fr_auto] items-start gap-3', task.state === 'pending' && 'text-fg-muted')}
              >
                <Icon
                  className={cn(
                    'mt-0.5 size-5',
                    task.state === 'done' && 'text-success',
                    task.state === 'running' && 'animate-spin text-link',
                  )}
                  aria-hidden="true"
                />
                <span className="min-w-0">
                  {task.label}
                  <span className="sr-only">{STATE_WORD[task.state]}</span>
                </span>
                {task.aside && <span className="text-sm text-fg-muted tabular-nums">{task.aside}</span>}
              </li>
            )
          })}
          {missing.map((job) => (
            <li key={job.lockfile} className="grid grid-cols-[24px_1fr_auto] items-start gap-3 text-fg-muted">
              <Terminal className="mt-0.5 size-5" aria-hidden="true" />
              <span className="min-w-0">
                <span className="font-mono">{job.lockfile}</span>
                {fr(` : ${job.program} absent, commande à lancer ensuite`)}
              </span>
            </li>
          ))}
        </ol>
        <div className="sr-only" aria-live="polite">
          {announcement(progress, tools)}
        </div>
        <p className="text-sm text-fg-muted">
          {fr(
            "La mise à jour continue même si la page est fermée, et ne s'interrompt pas. Un outil peut prendre quelques minutes (10 au plus par commande).",
          )}
        </p>
      </Card>
    </Container>
  )
}
