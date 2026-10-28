import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from 'cn'
import { Slot } from 'radix-ui'

/**
 * Bouton (MASTER, « Composants ») : principal (plein, un par écran), secondaire (contour),
 * discret (sans fond), risqué (contour rouge, toujours confirmé). 40 px de haut, 44 au doigt.
 */
const variants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-sm border border-transparent text-sm leading-none font-medium whitespace-nowrap no-underline transition-colors duration-150 touch-manipulation disabled:cursor-not-allowed disabled:opacity-45 aria-disabled:cursor-not-allowed aria-disabled:opacity-45 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        primary: 'bg-primary text-on-primary hover:bg-primary-hover',
        secondary: 'border-control bg-surface text-fg hover:bg-surface-hover',
        ghost: 'bg-transparent text-fg hover:bg-surface-hover',
        danger: 'border-danger bg-surface text-danger hover:bg-danger-bg',
      },
      size: {
        default: 'min-h-(--control-h) px-4',
        sm: 'min-h-8 px-3 pointer-coarse:min-h-11',
        icon: "size-(--control-h) p-0 [&_svg:not([class*='size-'])]:size-5",
      },
    },
    defaultVariants: {
      variant: 'secondary',
      size: 'default',
    },
  },
)

/** Les classes d'un bouton, fusionnées (un lien habillé en bouton s'en sert aussi). */
function buttonVariants({ className, ...props }: VariantProps<typeof variants> & { className?: string } = {}) {
  return cn(variants(props), className)
}

function Button({
  className,
  variant,
  size,
  asChild = false,
  type,
  ...props
}: React.ComponentProps<'button'> &
  VariantProps<typeof variants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : 'button'

  return (
    <Comp
      data-slot="button"
      className={buttonVariants({ variant, size, className })}
      type={asChild ? type : (type ?? 'button')}
      {...props}
    />
  )
}

export { Button, buttonVariants }
