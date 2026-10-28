import { FolderGit2, KeyRound, Menu, Search, Settings, WifiOff, X, type LucideIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router'
import { cn } from 'cn'
import { Button } from '@/components/ui/button'
import { useOnline } from '@/hooks/useStatus'
import { Banners } from './Banners'
import { ThemeToggle } from './ThemeToggle'

const NAV: { to: string; label: string; icon: LucideIcon; matches: (path: string) => boolean }[] = [
  {
    to: '/',
    label: 'Analyser',
    icon: Search,
    matches: (path) => path === '/' || path.startsWith('/choisir') || path.startsWith('/analyses') || path.startsWith('/plans'),
  },
  { to: '/depots', label: 'Dépôts', icon: FolderGit2, matches: (path) => path.startsWith('/depots') || path.startsWith('/pr') },
  { to: '/comptes', label: 'Comptes', icon: KeyRound, matches: (path) => path.startsWith('/comptes') },
  { to: '/reglages', label: 'Réglages', icon: Settings, matches: (path) => path.startsWith('/reglages') },
]

/**
 * La coquille (MASTER, « Points de rupture et mise en page ») : le lien d'évitement, l'en-tête
 * collant de 56 px (la marque, la navigation principale, l'état du réseau hors ligne, le
 * thème), les bandeaux communs, l'écran, le pied de page avec la devise. Sous 900 px, la
 * navigation passe dans un menu. Après un changement d'écran, le focus va au contenu.
 */
export function AppShell() {
  const location = useLocation()
  const online = useOnline()
  const [menuOpen, setMenuOpen] = useState(false)
  const main = useRef<HTMLElement>(null)
  const firstPath = useRef(location.pathname)

  useEffect(() => {
    if (location.pathname === firstPath.current) return
    firstPath.current = location.pathname
    main.current?.focus({ preventScroll: true })
    window.scrollTo({ top: 0 })
  }, [location.pathname])

  useEffect(() => {
    if (!menuOpen) return
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [menuOpen])

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#contenu"
        className="absolute -top-25 left-4 z-1000 rounded-sm border-2 border-ring bg-surface px-4 py-2 text-fg focus:top-2"
      >
        Aller au contenu
      </a>

      <header className="sticky top-0 z-10 flex h-(--header-h) items-center gap-4 border-b border-border bg-surface px-4 md:px-6">
        <Button
          variant="ghost"
          size="icon"
          className="nav:hidden"
          aria-expanded={menuOpen}
          aria-controls="nav"
          aria-label="Menu"
          onClick={() => setMenuOpen((open) => !open)}
        >
          {menuOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
        </Button>
        <Link
          to="/"
          aria-label="forceupdate, accueil"
          className="inline-flex items-center gap-2 font-mono text-lg font-semibold whitespace-nowrap text-fg no-underline"
        >
          <span className="h-5 w-1 rounded-full bg-blade shadow-[var(--blade-glow)]" aria-hidden="true" />
          <span>
            <b className="font-semibold text-primary">force</b>update
          </span>
        </Link>
        <nav
          id="nav"
          aria-label="Navigation principale"
          className={cn(
            'items-center gap-1 nav:flex',
            menuOpen
              ? 'fixed inset-x-0 top-(--header-h) z-50 flex flex-col items-stretch border-b border-border bg-surface px-4 pt-2 pb-4 shadow-raised'
              : 'hidden',
          )}
        >
          {NAV.map(({ to, label, icon: Icon, matches }) => {
            const current = matches(location.pathname)
            return (
              <Link
                key={to}
                to={to}
                onClick={() => setMenuOpen(false)}
                aria-current={current ? (location.pathname === to ? 'page' : 'true') : undefined}
                className={cn(
                  'inline-flex min-h-(--control-h) items-center gap-2 rounded-sm px-3 font-medium no-underline transition-colors duration-150 max-nav:min-h-11',
                  current
                    ? 'bg-surface-2 text-fg shadow-[inset_0_-2px_0_var(--primary)]'
                    : 'text-fg-muted hover:bg-surface-hover hover:text-fg',
                )}
              >
                <Icon className="size-5" aria-hidden="true" />
                {label}
              </Link>
            )
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {!online && (
            <span className="inline-flex items-center gap-2 text-sm whitespace-nowrap text-warning" role="status">
              <WifiOff className="size-4" aria-hidden="true" />
              Hors ligne
            </span>
          )}
          <ThemeToggle />
        </div>
      </header>

      <Banners />

      <main id="contenu" ref={main} tabIndex={-1} className="flex-1">
        <Outlet />
      </main>

      <footer className="flex flex-wrap justify-between gap-2 border-t border-border p-4 text-sm text-fg-muted">
        <span>
          forceupdate {__FORCEUPDATE_VERSION__} · serveur local{' '}
          <span className="font-mono">{window.location.host}</span>
        </span>
        <span>Que la Force soit avec tes dépendances.</span>
      </footer>
    </div>
  )
}
