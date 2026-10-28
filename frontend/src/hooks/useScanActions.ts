import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { api, queryKeys } from '@/api/client'
import type { ScanOptions, ScanRequest, ScanSummary } from '@/api/types'
import { useOnline } from '@/hooks/useStatus'

/** Les options d'une analyse, celles de `forceupdate scan` par défaut. */
export const DEFAULT_OPTIONS: ScanOptions = {
  dev: true,
  transitive: false,
  include_tests: false,
  offline: false,
  cache: true,
}

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
