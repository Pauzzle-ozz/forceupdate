import { Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { fr } from '@/lib/format'

/** Les limites de `POST /api/files`, à dire avant qu'on dépose. */
export const UPLOAD_LIMITS = fr(
  'Un manifeste ou un lockfile, 2 Mo au plus (50 Mo pour un lockfile). Le fichier d\'origine n\'est jamais modifié : sa version mise à jour se télécharge.',
)

function carriesFiles(event: DragEvent): boolean {
  return event.dataTransfer?.types.includes('Files') ?? false
}

/**
 * Déposer un fichier n'importe où sur la page : un voile dit quoi déposer et les limites
 * pendant le glisser ; au dépôt, `onFile` reçoit le fichier (le premier, s'il y en a
 * plusieurs). Toujours doublé d'un bouton « Choisir un fichier » (clavier).
 */
export function FileDrop({ onFile }: { onFile: (file: File) => void }) {
  const [dragging, setDragging] = useState(false)
  const depth = useRef(0)
  const latest = useRef(onFile)

  useEffect(() => {
    latest.current = onFile
  }, [onFile])

  useEffect(() => {
    const enter = (event: DragEvent) => {
      if (!carriesFiles(event)) return
      event.preventDefault()
      depth.current += 1
      setDragging(true)
    }
    const over = (event: DragEvent) => {
      if (!carriesFiles(event)) return
      event.preventDefault()
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
    }
    const leave = (event: DragEvent) => {
      if (!carriesFiles(event)) return
      depth.current = Math.max(0, depth.current - 1)
      if (depth.current === 0) setDragging(false)
    }
    const drop = (event: DragEvent) => {
      if (!carriesFiles(event)) return
      event.preventDefault()
      depth.current = 0
      setDragging(false)
      const file = event.dataTransfer?.files[0]
      if (file) latest.current(file)
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragover', over)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
    }
  }, [])

  if (!dragging) return null
  return (
    <div className="fixed inset-0 z-100 grid place-items-center bg-scrim p-6" data-testid="drop-overlay">
      <div className="flex min-h-65 w-full max-w-140 flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed border-primary bg-surface p-5 text-center text-fg">
        <Upload className="size-10" strokeWidth={1.5} aria-hidden="true" />
        <p className="font-semibold">Déposer pour analyser ce fichier</p>
        <p className="text-sm text-fg-muted">{UPLOAD_LIMITS}</p>
      </div>
    </div>
  )
}
