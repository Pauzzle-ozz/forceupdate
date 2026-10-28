/**
 * L'écran 5, prêt à afficher. Pas de logique métier ici : les options, la pré-sélection, ce
 * qui sera écrit, sauté ou régénéré viennent de l'API (le rapport, puis le plan). Seules les
 * déductions d'affichage sont faites : grouper les cartes par lockfile, cocher et décocher
 * (au plus une option par mise à jour), compter le récapitulatif sur la sélection affichée,
 * découper un diff unifié en lignes.
 */
import type {
  Edit,
  Finding,
  LockJob,
  Project,
  Report,
  Selection,
  Severity,
  Update,
  UpdateOption,
  UpdatePlan,
  UpdateReason,
} from '@/api/types'
import { count } from '@/lib/format'
import { dependencyKey, highest } from '@/lib/report'

export const REASON_WORD: Record<UpdateReason, string> = {
  latest_patch: 'dernier correctif',
  latest_minor: 'dernière mineure',
  latest_major: 'dernière version',
  security_fix: 'corrige les failles',
  replacement: 'remplace une version retirée ou dépréciée',
}

/** Les raisons d'une option, en clair : « dernière mineure · corrige les failles ». */
export function reasonsText(option: UpdateOption): string {
  return option.reasons.map((reason) => REASON_WORD[reason] ?? reason).join(' · ')
}

/**
 * Ce que corrige une option, en phrase : « Corrige 4 failles sur 6, en laisse 2 »,
 * « Corrige les 6 failles », « Laisse 3 failles ». `full` : toutes corrigées.
 */
export function fixesSentence(option: UpdateOption): { text: string; full: boolean } | null {
  const fixed = option.fixes.length
  const left = option.unfixed.length
  if (fixed + left === 0) return null
  if (left === 0) return { text: fixed === 1 ? 'Corrige la faille' : `Corrige les ${fixed} failles`, full: true }
  if (fixed === 0) return { text: `Laisse ${count(left, 'faille')}`, full: false }
  return { text: `Corrige ${count(fixed, 'faille')} sur ${fixed + left}, en laisse ${left}`, full: false }
}

/** Une réécriture : « package.json : 4.17.15 → 4.18.1 » (la flèche est posée par l'appelant). */
export function editFile(edit: Edit): string {
  if (edit.kind === 'catalog') return `${edit.file} (catalogue pnpm)`
  if (edit.kind === 'override') return `${edit.override?.file ?? edit.file} (version forcée)`
  return edit.file
}

// -- Les cartes : une par mise à jour, groupées par lockfile -----------------------------------

/** Le lockfile d'une mise à jour : celui de ses options, sinon celui de sa déclaration. */
export function updateLockfile(update: Update): string | null {
  return update.options.find((option) => option.lockfile)?.lockfile ?? update.dependencies[0]?.lockfile ?? null
}

/** Les mises à jour régénérées ensemble : un projet, un lockfile (ou aucun). */
export interface Group {
  key: string
  project: Project
  lockfile: string | null
  updates: Update[]
}

/**
 * Les cartes groupées par lockfile, dans l'ordre du rapport : projet après projet, ses lockfiles
 * dans l'ordre où il les donne, puis ce qui n'en a pas ; dans un groupe, l'ordre des constats.
 */
export function groups(report: Report): Group[] {
  const result: Group[] = []
  for (const project of report.projects) {
    const byLockfile = new Map<string | null, Update[]>()
    for (const update of project.updates) {
      const lockfile = updateLockfile(update)
      byLockfile.set(lockfile, [...(byLockfile.get(lockfile) ?? []), update])
    }
    const named = [...project.lockfiles, ...byLockfile.keys()].filter((name) => name !== null)
    for (const lockfile of new Set([...named, null])) {
      const updates = byLockfile.get(lockfile)
      if (updates) result.push({ key: `${project.path}|${lockfile ?? ''}`, project, lockfile, updates })
    }
  }
  return result
}

/** Les failles d'une mise à jour (celles de ses déclarations), et la plus haute gravité. */
export function updateVulnerabilities(project: Project, update: Update): { count: number; severity: Severity | null } {
  const keys = new Set(update.dependencies.map(dependencyKey))
  const findings: Finding[] = project.findings.filter(
    (finding) => finding.kind === 'vulnerable' && finding.dependency && keys.has(dependencyKey(finding.dependency)),
  )
  const option = update.options[0]
  // Un paquet déclaré deux fois a ses failles en double dans les constats : les options, elles,
  // les comptent une fois.
  const total = option ? option.fixes.length + option.unfixed.length : new Set(findings.map((f) => f.message)).size
  return { count: total, severity: highest(findings.map((finding) => finding.severity)) }
}

// -- La sélection : au plus une option par mise à jour -----------------------------------------

/** La sélection proposée : les options `selected` du rapport. */
export function defaultSelection(report: Report): Selection {
  const selection: Selection = {}
  for (const project of report.projects) {
    for (const update of project.updates) {
      if (update.selected) selection[update.id] = update.selected
    }
  }
  return selection
}

/** L'option qu'on reprend en recochant un paquet : la proposée, sinon la première faisable. */
export function resumeOption(update: Update): string | null {
  if (update.selected) return update.selected
  return update.options.find((option) => !option.manual)?.version ?? null
}

/** Coche ou décoche un paquet. */
export function toggle(selection: Selection, update: Update, on: boolean): Selection {
  const next = { ...selection }
  const version = on ? resumeOption(update) : null
  if (version) next[update.id] = version
  else delete next[update.id]
  return next
}

/** Choisit la version d'un paquet (ce qui le coche). */
export function choose(selection: Selection, update: Update, version: string): Selection {
  return { ...selection, [update.id]: version }
}

/** Les mises à jour du rapport, par identifiant, avec leur projet. */
export function updatesById(report: Report): Map<string, { update: Update; project: Project }> {
  const found = new Map<string, { update: Update; project: Project }>()
  for (const project of report.projects) {
    for (const update of project.updates) found.set(update.id, { update, project })
  }
  return found
}

/** L'option choisie d'une mise à jour, ou `null`. */
export function chosenOption(update: Update, version: string | undefined): UpdateOption | null {
  return version ? (update.options.find((option) => option.version === version) ?? null) : null
}

export interface Recap {
  /** Mises à jour cochées, sur celles qui ont au moins une option. */
  chosen: number
  total: number
  /** Failles corrigées par les options cochées, sur celles des paquets qui ont des options. */
  fixed: number
  vulnerabilities: number
  /** Failles que des options cochées apportent. */
  introduced: number
  majors: number
  /** Les fichiers que les options cochées réécrivent, et leurs lockfiles. */
  files: string[]
  lockfiles: string[]
}

/** Le récapitulatif, compté sur la sélection affichée. */
export function recap(report: Report, selection: Selection): Recap {
  const result: Recap = { chosen: 0, total: 0, fixed: 0, vulnerabilities: 0, introduced: 0, majors: 0, files: [], lockfiles: [] }
  const files = new Set<string>()
  const lockfiles = new Set<string>()
  // Dans l'ordre des cartes.
  for (const group of groups(report)) {
    for (const update of group.updates) {
      const first = update.options[0]
      if (!first) continue
      result.total += 1
      result.vulnerabilities += first.fixes.length + first.unfixed.length
      const option = chosenOption(update, selection[update.id])
      if (!option) continue
      result.chosen += 1
      result.fixed += option.fixes.length
      result.introduced += option.introduced.length
      if (option.gap === 'major') result.majors += 1
      for (const edit of option.edits) files.add(edit.file)
      if (option.lockfile) lockfiles.add(option.lockfile)
    }
  }
  result.files = [...files]
  result.lockfiles = [...lockfiles]
  return result
}

// -- Le plan ------------------------------------------------------------------------------------

/** Les fichiers que touche une option du plan : ses manifestes, puis le lockfile qui la porte. */
export function plannedFiles(plan: UpdatePlan, update: Update, version: string): { files: string[]; lockfileOnly: boolean } {
  const option = chosenOption(update, version)
  const files = [...new Set(option?.edits.map((edit) => edit.file) ?? [])]
  const jobs = plan.lockfiles.filter((job) => job.updates.some((chosen) => chosen.update === update.id))
  return { files: [...files, ...jobs.map((job) => job.lockfile)], lockfileOnly: files.length === 0 && jobs.length > 0 }
}

/** Les outils qui tourneront (ceux qui ont besoin du réseau), sans doublon : « npm et uv ». */
export function runnableTools(jobs: LockJob[]): string[] {
  return [...new Set(jobs.filter((job) => job.available).map((job) => job.program))]
}

/** « a », « a et b », « a, b et c ». */
export function listText(items: string[]): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} et ${items.at(-1)}`
}

/** Le dossier où lancer une commande, pour la montrer : celui de la source, ou un sous-dossier. */
export function commandDirectory(source: string, directory: string): string {
  if (directory === '.' || directory === '') return source
  if (/^([A-Za-z]:)?\//.test(directory)) return directory
  return `${source.replace(/\/+$/, '')}/${directory}`
}

/** Les `n` dernières lignes non vides d'une sortie d'outil. */
export function lastLines(text: string, n = 12): string {
  return text
    .split(/\r?\n/)
    .filter((line) => line.trim() !== '')
    .slice(-n)
    .join('\n')
}

// -- Diff unifié --------------------------------------------------------------------------------

export interface DiffLine {
  kind: 'hunk' | 'context' | 'add' | 'del' | 'note'
  text: string
  /** Numéros de ligne avant et après (le bloc `@@` et une note n'en ont pas). */
  old: number | null
  new: number | null
}

export interface ParsedDiff {
  lines: DiffLine[]
  added: number
  removed: number
}

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/

/** Un diff unifié (comme `git diff`) en lignes numérotées ; les en-têtes `---`/`+++` sont omis. */
export function parseDiff(text: string): ParsedDiff {
  const lines: DiffLine[] = []
  let added = 0
  let removed = 0
  let old = 0
  let now = 0
  let inHunk = false
  for (const raw of text.replace(/\n$/, '').split('\n')) {
    const hunk = HUNK.exec(raw)
    if (hunk) {
      old = Number(hunk[1])
      now = Number(hunk[2])
      inHunk = true
      lines.push({ kind: 'hunk', text: raw, old: null, new: null })
    } else if (!inHunk) {
      continue // --- a/… et +++ b/…
    } else if (raw.startsWith('+')) {
      added += 1
      lines.push({ kind: 'add', text: raw.slice(1), old: null, new: now++ })
    } else if (raw.startsWith('-')) {
      removed += 1
      lines.push({ kind: 'del', text: raw.slice(1), old: old++, new: null })
    } else if (raw.startsWith('\\')) {
      lines.push({ kind: 'note', text: raw.slice(2), old: null, new: null })
    } else {
      lines.push({ kind: 'context', text: raw.slice(1), old: old++, new: now++ })
    }
  }
  return { lines, added, removed }
}
