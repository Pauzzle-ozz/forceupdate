import { cn } from 'cn'

/** Squelette : un bloc gris aux dimensions du contenu attendu, qui scintille (sauf mouvement réduit). */
function Skeleton({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="skeleton" aria-hidden="true" className={cn('shimmer min-h-3.5 rounded-xs bg-surface-2', className)} {...props} />
}

export { Skeleton }
