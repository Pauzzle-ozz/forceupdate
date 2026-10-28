import { FileDiff } from 'lucide-react'
import { useMemo, useState } from 'react'
import { cn } from 'cn'
import { Button } from '@/components/ui/button'
import { count, fr } from '@/lib/format'
import { parseDiff } from '@/lib/update'

/** Au-delà, le diff est replié (pages/mise-a-jour.md). */
const FOLDED_FROM = 400

/**
 * Le diff d'un fichier (MASTER, « Diff » ; pages/mise-a-jour.md) : un cadre, le chemin et
 * `+n −n`, deux colonnes de numéros (avant, après), `+` et `−` en plus de la couleur ; défilement
 * horizontal dans le cadre, focalisable au clavier.
 */
export function Diff({ path, diff }: { path: string; diff: string }) {
  const parsed = useMemo(() => parseDiff(diff), [diff])
  const [unfolded, setUnfolded] = useState(false)
  const shown = unfolded || parsed.lines.length <= FOLDED_FROM

  return (
    <div className="overflow-hidden rounded-md border border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border bg-surface-2 px-4 py-2 text-sm">
        <FileDiff className="size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 font-mono font-semibold break-all">{path}</span>
        <span className="grow" />
        <span className="whitespace-nowrap tabular-nums" aria-hidden="true">
          <span className="text-diff-add">+{parsed.added}</span> <span className="text-diff-del">−{parsed.removed}</span>
        </span>
        <span className="sr-only">
          {count(parsed.added, 'ligne ajoutée', 'lignes ajoutées')}, {count(parsed.removed, 'retirée')}
        </span>
      </div>
      {shown ? (
        <div
          role="region"
          aria-label={`Diff de ${path}`}
          // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- défilement horizontal au clavier
          tabIndex={0}
          className="overflow-x-auto font-mono text-[13px] leading-[1.55]"
        >
          <table className="min-w-full border-collapse">
            <tbody>
              {parsed.lines.map((line, index) =>
                line.kind === 'hunk' ? (
                  <tr key={index}>
                    <td className="w-px border-r border-border bg-surface-2" aria-hidden="true" />
                    <td className="w-px border-r border-border bg-surface-2" aria-hidden="true" />
                    <td colSpan={2} className="bg-surface-2 px-3 py-0.5 whitespace-pre text-fg-muted">
                      {line.text}
                    </td>
                  </tr>
                ) : (
                  <tr
                    key={index}
                    className={cn(line.kind === 'add' && 'bg-diff-add-bg', line.kind === 'del' && 'bg-diff-del-bg')}
                  >
                    <td className="w-px border-r border-border px-2 text-right text-fg-muted tabular-nums select-none">{line.old}</td>
                    <td className="w-px border-r border-border px-2 text-right text-fg-muted tabular-nums select-none">{line.new}</td>
                    <td
                      className={cn(
                        'w-px pl-3 font-bold select-none',
                        line.kind === 'add' && 'text-diff-add',
                        line.kind === 'del' && 'text-diff-del',
                      )}
                    >
                      {line.kind === 'add' ? '+' : line.kind === 'del' ? '−' : ' '}
                    </td>
                    <td className={cn('px-3 whitespace-pre', line.kind === 'note' && 'text-fg-muted italic')}>{line.text}</td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm text-fg-muted">
          <span>{fr(`${count(parsed.lines.length, 'ligne')} : diff replié.`)}</span>
          <Button size="sm" onClick={() => setUnfolded(true)}>
            Afficher le diff
          </Button>
        </div>
      )}
    </div>
  )
}
