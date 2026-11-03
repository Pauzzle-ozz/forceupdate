import { describe, expect, it } from 'vitest'
import type { Report } from '@/api/types'
import { VULNERABLE } from '@/test/api'
import {
  DEFAULT_SORT,
  NO_FILTERS,
  filterRows,
  highest,
  rows,
  runtimeLines,
  selectedCount,
  shownOption,
  sortRows,
} from './report'

const names = (list: { dependency: { name: string } }[]) => list.map((row) => row.dependency.name)

describe('les lignes du rapport', () => {
  const all = rows(VULNERABLE)

  it('une par déclaration, avec ses constats, sa mise à jour et sa gravité', () => {
    expect(all).toHaveLength(7)
    const flask = all.find((row) => row.dependency.name === 'flask')!
    expect(flask.findings.map((finding) => finding.kind)).toEqual([
      'vulnerable',
      'vulnerable',
      'vulnerable',
      'vulnerable',
      'outdated',
    ])
    expect(flask.severity).toBe('high')
    expect(flask.update?.selected).toBe('0.12.5')
    expect(flask.coverage).toBe('up-to-date')
  })

  it('dit ce qui n’a pas été vérifié : une indirecte sans « transitive » est seulement auditée', () => {
    const click = all.find((row) => row.dependency.name === 'click')!
    expect(click.findings).toEqual([])
    expect(click.severity).toBeNull()
    expect(click.coverage).toBe('audit-only')
  })

  it('trie par gravité dans l’ordre du rapport, puis les lignes sans constat', () => {
    expect(names(sortRows(all, DEFAULT_SORT))).toEqual([
      'flask',
      'jinja2',
      'lodash',
      'werkzeug',
      'click',
      'itsdangerous',
      'markupsafe',
    ])
    expect(names(sortRows(all, { key: 'name', descending: false })).slice(0, 3)).toEqual([
      'click',
      'flask',
      'itsdangerous',
    ])
    expect(names(sortRows(all, { key: 'severity', descending: false })).at(-1)).toBe('flask')
  })

  it('filtre par nom, directes, écosystème et type de constat', () => {
    expect(names(filterRows(all, { ...NO_FILTERS, query: 'SK' }))).toEqual(['flask'])
    expect(names(filterRows(all, { ...NO_FILTERS, directness: 'direct' }))).toEqual(['flask', 'lodash'])
    expect(names(filterRows(all, { ...NO_FILTERS, ecosystem: 'npm' }))).toEqual(['lodash'])
    expect(names(filterRows(all, { ...NO_FILTERS, kind: 'outdated' }))).toEqual(['flask', 'lodash'])
    expect(names(filterRows(all, { ...NO_FILTERS, kind: 'none' }))).toEqual(['click', 'itsdangerous', 'markupsafe'])
  })

  it('montre l’option pré-cochée, sinon la plus récente', () => {
    const updates = VULNERABLE.projects[0].updates
    const werkzeug = updates.find((update) => update.name === 'werkzeug')!
    expect(werkzeug.selected).toBeNull()
    expect(shownOption(werkzeug)?.version).toBe('3.1.9')
    expect(selectedCount(VULNERABLE)).toBe(3)
  })

  it('une ligne aux seuls constats « non concluant » a une gravité inconnue', () => {
    const report = structuredClone(VULNERABLE) as Report
    const project = report.projects[0]
    const lodash = project.dependencies.find((dependency) => dependency.name === 'lodash')!
    project.findings = project.findings
      .filter((finding) => finding.dependency?.name !== 'lodash')
      .concat({
        kind: 'inconclusive',
        severity: 'info',
        message: 'Failles non vérifiées.',
        dependency: lodash,
        current_version: '4.17.15',
        current_is_approximate: false,
        target_version: null,
        wanted_version: null,
        gap: null,
        identifiers: [],
        cvss_score: null,
        detail: null,
        url: null,
        eol: null,
        blocked: null,
      })
    const row = rows(report).find((each) => each.dependency.name === 'lodash')!
    expect(row.severity).toBeNull()
    expect(row.inconclusive).toBe(true)
    expect(names(sortRows(rows(report), DEFAULT_SORT)).slice(3, 5)).toEqual(['lodash', 'click'])
  })

  it('prend la gravité la plus haute', () => {
    expect(highest(['low', 'critical', 'medium'])).toBe('critical')
    expect(highest([])).toBeNull()
  })
})

describe("les runtimes d'un projet", () => {
  it("Rust a son nom (E34 : le rust-version d'un Cargo.toml)", () => {
    const project = {
      ...VULNERABLE.projects[0],
      runtimes: [
        {
          product: 'rust',
          version: '1.70',
          approximate: true,
          file: 'Cargo.toml',
          source: 'rust-version = "1.70"',
        },
      ],
    }
    expect(runtimeLines(project)).toEqual([
      { label: 'Rust', version: '1.70', approximate: true, files: ['Cargo.toml'] },
    ])
  })
})
