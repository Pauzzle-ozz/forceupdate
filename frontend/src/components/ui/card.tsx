import * as React from 'react'
import { cn } from 'cn'

/** Carte : surface, bordure fine, rayon 8, pas d'ombre au repos (MASTER). */
function Card({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="card" className={cn('rounded-md border border-border bg-surface p-5', className)} {...props} />
}

function CardTitle({ className, ...props }: React.ComponentProps<'h3'>) {
  // oxlint-disable-next-line jsx-a11y/heading-has-content -- le texte arrive par children
  return <h3 data-slot="card-title" className={cn('flex items-center gap-2 text-base', className)} {...props} />
}

export { Card, CardTitle }
