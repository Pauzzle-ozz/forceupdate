import { Monitor, Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTheme, type Theme } from '@/hooks/useTheme'

const NEXT: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' }
const NAME: Record<Theme, string> = { system: 'celui du système', light: 'clair', dark: 'sombre' }
const ICON = { system: Monitor, light: Sun, dark: Moon }

/** Le choix du thème : système, clair, sombre, à tour de rôle. */
export function ThemeToggle() {
  const [theme, setTheme] = useTheme()
  const Icon = ICON[theme]
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`Thème : ${NAME[theme]}. Passer au thème ${NAME[NEXT[theme]]}`}
      title={`Thème : ${NAME[theme]}`}
      onClick={() => setTheme(NEXT[theme])}
    >
      <Icon aria-hidden="true" />
    </Button>
  )
}
