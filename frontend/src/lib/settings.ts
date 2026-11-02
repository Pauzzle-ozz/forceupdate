/**
 * L'écran Réglages (écran 9) : le formulaire et ce qu'il envoie. Rien n'est vérifié ici que le
 * serveur ne vérifie pas (`preferences.from_table`) : on y met seulement en forme une liste
 * écrite une valeur par ligne, et on retrouve la ligne d'une valeur refusée.
 */
import type { Ecosystem, FieldError, Gap, Preferences, SelectionInput, SettingsRequest } from '@/api/types'
import { NBSP } from '@/lib/format'

/** Les écosystèmes, dans l'ordre du brief, avec le langage qui les fait reconnaître. */
export const ECOSYSTEMS: { value: Ecosystem; label: string }[] = [
  { value: 'PyPI', label: 'Python (PyPI)' },
  { value: 'npm', label: 'JavaScript (npm)' },
  { value: 'crates.io', label: 'Rust (crates.io)' },
  { value: 'Go', label: 'Go' },
  { value: 'Packagist', label: 'PHP (Packagist)' },
  { value: 'RubyGems', label: 'Ruby (RubyGems)' },
  { value: 'Maven', label: 'Java (Maven, Gradle)' },
  { value: 'NuGet', label: '.NET (NuGet)' },
]

/** Les niveaux de la sélection, du plus prudent au plus large. */
export const LEVELS: { value: Gap; label: string; example: string }[] = [
  { value: 'patch', label: 'Correctifs', example: '2.3.1 → 2.3.4' },
  { value: 'minor', label: 'Correctifs et mineures', example: '2.3.1 → 2.9.0' },
  { value: 'major', label: 'Correctifs, mineures et majeures', example: '2.3.1 → 3.0.0' },
]

/** Pour un écosystème : « comme les autres », ou une valeur à lui. */
export type Inherited<T> = T | 'inherit'

export interface EcosystemDraft {
  level: Inherited<Gap>
  securityOnly: Inherited<'yes' | 'no'>
}

/** Le formulaire, tel qu'on l'édite. */
export interface SettingsDraft {
  ignore: string
  includeTests: boolean
  level: Gap
  securityOnly: boolean
  ecosystems: Record<Ecosystem, EcosystemDraft>
  excludedRepositories: string
  lockTimeout: string
  cloneTimeout: string
  rustDefaultToolchain: boolean
}

/** Les champs du formulaire, comme les nomme l'API (`FieldError.field`). */
export type SettingsField = 'ignore' | 'excluded_repositories' | 'lock_timeout' | 'clone_timeout' | 'selection' | 'other'

/** Une valeur refusée, rattachée à son champ, avec sa ligne pour une liste. */
export interface FieldProblem {
  field: SettingsField
  line: number | null
  message: string
}

const INHERIT: EcosystemDraft = { level: 'inherit', securityOnly: 'inherit' }

/** Le formulaire rempli avec des réglages. */
export function toDraft(preferences: Preferences): SettingsDraft {
  const general = preferences.selection.find((rule) => rule.ecosystem === null)
  const ecosystems = Object.fromEntries(ECOSYSTEMS.map(({ value }) => [value, { ...INHERIT }])) as Record<
    Ecosystem,
    EcosystemDraft
  >
  for (const rule of preferences.selection) {
    if (rule.ecosystem === null) continue
    ecosystems[rule.ecosystem] = {
      level: rule.level ?? 'inherit',
      securityOnly: rule.security_only === null ? 'inherit' : rule.security_only ? 'yes' : 'no',
    }
  }
  return {
    ignore: preferences.ignore.join('\n'),
    includeTests: preferences.include_tests,
    level: general?.level ?? 'minor',
    securityOnly: general?.security_only ?? false,
    ecosystems,
    excludedRepositories: preferences.excluded_repositories.join('\n'),
    lockTimeout: String(preferences.lock_timeout),
    cloneTimeout: String(preferences.clone_timeout),
    rustDefaultToolchain: preferences.rust_default_toolchain,
  }
}

/** Les valeurs non vides d'une liste écrite une par ligne, avec leur numéro de ligne. */
export function lines(text: string): { value: string; line: number }[] {
  return text
    .split(/\r?\n/)
    .map((value, index) => ({ value: value.trim(), line: index + 1 }))
    .filter((entry) => entry.value !== '')
}

/** Un nombre entier de secondes ; `null` s'il ne s'en lit pas (le serveur vérifie le reste). */
function seconds(text: string): number | null {
  return /^\s*\d+\s*$/.test(text) ? Number.parseInt(text, 10) : null
}

/**
 * Ce que le formulaire envoie (`PUT /api/settings`), ou les champs qui ne se lisent pas (un
 * délai qui n'est pas un nombre entier) : rien n'est alors envoyé.
 */
export function toRequest(draft: SettingsDraft): { request: SettingsRequest } | { problems: FieldProblem[] } {
  const lockTimeout = seconds(draft.lockTimeout)
  const cloneTimeout = seconds(draft.cloneTimeout)
  const problems: FieldProblem[] = []
  const notNumber = 'Un nombre entier de secondes est attendu.'
  if (lockTimeout === null) problems.push({ field: 'lock_timeout', line: null, message: notNumber })
  if (cloneTimeout === null) problems.push({ field: 'clone_timeout', line: null, message: notNumber })
  if (lockTimeout === null || cloneTimeout === null) return { problems }
  const selection: SelectionInput[] = [{ ecosystem: null, level: draft.level, security_only: draft.securityOnly }]
  for (const { value } of ECOSYSTEMS) {
    const own = draft.ecosystems[value]
    if (own.level === 'inherit' && own.securityOnly === 'inherit') continue
    selection.push({
      ecosystem: value,
      level: own.level === 'inherit' ? null : own.level,
      security_only: own.securityOnly === 'inherit' ? null : own.securityOnly === 'yes',
    })
  }
  return {
    request: {
      ignore: lines(draft.ignore).map((entry) => entry.value),
      include_tests: draft.includeTests,
      selection,
      excluded_repositories: lines(draft.excludedRepositories).map((entry) => entry.value),
      lock_timeout: lockTimeout,
      clone_timeout: cloneTimeout,
      rust_default_toolchain: draft.rustDefaultToolchain,
    },
  }
}

const FIELDS: SettingsField[] = ['ignore', 'excluded_repositories', 'lock_timeout', 'clone_timeout', 'selection']

/** Les valeurs refusées par le serveur, rattachées à leur champ et à leur ligne du formulaire. */
export function problems(errors: FieldError[], draft: SettingsDraft): FieldProblem[] {
  return errors.map((error) => {
    const field = (FIELDS as string[]).includes(error.field) ? (error.field as SettingsField) : 'other'
    let line: number | null = null
    if (error.index !== null && (field === 'ignore' || field === 'excluded_repositories')) {
      const text = field === 'ignore' ? draft.ignore : draft.excludedRepositories
      line = lines(text)[error.index]?.line ?? null
    }
    return { field, line, message: error.message }
  })
}

/** Vrai si le formulaire diffère des réglages enregistrés. */
export function changed(draft: SettingsDraft, saved: Preferences): boolean {
  return JSON.stringify(toRequest(draft)) !== JSON.stringify(toRequest(toDraft(saved)))
}

const sizeFormat = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 1 })

/** « 0 octet », « 340 ko », « 12,4 Mo ». */
export function formatSize(bytes: number): string {
  if (bytes < 1000) return `${bytes}${NBSP}${bytes >= 2 ? 'octets' : 'octet'}`
  if (bytes < 1_000_000) return `${sizeFormat.format(bytes / 1000)}${NBSP}ko`
  if (bytes < 1_000_000_000) return `${sizeFormat.format(bytes / 1_000_000)}${NBSP}Mo`
  return `${sizeFormat.format(bytes / 1_000_000_000)}${NBSP}Go`
}
