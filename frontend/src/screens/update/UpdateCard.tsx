import { Ban, Info, OctagonAlert, ShieldAlert, ShieldCheck, TriangleAlert } from 'lucide-react'
import { useId } from 'react'
import { cn } from 'cn'
import type { Project, Update, UpdateOption } from '@/api/types'
import { GapBadge, SeverityBadge } from '@/components/badges'
import { Badge } from '@/components/ui/badge'
import { Checkbox, Radio } from '@/components/ui/choice'
import { NBSP, count } from '@/lib/format'
import { GAP_LABEL } from '@/lib/report'
import { chosenOption, editFile, fixesSentence, reasonsText, updateVulnerabilities } from '@/lib/update'
import { Version, VersionArrow } from '../report/cells'

/**
 * Une mise à jour (MASTER, « Groupe d'options d'une mise à jour » ; pages/mise-a-jour.md, « Les
 * cartes de mise à jour ») : la case du paquet et les boutons radio de ses options, puisqu'au
 * plus une est choisie. Choisir une version coche le paquet ; décocher le paquet vide le choix ;
 * le recocher reprend l'option proposée.
 */
export function UpdateCard({
  project,
  update,
  chosen,
  onToggle,
  onChoose,
  cardRef,
}: {
  project: Project
  update: Update
  /** La version cochée, s'il y en a une. */
  chosen: string | undefined
  onToggle: (on: boolean) => void
  onChoose: (version: string) => void
  /** La carte visée par l'adresse (`?paquet=`) : elle reçoit le focus. */
  cardRef?: React.Ref<HTMLElement>
}) {
  const id = useId()
  const option = chosenOption(update, chosen)
  const vulnerabilities = updateVulnerabilities(project, update)
  const selectable = update.options.some((candidate) => !candidate.manual)
  const empty = update.options.length === 0

  return (
    <article
      ref={cardRef}
      tabIndex={cardRef ? -1 : undefined}
      aria-labelledby={`${id}-nom`}
      className={cn(
        'scroll-mt-20 rounded-md border bg-surface transition-colors duration-150 focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-bg',
        option ? 'border-primary/50' : 'border-border',
      )}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
        <label className="inline-flex min-w-0 items-center gap-3">
          <Checkbox
            checked={option !== null}
            disabled={!selectable}
            onChange={(event) => onToggle(event.target.checked)}
            aria-describedby={`${id}-sous`}
          />
          <span id={`${id}-nom`} className="font-mono font-semibold break-all">
            {update.name}
          </span>
        </label>
        <Badge variant="outline">{update.direct ? 'directe' : 'indirecte'}</Badge>
        {empty && vulnerabilities.severity && <SeverityBadge severity={vulnerabilities.severity} />}
        <span id={`${id}-sous`} className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm text-fg-muted">
          {update.current_version ? (
            <>
              utilisée <Version>{update.current_version}</Version>
              {update.current_is_approximate && ' (approximative)'}
            </>
          ) : (
            'version utilisée inconnue'
          )}
          {vulnerabilities.count > 0 && !empty && (
            <>
              {' · '}
              <Badge variant={vulnerabilities.severity ?? 'medium'}>
                <ShieldAlert aria-hidden="true" />
                {count(vulnerabilities.count, 'faille')}
              </Badge>
            </>
          )}
          {!update.direct && ' · par le lockfile seul'}
        </span>
      </div>

      {update.note &&
        (empty ? (
          <p className="flex items-start gap-2 border-t border-border px-4 py-3 text-sm text-danger">
            <OctagonAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {update.note}
          </p>
        ) : (
          <p className="-mt-1 flex items-start gap-2 px-4 pb-3 text-sm text-fg-muted">
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {update.note}
          </p>
        ))}

      {!empty && (
        <div role="radiogroup" aria-label={`Version visée pour ${update.name}`} className="flex flex-col border-t border-border">
          {update.options.map((candidate) => (
            <OptionRow
              key={candidate.version}
              update={update}
              option={candidate}
              checked={candidate.version === option?.version}
              onChoose={() => onChoose(candidate.version)}
            />
          ))}
        </div>
      )}
    </article>
  )
}

/** Une option : toute la ligne est la cible du bouton radio ; une option `manual` est grisée. */
function OptionRow({
  update,
  option,
  checked,
  onChoose,
}: {
  update: Update
  option: UpdateOption
  checked: boolean
  onChoose: () => void
}) {
  const id = useId()
  const manual = option.manual !== null
  const fixes = fixesSentence(option)
  const reasons = reasonsText(option)
  const proposed = update.selected === option.version
  // Le nom du bouton, en mots séparés (les badges collés au texte se liraient « 4.18.1Mineure »).
  const label = [
    option.version,
    option.gap && GAP_LABEL[option.gap].toLowerCase(),
    manual && 'à faire à la main',
    reasons,
    proposed && 'proposée',
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <label
      className={cn(
        'grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 px-4 py-3 transition-colors duration-150 not-first:border-t not-first:border-dashed not-first:border-border',
        manual ? 'cursor-not-allowed' : 'hover:bg-surface-hover',
        checked && 'bg-primary-soft hover:bg-primary-soft',
      )}
    >
      <Radio
        name={`option-${update.id}`}
        value={option.version}
        checked={checked}
        disabled={manual}
        onChange={onChoose}
        aria-label={label}
        aria-describedby={`${id}-plus`}
      />
      <span className={cn('flex flex-wrap items-center gap-x-2 gap-y-1', manual && 'opacity-60')}>
        <span className="font-mono text-sm font-semibold">{option.version}</span>
        {option.gap && <GapBadge gap={option.gap} />}
        {manual && (
          <Badge variant="neutral">
            <Ban aria-hidden="true" />à faire à la main
          </Badge>
        )}
        {reasons && <span className="text-sm">{reasons}</span>}
        {proposed && <Badge variant="primary">proposée</Badge>}
      </span>
      <span id={`${id}-plus`} className="col-start-2 flex flex-col gap-1 text-sm text-fg-muted">
        {option.manual && <span>{option.manual}</span>}
        {fixes && (
          <span className={cn('inline-flex items-center gap-1', fixes.full && 'text-success')}>
            {fixes.full && <ShieldCheck className="size-4 shrink-0" aria-hidden="true" />}
            {fixes.text}
          </span>
        )}
        {option.warnings.map((warning) => {
          // L'avertissement d'une faille apportée (`introduced`) est rouge : jamais pré-cochée.
          const brings = option.introduced.some((identifier) => warning.includes(identifier))
          const Icon = brings ? ShieldAlert : TriangleAlert
          return (
            <span key={warning} className={cn('flex items-start gap-2', brings ? 'text-danger' : 'text-warning')}>
              <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {warning}
            </span>
          )
        })}
        {option.edits.map((edit, index) => (
          <span key={index} className="flex flex-wrap items-center gap-x-1 font-mono">
            {editFile(edit)}
            {NBSP}:
            <VersionArrow from={edit.old} to={edit.new} />
          </span>
        ))}
        {option.edits.length === 0 && option.lockfile && (
          <span>
            aucun manifeste réécrit{NBSP}: <span className="font-mono">{option.lockfile}</span> seul
          </span>
        )}
      </span>
    </label>
  )
}
