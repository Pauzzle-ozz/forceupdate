import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from 'cn'

/** État vide (MASTER) : icône de 40 px, titre, une phrase, une action. Jamais un écran blanc. */
export function EmptyState({
  icon: Icon,
  title,
  level = 'h3',
  children,
  actions,
  className,
  titleRef,
}: {
  icon: LucideIcon
  title: ReactNode
  level?: 'h1' | 'h2' | 'h3'
  children?: ReactNode
  actions?: ReactNode
  className?: string
  titleRef?: React.Ref<HTMLHeadingElement>
}) {
  const Heading = level
  return (
    <div
      className={cn(
        'flex flex-col items-center gap-3 rounded-md border border-border bg-surface px-6 py-10 text-center text-fg-muted',
        className,
      )}
    >
      <Icon className="size-10" strokeWidth={1.5} aria-hidden="true" />
      <Heading ref={titleRef} tabIndex={titleRef ? -1 : undefined} className="text-lg text-fg">
        {title}
      </Heading>
      {children && <div className="max-w-[52ch] space-y-2">{children}</div>}
      {actions && <div className="flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  )
}
