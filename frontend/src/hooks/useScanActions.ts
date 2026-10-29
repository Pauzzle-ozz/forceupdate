import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { api, queryKeys } from '@/api/client'
import type { RepositoryRequest, ScanOptions, ScanRequest, ScanSummary } from '@/api/types'
import { useOnline } from '@/hooks/useStatus'

/** Les options d'une analyse, celles de `forceupdate scan` par défaut. */
export const DEFAULT_OPTIONS: ScanOptions = {
  dev: true,
  transitive: false,
  include_tests: false,
  offline: false,
  cache: true,
}

/** Les options de l'analyse d'un dépôt : jamais hors ligne (tout vient de la forge). */
export const REPOSITORY_OPTIONS = { dev: true, transitive: false, include_tests: false, cache: true }

/** Les options choisies ; « hors ligne » est coché d'office tant qu'il n'y a pas de réseau. */
export function useScanOptions(): [ScanOptions, (options: ScanOptions) => void] {
  const online = useOnline()
  const [options, setOptions] = useState<ScanOptions>(DEFAULT_OPTIONS)
  const change = (next: ScanOptions) =>
    // Sans réseau, « hors ligne » est imposé : le choix d'avant revient avec le réseau.
    setOptions((current) => ({ ...next, offline: online ? next.offline : current.offline }))
  return [{ ...options, offline: options.offline || !online }, change]
}

/** Lance une analyse, puis ouvre son écran (`/analyses/{id}`). */
export function useStartScan() {
  const navigate = useNavigate()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (request: ScanRequest) => api.startScan(request),
    onSuccess: (scan) => opened(scan, client, navigate),
  })
}

/** Envoie un fichier (glisser-déposer ou « Choisir un fichier »), puis ouvre son analyse. */
export function useUpload() {
  const navigate = useNavigate()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => api.uploadFile(file),
    onSuccess: (scan) => opened(scan, client, navigate),
  })
}

/** Analyse un dépôt donné par son nom ou son adresse, puis ouvre son analyse. */
export function useScanRepository() {
  const navigate = useNavigate()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (request: RepositoryRequest) => api.scanRepository(request),
    onSuccess: (scan) => {
      void client.invalidateQueries({ queryKey: queryKeys.repositories })
      opened(scan, client, navigate)
    },
  })
}

/**
 * Relance une analyse finie (même source, mêmes options, `overrides` en plus) : un dossier ou un
 * fichier par `POST /api/scans`, un dépôt par `POST /api/repositories/scans`.
 */
export function useRescan() {
  const navigate = useNavigate()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ scan, overrides = {} }: { scan: ScanSummary; overrides?: Partial<ScanOptions> }) =>
      scan.kind === 'repository'
        ? api.scanRepository(repositoryRequest(scan, overrides))
        : api.startScan(rescanRequest(scan, overrides)),
    onSuccess: (scan) => {
      if (scan.kind === 'repository') void client.invalidateQueries({ queryKey: queryKeys.repositories })
      opened(scan, client, navigate)
    },
  })
}

function opened(
  scan: ScanSummary,
  client: ReturnType<typeof useQueryClient>,
  navigate: ReturnType<typeof useNavigate>,
) {
  client.setQueryData(queryKeys.scan(scan.id), { ...scan, report: null })
  void client.invalidateQueries({ queryKey: queryKeys.scans })
  void client.invalidateQueries({ queryKey: ['fs'] })
  void navigate(`/analyses/${scan.id}`)
}

/** Relance une analyse : même chemin, mêmes options (`overrides` en plus). */
export function rescanRequest(scan: ScanSummary, overrides: Partial<ScanOptions> = {}): ScanRequest {
  return { path: scan.source, ...scan.options, ...overrides }
}

/** Relance l'analyse d'un dépôt : jamais hors ligne (tout vient de la forge). */
export function repositoryRequest(scan: ScanSummary, overrides: Partial<ScanOptions> = {}): RepositoryRequest {
  const { dev, transitive, include_tests, cache } = { ...scan.options, ...overrides }
  return { repository: scan.source, dev, transitive, include_tests, cache }
}
