import { describe, expect, it } from 'vitest'
import type { Blocker, Edit, Update } from '@/api/types'
import { VULNERABLE, planDocument } from '@/test/api'
import {
  blockedText,
  choose,
  commandDirectory,
  defaultSelection,
  editFile,
  editTarget,
  fixesSentence,
  isBlocked,
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

  it('une version que l’outil refusera : ses failles ne sont pas comptées non plus (E37)', () => {
    const jinja2 = update('.|PyPI|jinja2|2.10')
    const option = jinja2.options[jinja2.options.length - 1]
    const refused = { ...option, refused_by: ['flask 0.12.5'] }
    expect(fixesSentence(refused)?.text).toBe(`Corrigerait ${option.fixes.length} failles, mais flask 0.12.5 la fera refuser`)
    const report = structuredClone(VULNERABLE)
    report.projects[0].updates = report.projects[0].updates.map((item) =>
      item.id === jinja2.id ? { ...item, options: item.options.map((o) => (o.version === option.version ? refused : o)) } : item,
    )
    expect(recap(report, { [jinja2.id]: option.version }).fixed).toBe(0)
  })

  it('dit ce qui retient une version, ou la fera refuser, et la version qui l’accepte (E37)', () => {
    const blocker = (fields: Partial<Blocker>): Blocker => ({
      name: 'nodemon',
      version: '3.1.14',
      range: '^10.2.1',
      peer: false,
      companion: false,
      accepting: null,
      checked: false,
      held: true,
      ...fields,
    })
    const held = { held_by: ['nodemon 3.1.14'], refused_by: [] }
    expect(blockedText({ held_by: [], refused_by: [], blockers: [] })).toBeNull()
    expect(blockedText({ ...held, blockers: [] })).toBe("retenue par nodemon 3.1.14 : monter ce paquet d'abord")
    expect(blockedText({ ...held, blockers: [blocker({ accepting: '3.2.0', checked: true })] })).toBe(
      "retenue par nodemon 3.1.14 : monter d'abord nodemon en 3.2.0",
    )
    expect(blockedText({ ...held, blockers: [blocker({ checked: true })] })).toBe(
      "retenue par nodemon 3.1.14 : aucune de ses versions ne l'accepte",
    )
    const arq = blocker({ name: 'arq', version: '0.26.3', range: '<6,>=4.2.0', held: false, checked: true })
    expect(blockedText({ held_by: [], refused_by: ['arq 0.26.3'], blockers: [arq] })).toBe(
      "refusée à cause de arq 0.26.3 : aucune de ses versions ne l'accepte",
    )
    expect(blockedText({ held_by: [], refused_by: ['arq 0.26.3'], blockers: [{ ...arq, accepting: '0.38.0' }] })).toBe(
      'refusée à cause de arq 0.26.3 : monter aussi arq en 0.38.0',
    )
    expect(isBlocked({ held_by: [], refused_by: ['arq 0.26.3'] })).toBe(true)
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
