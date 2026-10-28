import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { FolderGit2, GitPullRequest, KeyRound, ListChecks, Settings } from 'lucide-react'
import { useState } from 'react'
import { BrowserRouter, Route, Routes, useParams } from 'react-router'
import { Choose } from '@/screens/Choose'
import { Home } from '@/screens/Home'
import { ScanPage } from '@/screens/ScanPage'
import { AppShell } from '@/shell/AppShell'
import { ComingSoon, NotFound } from '@/shell/NotFound'

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      // Le serveur est local : une erreur ne se règle pas en réessayant tout seul (les
      // bandeaux de la coquille proposent « Réessayer »).
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
}

/** Les adresses du front (design-system/ECRANS.md, « Adresses »). */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Home />} />
        <Route path="choisir" element={<Choose />} />
        <Route path="analyses/:id" element={<ScanPage />} />
        <Route path="analyses/:id/mise-a-jour" element={<UpdateSoon />} />
        <Route path="plans/:id" element={<UpdateSoon />} />
        <Route
          path="depots"
          element={
            <ComingSoon title="Mes dépôts" icon={FolderGit2}>
              <p>Les dépôts GitHub, GitLab et Bitbucket arrivent avec la connexion des comptes.</p>
            </ComingSoon>
          }
        />
        <Route
          path="comptes"
          element={
            <ComingSoon title="Comptes" icon={KeyRound}>
              <p>La connexion à GitHub, GitLab et Bitbucket n'est pas encore disponible.</p>
            </ComingSoon>
          }
        />
        <Route
          path="pr"
          element={
            <ComingSoon title="PR et MR" icon={GitPullRequest}>
              <p>Les pull requests arrivent avec la connexion des comptes.</p>
            </ComingSoon>
          }
        />
        <Route
          path="reglages"
          element={
            <ComingSoon title="Réglages" icon={Settings}>
              <p>Les réglages ne sont pas encore disponibles : les options se choisissent à chaque analyse.</p>
            </ComingSoon>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

/** L'écran 5 (mise à jour) vient à l'étape suivante ; le lien du rapport y mène déjà. */
function UpdateSoon() {
  const { id } = useParams()
  return (
    <ComingSoon
      title="Mise à jour"
      icon={ListChecks}
      back={id ? { to: `/analyses/${id}`, label: 'Revenir au rapport' } : undefined}
    >
      <p>
        Choisir les mises à jour, voir le diff et appliquer : pas encore dans l'interface. En attendant,{' '}
        <code>forceupdate update</code> le fait en ligne de commande.
      </p>
    </ComingSoon>
  )
}

export function App() {
  const [client] = useState(createQueryClient)
  return (
    <QueryClientProvider client={client}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
