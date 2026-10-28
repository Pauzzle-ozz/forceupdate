import { readFileSync } from 'node:fs'
import openapiTS, { astToString } from 'openapi-typescript'
import { describe, expect, it } from 'vitest'

const root = `${import.meta.dirname}/../..`

describe('les types de l’API', () => {
  it('suivent src/forceupdate/web/openapi.json (sinon : npm run gen:api)', async () => {
    const schema = JSON.parse(readFileSync(`${root}/../src/forceupdate/web/openapi.json`, 'utf-8'))
    const generated = astToString(await openapiTS(schema))
    const committed = readFileSync(`${root}/src/api/schema.d.ts`, 'utf-8')
    const body = (text: string) => text.replace(/\r\n/g, '\n').replace(/^\/\*\*[\s\S]*?\*\/\n+/, '').trim()
    expect(body(committed)).toBe(body(generated))
  })
})
