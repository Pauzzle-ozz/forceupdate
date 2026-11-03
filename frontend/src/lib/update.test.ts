import { describe, expect, it } from 'vitest'
import type { Edit, Update } from '@/api/types'
import { VULNERABLE, planDocument } from '@/test/api'
import {
  choose,
  commandDirectory,
  defaultSelection,
  editFile,
  editTarget,
  fixesSentence,
  isCargoManifest,
  groups,
  lastLines,
  listText,
  parseDiff,
  plannedFiles,
  recap,
  toggle,
  updatesById,
} from './update'

const byId = updatesById(VULNERABLE)
const update = (id: string): Update => {
  const found = byId.get(id)
  if (!found) throw new Error(id)
  return found.update
}

describe('l’écran 5, prêt à afficher', () => {
  it('groupe les cartes par lockfile, dans l’ordre des lockfiles du projet', () => {
    expect(groups(VULNERABLE).map((group) => [group.lockfile, group.updates.map((u) => u.name)])).toEqual([
      ['package-lock.json', ['lodash']],
      ['requirements.txt', ['flask', 'jinja2', 'werkzeug']],
    ])
  })

  it('part de la sélection proposée, et la compte comme la maquette', () => {
    const selection = defaultSelection(VULNERABLE)
    expect(selection).toEqual({ '.|PyPI|flask': '0.12.5', '.|PyPI|jinja2|2.10': '2.11.3', '.|npm|lodash': '4.18.1' })
    expect(recap(VULNERABLE, selection)).toEqual({
      chosen: 3,
      total: 4,
      fixed: 9,
      vulnerabilities: 28,
      introduced: 0,
      majors: 0,
      files: ['package.json', 'requirements.in'],
      lockfiles: ['package-lock.json', 'requirements.txt'],
    })
  })

  it('au plus une option par paquet : choisir coche, décocher vide, recocher reprend la proposée', () => {
    const flask = update('.|PyPI|flask')
    let selection = choose({}, flask, '3.1.3')
    expect(selection).toEqual({ '.|PyPI|flask': '3.1.3' })
    expect(recap(VULNERABLE, selection).majors).toBe(1)
    selection = toggle(selection, flask, false)
    expect(selection).toEqual({})
    expect(toggle(selection, flask, true)).toEqual({ '.|PyPI|flask': '0.12.5' })
    // Rien de proposé (une majeure seulement) : la première option faisable.
    expect(toggle({}, update('.|PyPI|werkzeug|0.14.1'), true)).toEqual({ '.|PyPI|werkzeug|0.14.1': '3.1.9' })
  })

  it('dit ce que corrige une option', () => {
    const [patch, minor] = update('.|npm|lodash').options
    expect(fixesSentence(patch)).toEqual({ text: 'Corrige 4\u00a0failles sur 6, en laisse 2', full: false })
    expect(fixesSentence(minor)).toEqual({ text: 'Corrige les 6 failles', full: true })
  })

  it('une indirecte que son parent retiendra : ses failles ne sont pas comptées (session 37)', () => {
    const jinja2 = update('.|PyPI|jinja2|2.10')
    const option = jinja2.options[jinja2.options.length - 1]
    const held = { ...option, held_by: ['flask 0.12.5'] }
    expect(option.fixes.length).toBeGreaterThanOrEqual(2)
    expect(fixesSentence(held)?.text).toBe(`Corrigerait ${option.fixes.length} failles, mais flask 0.12.5 la retiendra`)
    const report = structuredClone(VULNERABLE)
    const project = report.projects[0]
    project.updates = project.updates.map((item) =>
      item.id === jinja2.id ? { ...item, options: item.options.map((o) => (o.version === option.version ? held : o)) } : item,
    )
    const selection = { [jinja2.id]: option.version }
    expect(recap(VULNERABLE, selection).fixed).toBe(option.fixes.length)
    expect(recap(report, selection).fixed).toBe(0)
  })

  it('dit quels fichiers touche une option du plan', () => {
    const plan = planDocument()
    expect(plannedFiles(plan, update('.|npm|lodash'), '4.18.1')).toEqual({
      files: ['package.json', 'package-lock.json'],
      lockfileOnly: false,
    })
    expect(plannedFiles(plan, update('.|PyPI|jinja2|2.10'), '2.11.3')).toEqual({
      files: ['requirements.txt'],
      lockfileOnly: true,
    })
  })

  it('découpe un diff unifié en lignes numérotées', () => {
    const { lines, added, removed } = parseDiff(planDocument().files[0].diff)
    expect([added, removed]).toEqual([1, 1])
    expect(lines[0]).toEqual({ kind: 'hunk', text: '@@ -3,6 +3,6 @@', old: null, new: null })
    expect(lines.slice(3, 6)).toEqual([
      { kind: 'context', text: '  "dependencies": {', old: 5, new: 5 },
      { kind: 'del', text: '    "lodash": "4.17.15"', old: 6, new: null },
      { kind: 'add', text: '    "lodash": "4.18.1"', old: null, new: 6 },
    ])
    expect(lines.at(-1)).toEqual({ kind: 'context', text: '}', old: 8, new: 8 })
    expect(parseDiff('@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n').lines.at(-1)).toEqual({
      kind: 'note',
      text: 'No newline at end of file',
      old: null,
      new: null,
    })
  })

  it('met en forme listes, dossiers et sorties d’outil', () => {
    expect(listText(['npm'])).toBe('npm')
    expect(listText(['npm', 'uv', 'pnpm'])).toBe('npm, uv et pnpm')
    expect(commandDirectory('C:/Projets/demo', '.')).toBe('C:/Projets/demo')
    expect(commandDirectory('C:/Projets/demo', 'web')).toBe('C:/Projets/demo/web')
    expect(commandDirectory('C:/Projets/demo', 'C:/Projets/autre')).toBe('C:/Projets/autre')
    const output = Array.from({ length: 20 }, (_, index) => `ligne ${index + 1}`).join('\n')
    expect(lastLines(`${output}\n\n`).split('\n')).toEqual(Array.from({ length: 12 }, (_, index) => `ligne ${index + 9}`))
  })

  it('dit où se réécrit une plage reprise d’ailleurs : catalogue pnpm ou workspace Cargo', () => {
    const edit = (file: string, kind: Edit['kind'] = 'catalog'): Edit => ({
      kind,
      file,
      location: null,
      old: '1.0',
      new: '1.2',
      override: null,
    })
    expect(editFile(edit('packages/web/package.json'))).toBe('packages/web/package.json (catalogue pnpm)')
    expect(editFile(edit('crates/app/Cargo.toml'))).toBe('crates/app/Cargo.toml (workspace Cargo)')
    expect(editFile(edit('Cargo.toml', 'dependency'))).toBe('Cargo.toml')
    expect(isCargoManifest('Cargo.toml')).toBe(true)
    expect(isCargoManifest('MyCargo.toml')).toBe(false)
    // Le fichier réécrit, pour le récapitulatif : pas le manifeste qui y renvoie.
    expect(editTarget(edit('packages/web/package.json'))).toBe('pnpm-workspace.yaml')
    expect(editTarget(edit('crates/app/Cargo.toml'))).toBe('Cargo.toml (racine du workspace)')
    expect(editTarget(edit('crates/app/Cargo.toml', 'dependency'))).toBe('crates/app/Cargo.toml')
  })
})
