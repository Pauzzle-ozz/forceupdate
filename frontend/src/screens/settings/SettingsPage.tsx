import {
  ChevronRight,
  CircleCheck,
  CircleX,
  Database,
  LoaderCircle,
  Monitor,
  Moon,
  Sun,
  TriangleAlert,
} from 'lucide-react'
import { useId, useRef, useState, type ReactNode } from 'react'
import { fieldErrors } from '@/api/client'
import type { CacheState, Ecosystem, SettingsDocument } from '@/api/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Radio } from '@/components/ui/choice'
import { ConfirmDialog } from '@/components/ui/dialog'
import { fieldClass, Input } from '@/components/ui/input'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { useClearCache, useSaveSettings, useSettings } from '@/hooks/useSettings'
import { useTheme, type Theme } from '@/hooks/useTheme'
import { count, formatDateTime, fr } from '@/lib/format'
import {
  changed,
  ECOSYSTEMS,
  formatSize,
  LEVELS,
  problems as fieldProblems,
  toDraft,
  toRequest,
  type FieldProblem,
  type SettingsDraft,
  type SettingsField,
} from '@/lib/settings'
import { Container, PageHead, Section, useDocumentTitle } from '@/shell/Page'
import { cn } from 'cn'

/** Écran 9 : les réglages de la personne, le cache, le thème (design-system/ECRANS.md). */
export function SettingsPage() {
  useDocumentTitle('Réglages')
  const settings = useSettings()
  return (
    <Container narrow>
      <PageHead>
        <h1 className="text-2xl">Réglages</h1>
        <p className="text-fg-muted">
          {fr(
            "Ce qui vaut pour toutes les analyses, dans l'interface comme en ligne de commande. Un forceupdate.toml dans un projet prime sur eux : sa sélection, ses paquets ignorés.",
          )}
        </p>
      </PageHead>
      {settings.data ? (
        <>
          <SettingsForm document={settings.data} />
          <CacheSection cache={settings.data.cache} />
        </>
      ) : settings.isError ? (
        <Alert variant="danger" role="alert">
          <CircleX aria-hidden="true" />
          <AlertTitle>Réglages indisponibles</AlertTitle>
          <AlertDescription>
            <p>{settings.error.message}</p>
          </AlertDescription>
        </Alert>
      ) : (
        <SettingsSkeleton />
      )}
      <ThemeSection />
    </Container>
  )
}

function SettingsSkeleton() {
  return (
    <div aria-busy="true" aria-label="Chargement des réglages" className="flex flex-col gap-8">
      {[0, 1, 2].map((index) => (
        <div key={index} className="flex flex-col gap-3">
          <Skeleton className="h-6 w-56" />
          <Skeleton className="h-24 w-full" />
        </div>
      ))}
    </div>
  )
}

/** L'identifiant d'un champ, pour y mettre le focus quand il est refusé. */
const FOCUS: Record<Exclude<SettingsField, 'other'>, string> = {
  selection: 'niveau-patch',
  ignore: 'ignore',
  excluded_repositories: 'depots',
  lock_timeout: 'delai-lockfile',
  clone_timeout: 'delai-clone',
}

function SettingsForm({ document }: { document: SettingsDocument }) {
  const id = useId()
  const [draft, setDraft] = useState<SettingsDraft>(() => toDraft(document.values))
  const [refused, setRefused] = useState<FieldProblem[]>([])
  const [saved, setSaved] = useState(false)
  const save = useSaveSettings()
  const form = useRef<HTMLFormElement>(null)
  const dirty = changed(draft, document.values)

  const edit = (next: Partial<SettingsDraft>) => {
    setDraft((current) => ({ ...current, ...next }))
    setSaved(false)
  }

  const focusFirst = (found: FieldProblem[]) => {
    const first = found.find((problem) => problem.field !== 'other')
    if (first && first.field !== 'other') {
      form.current?.querySelector<HTMLElement>(`#${CSS.escape(`${id}-${FOCUS[first.field]}`)}`)?.focus()
    }
  }

  const submit = () => {
    const built = toRequest(draft)
    if ('problems' in built) {
      setRefused(built.problems)
      focusFirst(built.problems)
      return
    }
    setRefused([])
    save.mutate(built.request, {
      onSuccess: () => setSaved(true),
      onError: (error) => {
        const found = fieldProblems(fieldErrors(error), draft)
        setRefused(found)
        focusFirst(found)
      },
    })
  }

  const errorsOf = (field: SettingsField) => refused.filter((problem) => problem.field === field)
  const field = (name: string) => `${id}-${name}`
  const describedBy = (name: string, problemField: SettingsField) =>
    [field(`${name}-aide`), errorsOf(problemField).length ? field(`${name}-erreur`) : null].filter(Boolean).join(' ')

  const rejected = save.error && !fieldErrors(save.error).length ? save.error.message : null
  const others = errorsOf('other')

  return (
    <form
      ref={form}
      noValidate
      aria-label="Réglages"
      onSubmit={(event) => {
        event.preventDefault()
        submit()
      }}
    >
      {document.problems.length > 0 && (
        <Alert variant="warning" role="status" className="mb-6">
          <TriangleAlert aria-hidden="true" />
          <AlertTitle>{fr('Réglages en partie illisibles : valeurs par défaut à la place')}</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-5">
              {document.problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
            <p>{fr('Enregistrer les réécrit.')}</p>
          </AlertDescription>
        </Alert>
      )}

      <Section aria-labelledby={field('selection-titre')}>
        <h2 className="text-xl" id={field('selection-titre')}>Sélection par défaut</h2>
        <p className="text-sm text-fg-muted">
          {fr(
            'Ce que le plan de mise à jour pré-coche ; le reste est proposé, à cocher soi-même. Une majeure peut demander d\'adapter le code.',
          )}
        </p>
        <fieldset className="flex flex-col gap-2" aria-describedby={describedBy('selection', 'selection')}>
          <legend className="mb-2 font-medium">Pré-cocher</legend>
          {LEVELS.map((level) => (
            <label key={level.value} className="flex min-h-(--control-h) items-center gap-3">
              <Radio
                id={field(`niveau-${level.value}`)}
                name={field('niveau')}
                value={level.value}
                checked={draft.level === level.value}
                onChange={() => edit({ level: level.value })}
              />
              <span>
                {level.label}
                {level.value === toDraft(document.defaults).level
                  ? ' (par défaut)'
                  : ''}
                {' '}
                <span className="ml-1 font-mono text-sm text-fg-muted">{level.example}</span>
              </span>
            </label>
          ))}
          <div className="mt-1 flex min-h-(--control-h) items-center gap-3">
            <Switch
              id={field('failles')}
              checked={draft.securityOnly}
              onCheckedChange={(checked) => edit({ securityOnly: checked })}
              aria-describedby={field('failles-aide')}
            />
            <label htmlFor={field('failles')}>Seulement les corrections de failles</label>
          </div>
          <p id={field('failles-aide')} className="text-sm text-fg-muted">
            {fr('Pour chaque paquet, la plus petite version qui corrige le plus de failles. Désactivé par défaut.')}
          </p>
          <p id={field('selection-aide')} className="sr-only">
            {fr('Correctifs et mineures par défaut.')}
          </p>
          <FieldErrors id={field('selection-erreur')} problems={errorsOf('selection')} />
        </fieldset>
        <EcosystemRules draft={draft} onChange={(ecosystems) => edit({ ecosystems })} />
      </Section>

      <Section aria-labelledby={field('ignore-titre')}>
        <h2 className="text-xl" id={field('ignore-titre')}>Paquets et versions ignorés</h2>
        <div className="flex flex-col gap-1">
          <label htmlFor={field('ignore')} className="font-medium">
            Un par ligne
          </label>
          <p id={field('ignore-aide')} className="text-sm text-fg-muted">
            {fr('Un paquet (')}
            <code>lodash</code>, <code>@types/*</code>
            {fr(') : ni versions plus récentes ni mises à jour ; ses failles restent dites. Des versions (')}
            <code>django@&gt;=5</code>, <code>{'requests@<3,>=2.30'}</code>
            {fr(') : jamais proposées. Vide par défaut.')}
          </p>
          <textarea
            id={field('ignore')}
            className={cn(fieldClass, 'min-h-28 py-2 font-mono text-sm')}
            spellCheck={false}
            autoCapitalize="off"
            value={draft.ignore}
            onChange={(event) => edit({ ignore: event.target.value })}
            aria-describedby={describedBy('ignore', 'ignore')}
            aria-invalid={errorsOf('ignore').length > 0 || undefined}
          />
          <FieldErrors id={field('ignore-erreur')} problems={errorsOf('ignore')} />
        </div>
      </Section>

      <Section aria-labelledby={field('analyse-titre')}>
        <h2 className="text-xl" id={field('analyse-titre')}>Analyse</h2>
        <div className="flex min-h-(--control-h) items-center gap-3">
          <Switch
            id={field('tests')}
            checked={draft.includeTests}
            onCheckedChange={(checked) => edit({ includeTests: checked })}
            aria-describedby={field('tests-aide')}
          />
          <label htmlFor={field('tests')}>{fr("Analyser aussi les dossiers de tests et d'exemples")}</label>
        </div>
        <p id={field('tests-aide')} className="text-sm text-fg-muted">
          {fr(
            "L'option d'analyse cochée d'office, ici et pour forceupdate scan. Désactivé par défaut : leurs manifestes sont seulement listés.",
          )}
        </p>
      </Section>

      <Section aria-labelledby={field('depots-titre')}>
        <h2 className="text-xl" id={field('depots-titre')}>Dépôts exclus</h2>
        <div className="flex flex-col gap-1">
          <label htmlFor={field('depots')} className="font-medium">
            Un par ligne
          </label>
          <p id={field('depots-aide')} className="text-sm text-fg-muted">
            <code>github.com/propriétaire/dépôt</code>, <code>gitlab.com/groupe/*</code>
            {fr(
              ' : masqués dans « Mes dépôts » comme un dépôt archivé, jamais analysés avec les autres, jamais de PR. Vide par défaut.',
            )}
          </p>
          <textarea
            id={field('depots')}
            className={cn(fieldClass, 'min-h-24 py-2 font-mono text-sm')}
            spellCheck={false}
            autoCapitalize="off"
            value={draft.excludedRepositories}
            onChange={(event) => edit({ excludedRepositories: event.target.value })}
            aria-describedby={describedBy('depots', 'excluded_repositories')}
            aria-invalid={errorsOf('excluded_repositories').length > 0 || undefined}
          />
          <FieldErrors id={field('depots-erreur')} problems={errorsOf('excluded_repositories')} />
        </div>
      </Section>

      <Section aria-labelledby={field('outils-titre')}>
        <h2 className="text-xl" id={field('outils-titre')}>Outils</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <Seconds
            id={field('delai-lockfile')}
            label="Délai des outils de lockfile"
            help={fr('Pour chaque commande (npm, uv, cargo…), en secondes ; 600 par défaut.')}
            value={draft.lockTimeout}
            problems={errorsOf('lock_timeout')}
            onChange={(lockTimeout) => edit({ lockTimeout })}
          />
          <Seconds
            id={field('delai-clone')}
            label="Délai d'un clone ou d'un push"
            help={fr('Pour les PR, en secondes ; 600 par défaut.')}
            value={draft.cloneTimeout}
            problems={errorsOf('clone_timeout')}
            onChange={(cloneTimeout) => edit({ cloneTimeout })}
          />
        </div>
        <div className="flex min-h-(--control-h) items-center gap-3">
          <Switch
            id={field('rust')}
            checked={draft.rustDefaultToolchain}
            onCheckedChange={(checked) => edit({ rustDefaultToolchain: checked })}
            aria-describedby={field('rust-aide')}
          />
          <label htmlFor={field('rust')}>{fr('Rust : lancer cargo avec ma chaîne d\'outils par défaut')}</label>
        </div>
        <p id={field('rust-aide')} className="text-sm text-fg-muted">
          {fr(
            "Celle de rustup default, pas celle du rust-toolchain.toml du projet, que rustup installerait. Plus ancienne que ce que demande le projet, la régénération peut échouer. Désactivé par défaut.",
          )}
        </p>
      </Section>

      <div className="mt-8 flex flex-col gap-3 border-t border-border pt-6">
        {others.length > 0 && <FieldErrors id={field('autres-erreur')} problems={others} />}
        {(rejected || refused.length > 0) && (
          <Alert variant="danger" role="alert">
            <CircleX aria-hidden="true" />
            <AlertTitle>{fr('Réglages non enregistrés')}</AlertTitle>
            <AlertDescription>
              <p>
                {rejected ??
                  fr(
                    `${count(refused.length, 'valeur refusée', 'valeurs refusées')} : rien n'est enregistré. Les corriger sous leur champ.`,
                  )}
              </p>
            </AlertDescription>
          </Alert>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {save.isPending && <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />}
            Enregistrer
          </Button>
          <Button type="button" variant="ghost" onClick={() => edit(toDraft(document.defaults))}>
            Valeurs par défaut
          </Button>
          <p role="status" className="flex items-center gap-2 text-sm text-fg-muted">
            {saved && !dirty ? (
              <>
                <CircleCheck className="size-4 text-success" aria-hidden="true" />
                <span>{fr('Enregistré : vaut pour les analyses et les plans qui suivent.')}</span>
              </>
            ) : dirty ? (
              'Modifications non enregistrées.'
            ) : null}
          </p>
        </div>
        <p className="text-sm break-all text-fg-muted">
          {fr('Fichier : ')}
          <span className="font-mono">{document.file}</span>
        </p>
      </div>
    </form>
  )
}

/** La sélection par défaut d'un écosystème, à la place de la générale (repliée s'il n'y en a pas). */
function EcosystemRules({
  draft,
  onChange,
}: {
  draft: SettingsDraft
  onChange: (ecosystems: SettingsDraft['ecosystems']) => void
}) {
  const id = useId()
  const any = ECOSYSTEMS.some(
    ({ value }) => draft.ecosystems[value].level !== 'inherit' || draft.ecosystems[value].securityOnly !== 'inherit',
  )
  const set = (ecosystem: Ecosystem, next: Partial<SettingsDraft['ecosystems'][Ecosystem]>) =>
    onChange({ ...draft.ecosystems, [ecosystem]: { ...draft.ecosystems[ecosystem], ...next } })
  return (
    <details className="group" open={any || undefined}>
      <summary className="inline-flex min-h-(--control-h) items-center gap-2 text-sm font-medium">
        <ChevronRight
          className="size-4 transition-transform duration-200 ease-out group-open:rotate-90"
          aria-hidden="true"
        />
        {fr('Régler un écosystème à part')}
      </summary>
      <div className="flex flex-col gap-3 pt-2">
        <p className="text-sm text-fg-muted">{fr('« Comme les autres » : la sélection ci-dessus.')}</p>
        <ul className="flex flex-col divide-y divide-border rounded-md border border-border bg-surface">
          {ECOSYSTEMS.map(({ value, label }) => (
            <li key={value} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
              <span className="min-w-44 flex-1 font-medium">{label}</span>
              <div className="flex flex-wrap gap-2">
                <label className="sr-only" htmlFor={`${id}-${value}-niveau`}>
                  {`${label} : pré-cocher`}
                </label>
                <NativeSelect
                  id={`${id}-${value}-niveau`}
                  value={draft.ecosystems[value].level}
                  onChange={(event) =>
                    set(value, { level: event.target.value as SettingsDraft['ecosystems'][Ecosystem]['level'] })
                  }
                >
                  <NativeSelectOption value="inherit">Comme les autres</NativeSelectOption>
                  {LEVELS.map((level) => (
                    <NativeSelectOption key={level.value} value={level.value}>
                      {level.label}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
                <label className="sr-only" htmlFor={`${id}-${value}-failles`}>
                  {`${label} : seulement les corrections de failles`}
                </label>
                <NativeSelect
                  id={`${id}-${value}-failles`}
                  value={draft.ecosystems[value].securityOnly}
                  onChange={(event) =>
                    set(value, {
                      securityOnly: event.target.value as SettingsDraft['ecosystems'][Ecosystem]['securityOnly'],
                    })
                  }
                >
                  <NativeSelectOption value="inherit">Failles : comme les autres</NativeSelectOption>
                  <NativeSelectOption value="yes">Seulement les failles</NativeSelectOption>
                  <NativeSelectOption value="no">Pas seulement les failles</NativeSelectOption>
                </NativeSelect>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </details>
  )
}

function Seconds({
  id,
  label,
  help,
  value,
  problems,
  onChange,
}: {
  id: string
  label: string
  help: string
  value: string
  problems: FieldProblem[]
  onChange: (value: string) => void
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="font-medium">
        {label}
      </label>
      <Input
        id={id}
        type="number"
        inputMode="numeric"
        min={10}
        max={86400}
        step={1}
        className="max-w-40 tabular-nums"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-describedby={[`${id}-aide`, problems.length ? `${id}-erreur` : null].filter(Boolean).join(' ')}
        aria-invalid={problems.length > 0 || undefined}
      />
      <p id={`${id}-aide`} className="text-sm text-fg-muted">
        {help}
      </p>
      <FieldErrors id={`${id}-erreur`} problems={problems} />
    </div>
  )
}

/** Les valeurs refusées d'un champ, sous lui (« Ligne 3 : … » pour une liste). */
function FieldErrors({ id, problems }: { id: string; problems: FieldProblem[] }) {
  if (!problems.length) return null
  return (
    <ul id={id} className="flex flex-col gap-1 text-sm text-danger">
      {problems.map((problem, index) => (
        <li key={index} className="flex items-start gap-2">
          <CircleX className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span>
            {problem.line !== null && fr(`Ligne ${problem.line} : `)}
            {problem.message}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** Le cache disque : ce qu'il contient, et le vider (confirmé). */
function CacheSection({ cache }: { cache: CacheState }) {
  const id = useId()
  const clear = useClearCache()
  const [asking, setAsking] = useState(false)
  const [cleared, setCleared] = useState(false)
  return (
    <Section aria-labelledby={`${id}-titre`}>
      <h2 className="text-xl" id={`${id}-titre`}>Cache</h2>
      <p className="text-sm text-fg-muted">
        {fr(
          "Les réponses des registres, d'OSV et d'endoflife.date, gardées de 1 h à 7 jours : une analyse relancée va plus vite, et hors ligne, c'est tout ce qu'il reste.",
        )}
      </p>
      <Card className="flex flex-col gap-4">
        {!cache.enabled && (
          <Alert variant="warning" role="status">
            <TriangleAlert aria-hidden="true" />
            <AlertTitle>{fr('Cache désactivé')}</AlertTitle>
            <AlertDescription>
              <p>{fr("Son fichier ne s'ouvre pas, ou le disque refuse l'écriture : chaque analyse redemande tout.")}</p>
            </AlertDescription>
          </Alert>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <CacheRow label="Contenu">
            <span className="tabular-nums">
              {cache.entries === 0
                ? 'vide'
                : `${count(cache.entries, 'réponse gardée', 'réponses gardées')}, ${formatSize(cache.size)}`}
            </span>
          </CacheRow>
          {cache.oldest && cache.newest && (
            <CacheRow label="Dates">
              {`du ${formatDateTime(cache.oldest)} au ${formatDateTime(cache.newest)}`}
            </CacheRow>
          )}
          {cache.path && (
            <CacheRow label="Fichier">
              <span className="font-mono break-all">{cache.path}</span>
            </CacheRow>
          )}
        </dl>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="danger"
            disabled={clear.isPending || cache.entries === 0}
            onClick={() => {
              setCleared(false)
              setAsking(true)
            }}
          >
            {clear.isPending ? (
              <LoaderCircle className="motion-safe:animate-spin" aria-hidden="true" />
            ) : (
              <Database aria-hidden="true" />
            )}
            Vider le cache…
          </Button>
          <p role="status" className="flex items-center gap-2 text-sm text-fg-muted">
            {cleared && (
              <>
                <CircleCheck className="size-4 text-success" aria-hidden="true" />
                <span>{fr('Cache vidé : la prochaine analyse redemande tout.')}</span>
              </>
            )}
          </p>
        </div>
        {clear.isError && (
          <p role="alert" className="flex items-start gap-2 text-sm text-danger">
            <CircleX className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {clear.error.message}
          </p>
        )}
      </Card>
      <ConfirmDialog
        open={asking}
        title="Vider le cache ?"
        confirm="Vider le cache"
        onCancel={() => setAsking(false)}
        onConfirm={() => {
          setAsking(false)
          clear.mutate(undefined, { onSuccess: () => setCleared(true) })
        }}
      >
        <p>
          {fr(
            `${count(cache.entries, 'réponse', 'réponses')} effacée${cache.entries >= 2 ? 's' : ''} : la prochaine analyse redemandera tout aux registres, à OSV et à endoflife.date. Hors ligne, il ne restera rien.`,
          )}
        </p>
      </ConfirmDialog>
    </Section>
  )
}

function CacheRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-fg-muted">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </>
  )
}

const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: 'system', label: 'Celui du système', icon: Monitor },
  { value: 'light', label: 'Clair', icon: Sun },
  { value: 'dark', label: 'Sombre', icon: Moon },
]

/** Le thème : appliqué tout de suite, gardé dans ce navigateur (comme le bouton de l'en-tête). */
function ThemeSection() {
  const id = useId()
  const [theme, setTheme] = useTheme()
  return (
    <Section aria-labelledby={`${id}-titre`}>
      <h2 className="text-xl" id={`${id}-titre`}>Thème</h2>
      <fieldset className="flex flex-col gap-1" aria-describedby={`${id}-aide`}>
        <legend className="sr-only">Thème</legend>
        {THEMES.map(({ value, label, icon: Icon }) => (
          <label key={value} className="flex min-h-(--control-h) items-center gap-3">
            <Radio name={`${id}-theme`} value={value} checked={theme === value} onChange={() => setTheme(value)} />
            <Icon className="size-4 text-fg-muted" aria-hidden="true" />
            <span>
              {label}
              {value === 'system' ? ' (par défaut)' : ''}
            </span>
          </label>
        ))}
      </fieldset>
      <p id={`${id}-aide`} className="text-sm text-fg-muted">
        {fr("Appliqué tout de suite et gardé dans ce navigateur, comme le bouton de l'en-tête.")}
      </p>
    </Section>
  )
}
