import * as React from 'react'
import { cn } from 'cn'

/**
 * Panneau latéral (MASTER, « Panneau latéral ») : à droite, 600 px (plein écran sous 640),
 * voile derrière ; le titre (`data-autofocus`) reçoit le focus à l'ouverture, Échap ferme, le
 * focus revient à ce qui l'a ouvert.
 *
 * Un `<dialog>` natif ouvert par `showModal()`, pas le Sheet de shadcn/ui : celui-ci (Radix
 * Dialog, par react-remove-scroll) injecte un `<style>` que refuse la CSP du serveur
 * (`default-src 'self'`). Le dialogue natif a tout ce qu'il faut : le reste de la page devient
 * inerte, Échap le ferme, le voile est son `::backdrop` (app.css).
 */
function Sheet({
  open,
  onClose,
  className,
  children,
  ...props
}: Omit<React.ComponentProps<'dialog'>, 'open'> & { open: boolean; onClose: () => void }) {
  const ref = React.useRef<HTMLDialogElement>(null)
  const opener = React.useRef<HTMLElement | null>(null)

  React.useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
      dialog.showModal()
      dialog.querySelector<HTMLElement>('[data-autofocus]')?.focus()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open])

  React.useEffect(() => {
    const dialog = ref.current
    return () => {
      if (dialog?.open) dialog.close()
    }
  }, [])

  return (
    // Le clic sur le voile complète Échap (géré par le dialogue natif) : pas besoin d'une touche en plus.
    // oxlint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions
    <dialog
      ref={ref}
      className={cn('sheet', className)}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClose={() => {
        opener.current?.focus()
        opener.current = null
      }}
      onClick={(event) => {
        // Un clic sur le voile (hors du contenu) ferme le panneau.
        if (event.target === ref.current) onClose()
      }}
      {...props}
    >
      {children}
    </dialog>
  )
}

function SheetHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div className={cn('flex items-start gap-3 border-b border-border px-5 py-4', className)} {...props} />
  )
}

function SheetBody({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-1 flex-col gap-6 overflow-y-auto p-5', className)} {...props} />
}

function SheetFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      className={cn('flex flex-wrap justify-end gap-2 border-t border-border px-5 py-3', className)}
      {...props}
    />
  )
}

export { Sheet, SheetHeader, SheetBody, SheetFooter }
