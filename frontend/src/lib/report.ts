/**
 * Le rapport, prêt à afficher. Pas de logique métier ici (elle est dans le moteur) : l'ordre
 * des constats, la sélection pré-cochée et les chiffres viennent de l'API. Seules les
 * déductions d'affichage sont faites : rattacher constats et mises à jour à leur ligne,
 * la gravité la plus haute d'une ligne, « non vérifiée » pour ce que les options n'ont pas
 * vérifié, filtrer et trier les lignes.
 */
import type {
  Dependency,
  Ecosystem,
  Finding,
  FindingKind,
  Gap,
  Project,
  Report,
  Severity,
  Update,
  UpdateOption,
} from '@/api/types'

export const SEVERITIES: Severity[] = ['critical', 'high', 'medium', 'low', 'info']

export const SEVERITY_LABEL: Record<Severity, string> = {
  critical: 'Critique',
  high: 'Élevée',
  medium: 'Moyenne',
  low: 'Faible',
  info: 'Information',
}

/** Pour les répartitions : « 13 élevées · 1 faible ». */
export const SEVERITY_WORD: Record<Severity, [string, string]> = {
  critical: ['critique', 'critiques'],
  high: ['élevée', 'élevées'],
  medium: ['moyenne', 'moyennes'],
  low: ['faible', 'faibles'],
  info: ['information', 'informations'],
}

/** Les types de constats, dans l'ordre des compteurs de la synthèse (maquette). */
export const KINDS: FindingKind[] = [
  'vulnerable',
  'outdated',
  'eol',
  'yanked',
  'deprecated',
  'unpinned',
  'unverifiable',
  'inconclusive',
]

export const KIND_LABEL: Record<FindingKind, string> = {
  vulnerable: 'Failles',
  outdated: 'Plus récentes',
  eol: 'Fins de vie',
  yanked: 'Retirées',
  deprecated: 'Dépréciées',
  unpinned: 'Versions non fixées',
  unverifiable: 'Non vérifiables',
  inconclusive: 'Non concluants',
}

/** Un constat d'un type, accordé : « 4 failles », « retirée ». */
export const KIND_WORD: Record<FindingKind, [string, string]> = {
  vulnerable: ['faille', 'failles'],
  outdated: ['plus récente', 'plus récentes'],
  eol: ['fin de vie', 'fins de vie'],
  yanked: ['retirée', 'retirées'],
  deprecated: ['dépréciée', 'dépréciées'],
  unpinned: ['version non fixée', 'versions non fixées'],
  unverifiable: ['non vérifiable', 'non vérifiables'],
  inconclusive: ['non concluant', 'non concluants'],
}

export const GAP_LABEL: Record<Gap, string> = {
  patch: 'Correctif',
  minor: 'Mineure',
  major: 'Majeure',
}

export const GAP_WORD: Record<Gap, [string, string]> = {
  patch: ['correctif', 'correctifs'],
  minor: ['mineure', 'mineures'],
  major: ['majeure', 'majeures'],
}

const SEVERITY_RANK: Record<Severity, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 }

/** Ce qu'on sait d'une dépendance qui n'a pas de constat. */
export type Coverage =
  | 'up-to-date' // vérifiée auprès des registres, et sans faille connue
  | 'audit-only' // indirecte sans « transitive » : failles cherchées, version non vérifiée
  | 'unchecked' // ni la version, ni les failles (options, version inconnue)
  | 'unverifiable' // dépendance git, chemin local… (unverifiable_reason)

/** Une ligne du tableau des dépendances : une déclaration, ses constats, sa mise à jour. */
export interface Row {
  key: string
  project: Project
  projectIndex: number
  dependency: Dependency
  /** Ses constats, dans l'ordre du rapport (du plus grave au moins grave). */
  findings: Finding[]
  /** La place de son premier constat dans le rapport : l'ordre « par gravité ». */
  order: number
  update: Update | null
  /** La gravité la plus haute, sans les « non concluant » ; `null` sans constat. */
  severity: Severity | null
  /** Ses seuls constats sont « non concluant » : la gravité est inconnue. */
  inconclusive: boolean
  coverage: Coverage
}

/** Une dépendance, en clé : les objets du rapport sont des copies, égales champ à champ. */
export function dependencyKey(dependency: Dependency): string {
  return JSON.stringify(dependency)
}

export function rows(report: Report): Row[] {
  const result: Row[] = []
  report.projects.forEach((project, projectIndex) => {
    const findings = new Map<string, Finding[]>()
    const order = new Map<string, number>()
    project.findings.forEach((finding, index) => {
      if (!finding.dependency) return
      const key = dependencyKey(finding.dependency)
      findings.set(key, [...(findings.get(key) ?? []), finding])
      if (!order.has(key)) order.set(key, index)
    })
    const updates = new Map<string, Update>()
    for (const update of project.updates) {
      for (const dependency of update.dependencies) updates.set(dependencyKey(dependency), update)
    }
    project.dependencies.forEach((dependency, index) => {
      const key = dependencyKey(dependency)
      const own = findings.get(key) ?? []
      const graded = own.filter((finding) => finding.kind !== 'inconclusive')
      result.push({
        key: `${projectIndex}:${index}`,
        project,
        projectIndex,
        dependency,
        findings: own,
        order: order.get(key) ?? Number.POSITIVE_INFINITY,
        update: updates.get(key) ?? null,
        severity: highest(graded.map((finding) => finding.severity)),
        inconclusive: own.length > 0 && graded.length === 0,
        coverage: coverage(dependency, report),
      })
    })
  })
  return result
}

export function highest(severities: Severity[]): Severity | null {
  let best: Severity | null = null
  for (const severity of severities) {
    if (best === null || SEVERITY_RANK[severity] < SEVERITY_RANK[best]) best = severity
  }
  return best
}

function coverage(dependency: Dependency, report: Report): Coverage {
  const options = report.options
  if (dependency.unverifiable_reason) return 'unverifiable'
  if (!options) return 'unchecked'
  if (dependency.scope === 'dev' && !options.dev) return 'unchecked'
  if (!dependency.direct && !options.transitive) {
    // Les failles d'une indirecte sont toujours cherchées, si sa version est connue.
    return dependency.installed ? 'audit-only' : 'unchecked'
  }
  return 'up-to-date'
}

/** L'option à montrer pour une mise à jour : la pré-cochée, sinon la plus récente. */
export function shownOption(update: Update): UpdateOption | null {
  const selected = update.options.find((option) => option.version === update.selected)
  return selected ?? update.options.at(-1) ?? null
}

/** Les mises à jour pré-cochées du rapport (le bouton « Mettre à jour »). */
export function selectedCount(report: Report): number {
  return report.projects.reduce(
    (total, project) => total + project.updates.filter((update) => update.selected).length,
    0,
  )
}

/** Les constats d'une ligne regroupés par type, dans l'ordre du rapport. */
export function findingsByKind(findings: Finding[]): [FindingKind, Finding[]][] {
  const groups = new Map<FindingKind, Finding[]>()
  for (const finding of findings) groups.set(finding.kind, [...(groups.get(finding.kind) ?? []), finding])
  return [...groups]
}

// -- Filtres et tris -------------------------------------------------------------------------

export type Directness = 'all' | 'direct' | 'indirect'
export type KindFilter = 'all' | 'none' | FindingKind
export type SortKey = 'severity' | 'name'

export interface Filters {
  query: string
  directness: Directness
  ecosystem: 'all' | Ecosystem
  kind: KindFilter
  project: 'all' | string
}

export interface Sort {
  key: SortKey
  descending: boolean
}

export const NO_FILTERS: Filters = {
  query: '',
  directness: 'all',
  ecosystem: 'all',
  kind: 'all',
  project: 'all',
}

/** Par défaut : la gravité, de la plus haute à la plus basse (l'ordre du rapport). */
export const DEFAULT_SORT: Sort = { key: 'severity', descending: true }

export function filterRows(all: Row[], filters: Filters): Row[] {
  const query = filters.query.trim().toLocaleLowerCase('fr')
  return all.filter((row) => {
    const { dependency } = row
    if (query && !dependency.name.toLocaleLowerCase('fr').includes(query)) return false
    if (filters.directness === 'direct' && !dependency.direct) return false
    if (filters.directness === 'indirect' && dependency.direct) return false
    if (filters.ecosystem !== 'all' && dependency.ecosystem !== filters.ecosystem) return false
    if (filters.project !== 'all' && row.project.path !== filters.project) return false
    if (filters.kind === 'none') return row.findings.length === 0
    if (filters.kind !== 'all') return row.findings.some((finding) => finding.kind === filters.kind)
    return true
  })
}

/** Rang de gravité d'une ligne : connue, puis inconnue (non concluant), puis sans constat. */
function severityRank(row: Row): number {
  if (row.severity) return SEVERITY_RANK[row.severity]
  return row.inconclusive ? 5 : 6
}

const byName = new Intl.Collator('fr', { sensitivity: 'base', numeric: true })

export function sortRows(all: Row[], sort: Sort): Row[] {
  const sign = sort.descending ? 1 : -1
  return [...all].sort((a, b) => {
    if (sort.key === 'name') {
      return -sign * byName.compare(a.dependency.name, b.dependency.name) || a.key.localeCompare(b.key)
    }
    return (
      sign *
        (severityRank(a) - severityRank(b) ||
          a.projectIndex - b.projectIndex ||
          a.order - b.order ||
          byName.compare(a.dependency.name, b.dependency.name)) ||
      a.key.localeCompare(b.key)
    )
  })
}

/** Les écosystèmes présents, dans l'ordre des projets. */
export function ecosystems(report: Report): Ecosystem[] {
  return [...new Set(report.projects.flatMap((project) => project.ecosystems))]
}

/** Le nom affiché d'un runtime, d'après son nom chez endoflife.date (`Runtime.product`). */
export const RUNTIME_LABEL: Record<string, string> = {
  python: 'Python',
  nodejs: 'Node.js',
  go: 'Go',
  ruby: 'Ruby',
  php: 'PHP',
  'eclipse-temurin': 'Java (Eclipse Temurin)',
  'amazon-corretto': 'Java (Amazon Corretto)',
  'azul-zulu': 'Java (Azul Zulu)',
  dotnet: '.NET',
  dotnetfx: '.NET Framework',
  rust: 'Rust',
}

/** Une version de runtime lue, avec tous les fichiers qui la donnent. */
export interface RuntimeLine {
  label: string
  version: string
  /** Une borne basse (`requires-python = ">=3.8"`) : « 3.8 et plus ». */
  approximate: boolean
  files: string[]
}

/** Les runtimes d'un projet, une ligne par version lue (« Python 3.8 : .python-version, Dockerfile »). */
export function runtimeLines(project: Project): RuntimeLine[] {
  const lines = new Map<string, RuntimeLine>()
  for (const runtime of project.runtimes) {
    const key = `${runtime.product}|${runtime.version}|${runtime.approximate}`
    const line = lines.get(key)
    if (line) {
      if (!line.files.includes(runtime.file)) line.files.push(runtime.file)
    } else {
      lines.set(key, {
        label: RUNTIME_LABEL[runtime.product] ?? runtime.product,
        version: runtime.version,
        approximate: runtime.approximate,
        files: [runtime.file],
      })
    }
  }
  return [...lines.values()]
}

/** « requirements.in, ligne 2 » */
export function where(file: string, line: number | null | undefined): string {
  return line ? `${file}, ligne ${line}` : file
}
