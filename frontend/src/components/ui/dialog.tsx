import * as React from 'react'
import { cn } from 'cn'
import { Button } from './button'

/**
 * Dialogue de confirmation (MASTER, « Bouton » risqué, toujours confirmé ; pages/mise-a-jour.md,
 * « Garde-fou et confirmation ») : le focus va sur « Annuler », Échap annule, le focus revient à
 * ce qui l'a ouvert ; l'action risquée est en rouge.
 *
 * Un `<dialog>` natif ouvert par `showModal()`, comme le panneau latéral (`sheet.tsx`), pas
 * l'AlertDialog de shadcn/ui : Radix y injecte un `<style>` que refuse la CSP du serveur. Le
 * reste de la page devient inerte, le voile est son `::backdrop` (app.css). Un clic sur le voile
 * ne ferme pas : il faut choisir.
 */
function ConfirmDialog({
  open,
  title,
  children,
  confirm,
  onConfirm,
  onCancel,
  className,
}: {
  open: boolean
  title: React.ReactNode
  children: React.ReactNode
  /** Le nom de l'action, sur son bouton (« Appliquer quand même »). */
  confirm: string
  onConfirm: () => void
  onCancel: () => void
  className?: string
}) {
  const ref = React.useRef<HTMLDialogElement>(null)
  const opener = React.useRef<HTMLElement | null>(null)
  const id = React.useId()

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
    <dialog
      ref={ref}
      role="alertdialog"
      aria-labelledby={`${id}-titre`}
      aria-describedby={`${id}-texte`}
      className={cn('confirm', className)}
      onCancel={(event) => {
        event.preventDefault()
        onCancel()
      }}
      onClose={() => {
        opener.current?.focus()
        opener.current = null
      }}
    >
      {open && (
        <>
          <h2 id={`${id}-titre`} className="text-lg">
            {title}
          </h2>
          <div id={`${id}-texte`} className="text-sm [&>*+*]:mt-2">
            {children}
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <Button data-autofocus onClick={onCancel}>
              Annuler
            </Button>
            <Button variant="danger" onClick={onConfirm}>
              {confirm}
            </Button>
          </div>
        </>
      )}
    </dialog>
  )
}

export { ConfirmDialog }
