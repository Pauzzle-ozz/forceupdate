import * as React from 'react'
import { cn } from 'cn'

/**
 * Case à cocher et bouton radio (MASTER, « Groupe d'options d'une mise à jour ») : les contrôles
 * natifs (clavier, flèches d'un groupe radio, formulaires), dessinés aux tokens par app.css
 * (`input.choice`) : 18 px, bord `--border-control`, plein `--primary` une fois coché ; 44 px
 * de cible au doigt.
 */
function Checkbox({ className, ...props }: Omit<React.ComponentProps<'input'>, 'type'>) {
  return <input type="checkbox" data-slot="checkbox" className={cn('choice', className)} {...props} />
}

function Radio({ className, ...props }: Omit<React.ComponentProps<'input'>, 'type'>) {
  return <input type="radio" data-slot="radio" className={cn('choice', className)} {...props} />
}

export { Checkbox, Radio }
