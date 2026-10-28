import * as React from 'react'
import { cn } from 'cn'

/**
 * Tableau dense (MASTER, pages/rapport.md) : texte à 14 px, cellules alignées en haut, en-tête
 * en majuscules 12 px sur `--surface-2`, collant sous l'en-tête de l'application. Le cadre
 * coupe ce qui déborde sans devenir un conteneur de défilement (l'en-tête reste collant).
 */
function Table({ className, ...props }: React.ComponentProps<'table'>) {
  return (
    <div data-slot="table-container" className="overflow-clip rounded-md border border-border bg-surface">
      <table data-slot="table" className={cn('w-full border-collapse text-sm', className)} {...props} />
    </div>
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<'thead'>) {
  return <thead data-slot="table-header" className={className} {...props} />
}

function TableBody({ className, ...props }: React.ComponentProps<'tbody'>) {
  return <tbody data-slot="table-body" className={cn('[&_tr:last-child>td]:border-b-0', className)} {...props} />
}

function TableRow({ className, ...props }: React.ComponentProps<'tr'>) {
  return (
    <tr
      data-slot="table-row"
      className={cn('transition-colors duration-150 [tbody_&]:hover:bg-surface-hover', className)}
      {...props}
    />
  )
}

function TableHead({ className, ...props }: React.ComponentProps<'th'>) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        'sticky top-(--header-h) z-1 border-b border-border bg-surface-2 px-2 py-2 lg:px-3 text-left align-top text-xs font-semibold tracking-[0.04em] text-fg-muted uppercase',
        className,
      )}
      {...props}
    />
  )
}

function TableCell({ className, ...props }: React.ComponentProps<'td'>) {
  return (
    <td
      data-slot="table-cell"
      className={cn('border-b border-border px-2 py-2 text-left align-top lg:px-3', className)}
      {...props}
    />
  )
}

function TableCaption({ className, ...props }: React.ComponentProps<'caption'>) {
  return <caption data-slot="table-caption" className={cn('px-4 py-3 text-left', className)} {...props} />
}

export { Table, TableHeader, TableBody, TableHead, TableRow, TableCell, TableCaption }
