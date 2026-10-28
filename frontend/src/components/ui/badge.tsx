import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from 'cn'

/**
 * Badge (MASTER, « Composants ») : gravité (icône et mot ; critique plein, les autres
 * teintés), type de constat, écart, écosystème, « non concluant » (bord pointillé). Jamais
 * la couleur seule : toujours un mot, souvent une icône.
 */
const badgeVariants = cva(
  'inline-flex min-h-[22px] shrink-0 items-center gap-1 rounded-xs border border-transparent px-2 text-xs leading-tight font-medium whitespace-nowrap [&>svg]:size-3.5 [&>svg]:shrink-0',
  {
    variants: {
      variant: {
        neutral: 'bg-surface-2 text-fg-muted',
        outline: 'border-border bg-transparent text-fg-muted',
        critical: 'bg-critical text-on-critical',
        high: 'bg-high-bg text-high',
        medium: 'bg-medium-bg text-medium',
        low: 'bg-low-bg text-low',
        info: 'bg-info-bg text-info',
        success: 'bg-success-bg text-success',
        warning: 'bg-warning-bg text-warning',
        danger: 'bg-danger-bg text-danger',
        inconclusive: 'border-dashed border-current bg-inconclusive-bg text-inconclusive',
        primary: 'bg-primary-soft text-link',
      },
      mono: {
        true: 'font-mono font-medium',
        false: '',
      },
    },
    defaultVariants: {
      variant: 'neutral',
      mono: false,
    },
  },
)

function Badge({
  className,
  variant,
  mono,
  ...props
}: React.ComponentProps<'span'> & VariantProps<typeof badgeVariants>) {
  return <span data-slot="badge" className={cn(badgeVariants({ variant, mono }), className)} {...props} />
}

export { Badge, badgeVariants }
