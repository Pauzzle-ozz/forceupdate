import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from 'cn'

/**
 * Alerte (MASTER, « Composants ») : info, avertissement, erreur, réussite, non concluant ;
 * icône, titre, texte, actions. Une erreur dit ce qui s'est passé et quoi faire. `role` :
 * « alert » pour une erreur qui arrive, « status » sinon (à donner). En bandeau pleine
 * largeur (`banner`) pour un état global : serveur arrêté, session terminée, hors ligne.
 */
const alertVariants = cva(
  "grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md border border-l-4 bg-surface px-4 py-3 text-fg *:[svg]:row-span-2 *:[svg]:mt-0.5 *:[svg]:size-5 *:[svg]:shrink-0",
  {
    variants: {
      variant: {
        info: 'border-l-primary *:[svg]:text-link',
        warning: 'border-l-warning-edge bg-warning-bg *:[svg]:text-warning *:data-[slot=alert-title]:text-warning',
        danger: 'border-l-danger bg-danger-bg *:[svg]:text-danger *:data-[slot=alert-title]:text-danger',
        success: 'border-l-success bg-success-bg *:[svg]:text-success *:data-[slot=alert-title]:text-success',
        inconclusive:
          'border-l-inconclusive border-l-dashed bg-inconclusive-bg *:[svg]:text-inconclusive *:data-[slot=alert-title]:text-inconclusive',
      },
      banner: {
        true: 'rounded-none border-x-0 border-t-0 pl-4',
        false: '',
      },
    },
    defaultVariants: {
      variant: 'info',
      banner: false,
    },
  },
)

function Alert({
  className,
  variant,
  banner,
  ...props
}: React.ComponentProps<'div'> & VariantProps<typeof alertVariants>) {
  return <div data-slot="alert" className={cn(alertVariants({ variant, banner }), className)} {...props} />
}

function AlertTitle({ className, ...props }: React.ComponentProps<'p'>) {
  return <p data-slot="alert-title" className={cn('col-start-2 font-semibold', className)} {...props} />
}

function AlertDescription({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="alert-description"
      className={cn('col-start-2 text-sm text-fg [&>*+*]:mt-2', className)}
      {...props}
    />
  )
}

function AlertActions({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="alert-actions" className={cn('col-start-2 mt-2 flex flex-wrap gap-2', className)} {...props} />
}

export { Alert, AlertTitle, AlertDescription, AlertActions }
