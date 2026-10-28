import * as React from 'react'
import { cn } from 'cn'
import { ChevronDownIcon } from 'lucide-react'
import { fieldClass } from './input'

/** Liste déroulante native (clavier et lecteurs d'écran du système), habillée par les tokens. */
function NativeSelect({ className, ...props }: React.ComponentProps<'select'>) {
  return (
    <div className={cn('relative w-fit has-[select:disabled]:opacity-45', className)} data-slot="native-select-wrapper">
      <select
        data-slot="native-select"
        className={cn(fieldClass, 'w-full appearance-none pr-9 text-sm')}
        {...props}
      />
      <ChevronDownIcon
        className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-fg-muted"
        aria-hidden="true"
      />
    </div>
  )
}

function NativeSelectOption(props: React.ComponentProps<'option'>) {
  return <option data-slot="native-select-option" {...props} />
}

export { NativeSelect, NativeSelectOption }
