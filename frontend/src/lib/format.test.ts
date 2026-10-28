import { describe, expect, it } from 'vitest'
import { NBSP, basename, count, formatDuration, formatRelative, fr } from './format'

describe('règles françaises', () => {
  it('accorde le nombre', () => {
    expect(count(0, 'faille')).toBe(`0${NBSP}faille`)
    expect(count(1, 'faille')).toBe(`1${NBSP}faille`)
    expect(count(28, 'faille')).toBe(`28${NBSP}failles`)
    expect(count(2, 'plus récente', 'plus récentes')).toBe(`2${NBSP}plus récentes`)
    expect(count(5000, 'entrée')).toBe(`5${'\u202f'}000${NBSP}entrées`)
  })

  it('rend insécables les espaces avant la ponctuation haute et dans les guillemets', () => {
    expect(fr('Hors ligne : seulement le cache ; « non concluant » ?')).toBe(
      `Hors ligne${NBSP}: seulement le cache${NBSP}; «${NBSP}non concluant${NBSP}»${NBSP}?`,
    )
  })

  it('écrit les durées avec la virgule décimale', () => {
    expect(formatDuration(900)).toBe(`0,9${NBSP}s`)
    expect(formatDuration(12_400)).toBe(`12${NBSP}s`)
    expect(formatDuration(125_000)).toBe(`2${NBSP}min 05${NBSP}s`)
  })

  it('dit une date relative', () => {
    const now = Date.parse('2026-10-28T18:30:00Z')
    expect(formatRelative('2026-10-21T18:30:00Z', now)).toBe('il y a 7 jours')
    expect(formatRelative('2026-10-28T16:30:00Z', now)).toBe('il y a 2 heures')
    expect(formatRelative('2026-10-28T18:29:50Z', now)).toBe('maintenant')
  })

  it('prend le dernier élément d’un chemin', () => {
    expect(basename('C:/Projets/vulnerable')).toBe('vulnerable')
    expect(basename('C:/Projets/vulnerable/')).toBe('vulnerable')
    expect(basename('C:/')).toBe('C:/')
    expect(basename('/')).toBe('/')
    expect(basename('package.json')).toBe('package.json')
  })
})
