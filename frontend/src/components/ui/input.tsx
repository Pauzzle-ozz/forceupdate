import * as React from 'react'
import { cn } from 'cn'

/** Champ : bord `--border-control` (≥ 3:1), 40 px, halo de focus. */
export const fieldClass =
  'min-h-(--control-h) w-full rounded-sm border border-control bg-surface px-3 text-fg transition-[border-color,box-shadow] duration-150 focus-visible:border-ring focus-visible:shadow-[0_0_0_3px_color-mix(in_srgb,var(--ring)_30%,transparent)] focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-45'

function Input({ className, type, mono, ...props }: React.ComponentProps<'input'> & { mono?: boolean }) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(fieldClass, mono && 'font-mono text-sm', className)}
      {...props}
    />
  )
}

export { Input }
