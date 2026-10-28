import { ChevronRight } from 'lucide-react'
import { Fragment, useEffect, type ReactNode } from 'react'
import { Link } from 'react-router'
import { cn } from 'cn'

/** Le titre de l'onglet : « Rapport · vulnerable · forceupdate ». */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} · forceupdate` : 'forceupdate'
  }, [title])
}

/** Le cadre d'un écran : 1280 px au plus (1040 pour l'accueil et les formulaires). */
export function Container({
  narrow = false,
  className,
  children,
}: {
  narrow?: boolean
  className?: string
  children: ReactNode
}) {
  return (
    <div
      className={cn(
        'mx-auto w-full px-4 pt-6 pb-12 md:px-6 md:pt-8 xl:px-8',
        narrow ? 'max-w-260' : 'max-w-320',
        className,
      )}
    >
      {children}
    </div>
  )
}

/** Fil d'Ariane des écrans profonds : Analyser › vulnerable. Le dernier n'est pas un lien. */
export function Breadcrumb({ items }: { items: { label: ReactNode; to?: string; mono?: boolean }[] }) {
  return (
    <nav aria-label="Fil d'Ariane" className="mb-3 flex flex-wrap items-center gap-1 text-sm text-fg-muted">
      {items.map((item, index) => (
        <Fragment key={index}>
          {index > 0 && <ChevronRight className="size-3.5" aria-hidden="true" />}
          {item.to ? (
            <Link to={item.to} className={cn('text-fg-muted', item.mono && 'font-mono')}>
              {item.label}
            </Link>
          ) : (
            <span aria-current="page" className={cn(item.mono && 'font-mono')}>
              {item.label}
            </span>
          )}
        </Fragment>
      ))}
    </nav>
  )
}

/** En-tête d'écran : le titre (un seul h1), la description, les actions à droite. */
export function PageHead({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-2">{children}</div>
      {actions && <div className="flex flex-wrap gap-2 max-sm:w-full max-sm:*:w-full">{actions}</div>}
    </div>
  )
}

/** Une section d'écran, 32 px sous la précédente. */
export function Section({
  className,
  children,
  ...props
}: React.ComponentProps<'section'>) {
  return (
    <section className={cn('flex flex-col gap-4 not-first:mt-8', className)} {...props}>
      {children}
    </section>
  )
}
