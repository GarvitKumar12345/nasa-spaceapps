import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import type { MaskBit } from '../api/types'
import { CAUTION_FLAGS, INFORMATIONAL_FLAGS, PHOTOMETRY_MASK_FLAGS, classMasks, flagClass, namesInWord, overlayColour } from './spherexFlags'

const REFERENCE = fileURLToPath(new URL('../../../backend/skyshift/providers/spherex/reference.py', import.meta.url))

function pythonTuple(source: string, name: string): string[] {
  const m = source.match(new RegExp(`${name}: tuple\\[str, \\.\\.\\.\\] = \\(([^)]*)\\)`, 's'))
  if (!m) throw new Error(`${name} not found in reference.py`)
  return [...m[1].matchAll(/"([A-Z_]+)"/g)].map((x) => x[1])
}

// ES v2.1 Table 16 bits as written in a real DR1 FLAGS header (bit 29 is documented but absent there).
const BITS: MaskBit[] = (
  [
    [0, 'TRANSIENT'], [1, 'OVERFLOW'], [2, 'SUR_ERROR'], [6, 'NONFUNC'], [7, 'DICHROIC'], [9, 'MISSING_DATA'], [10, 'HOT'], [11, 'COLD'],
    [12, 'FULLSAMPLE'], [14, 'PHANMISS'], [15, 'NONLINEAR'], [17, 'PERSIST'], [19, 'OUTLIER'], [20, 'CROSSTALK'], [21, 'SOURCE'], [22, 'GHOST'],
    [23, 'GHOST_FPA'], [24, 'GHOST_EXT'], [25, 'STREAK'], [26, 'BLOOM'], [27, 'SNOWBALL'], [28, 'HALO'], [31, 'SKYSHIFT_NO_COVERAGE'],
  ] as const
).map(([bit, name]) => ({ bit, name, description: '' }))

describe('[contracts] SPHEREx flag classes', () => {
  it('[contracts] match the backend reference lists (ES v2.1 Sect. 3.3) exactly', () => {
    const src = readFileSync(REFERENCE, 'utf-8')
    expect([...PHOTOMETRY_MASK_FLAGS]).toEqual(pythonTuple(src, 'PHOTOMETRY_MASK_FLAGS'))
    expect([...CAUTION_FLAGS]).toEqual(pythonTuple(src, 'CAUTION_FLAGS'))
    expect([...INFORMATIONAL_FLAGS]).toEqual(pythonTuple(src, 'INFORMATIONAL_FLAGS'))
  })

  it('[contracts] classify by name from the file, never by bit number', () => {
    expect(flagClass('BLOOM')).toBe('photometry_mask')
    expect(flagClass('OVERFLOW')).toBe('caution')
    expect(flagClass('SOURCE')).toBe('informational')
    expect(flagClass('PHANMISS')).toBe('other')
    expect(flagClass('SKYSHIFT_NO_COVERAGE')).toBe('coverage')
    // A file that moved SOURCE to another bit would still be classified by its name.
    const moved = classMasks([{ bit: 3, name: 'SOURCE', description: '' }, { bit: 5, name: 'HOT', description: '' }])
    expect(moved).toEqual({ photometry: 2 ** 5, caution: 0 })
  })

  it('[contracts] overlay colours: SOURCE-only and coverage-only words stay transparent; bit 31 does not break masking', () => {
    const masks = classMasks(BITS)
    expect(overlayColour(2 ** 21, masks)).toBeNull()
    expect(overlayColour(2 ** 31, masks)).toBeNull()
    expect(overlayColour(2 ** 26 + 2 ** 21, masks)?.[0]).toBe(255)
    expect(overlayColour(2 ** 31 + 2 ** 26, masks)).toEqual(overlayColour(2 ** 26, masks))
    expect(overlayColour(2 ** 1, masks)).toEqual([255, 196, 64, 64])
    expect(namesInWord(2 ** 31 + 2 ** 21 + 2 ** 1, BITS)).toEqual(['OVERFLOW', 'SOURCE', 'SKYSHIFT_NO_COVERAGE'])
  })
})
