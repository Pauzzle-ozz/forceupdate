import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { GitPullRequest, Settings } from 'lucide-react'
import { useState } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { Choose } from '@/screens/Choose'
import { AccountsPage } from '@/screens/accounts/AccountsPage'
import { Home } from '@/screens/Home'
import { ScanPage } from '@/screens/ScanPage'
import { RepositoriesPage } from '@/screens/repositories/RepositoriesPage'
import { PlanPage } from '@/screens/update/PlanPage'
import { UpdatePage } from '@/screens/update/UpdatePage'
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
        <Route path="analyses/:id/mise-a-jour" element={<UpdatePage />} />
        <Route path="plans/:id" element={<PlanPage />} />
        <Route path="depots" element={<RepositoriesPage />} />
        <Route path="comptes" element={<AccountsPage />} />
        <Route
          path="pr"
          element={
            <ComingSoon title="PR et MR" icon={GitPullRequest}>
              <p>Les pull requests des dépôts à mettre à jour arrivent bientôt.</p>
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
