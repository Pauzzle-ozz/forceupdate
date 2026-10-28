import { cn } from 'cn'

/**
 * La lame (MASTER, « Le clin d'œil ») : la barre de progression, fine et arrondie, qui luit en
 * thème sombre. Déterminée (`value` sur `max`) ou indéterminée (un reflet qui glisse ; une
 * barre rayée immobile avec « réduire les animations »).
 */
export function Blade({
  label,
  value,
  max,
  valueText,
  large = false,
  className,
}: {
  label: string
  value?: number
  max?: number
  valueText?: string
  large?: boolean
  className?: string
}) {
  const determinate = max !== undefined && max > 0 && value !== undefined
  const percent = determinate ? Math.min(100, Math.max(0, (value / max) * 100)) : 0
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={determinate ? 0 : undefined}
      aria-valuemax={determinate ? max : undefined}
      aria-valuenow={determinate ? value : undefined}
      aria-valuetext={valueText}
      className={cn('relative overflow-hidden rounded-full bg-track', large ? 'h-2' : 'h-1.5', className)}
    >
      <span
        className={cn('lame-fill', !determinate && 'lame-sweep')}
        style={determinate ? { width: `${percent}%` } : undefined}
      />
    </div>
  )
}
