/* SPHEREx pixel-flag classes for display (SPHEREx Explanatory Supplement v2.1, Sect. 3.3).
 * Bit numbers and names always come from the file (frame.mask_bits); this module only maps a
 * documented flag NAME to a display class. Kept identical to backend/skyshift/providers/spherex/
 * reference.py by spherexFlags.test.ts. */
import type { MaskBit } from '../api/types'

/** ES Sect. 3.3 "Flags for masking pixels for photometry calculations". */
export const PHOTOMETRY_MASK_FLAGS = ['SUR_ERROR', 'NONFUNC', 'MISSING_DATA', 'HOT', 'COLD', 'NONLINEAR', 'PERSIST', 'BLOOM', 'SNOWBALL', 'HALO', 'SATELLITE_HALO'] as const
/** ES Sect. 3.3 CONTAINS_BAD_PIXEL warning flags not in the photometry-mask list. */
export const CAUTION_FLAGS = ['TRANSIENT', 'OVERFLOW', 'DICHROIC', 'CROSSTALK', 'GHOST', 'GHOST_FPA', 'GHOST_EXT', 'STREAK'] as const
/** ES Table 16: FULLSAMPLE is "purely informational"; SOURCE marks a known source. */
export const INFORMATIONAL_FLAGS = ['SOURCE', 'FULLSAMPLE'] as const

export type FlagClass = 'photometry_mask' | 'caution' | 'informational' | 'other' | 'coverage'

export function flagClass(name: string): FlagClass {
  if (name === 'SKYSHIFT_NO_COVERAGE') return 'coverage'
  if ((PHOTOMETRY_MASK_FLAGS as readonly string[]).includes(name)) return 'photometry_mask'
  if ((CAUTION_FLAGS as readonly string[]).includes(name)) return 'caution'
  if ((INFORMATIONAL_FLAGS as readonly string[]).includes(name)) return 'informational'
  return 'other'
}

export const FLAG_CLASS_LABEL: Record<FlagClass, string> = {
  photometry_mask: 'masked for photometry',
  caution: 'warning',
  informational: 'informational',
  other: 'documented, unclassified',
  coverage: 'outside cutout',
}

/** Bit masks of the photometry-mask and caution classes for one frame's own bit definitions. */
export function classMasks(bits: MaskBit[]): { photometry: number; caution: number } {
  let photometry = 0
  let caution = 0
  for (const b of bits) {
    if (b.bit < 0 || b.bit > 31) continue
    const v = 2 ** b.bit
    const c = flagClass(b.name)
    if (c === 'photometry_mask') photometry += v
    else if (c === 'caution') caution += v
  }
  return { photometry, caution }
}

/** Flag names set in a pixel word, using the frame's own definitions. */
export function namesInWord(word: number, bits: MaskBit[]): string[] {
  return bits.filter((b) => b.bit >= 0 && b.bit <= 31 && Math.floor(word / 2 ** b.bit) % 2 === 1).map((b) => b.name)
}

/** Overlay colour for a flag word: photometry-mask flags (red-orange) over caution flags (amber). */
export function overlayColour(word: number, masks: { photometry: number; caution: number }): [number, number, number, number] | null {
  // Unsigned AND without sign problems for bit 31: use >>> 0.
  if (((word & masks.photometry) >>> 0) !== 0) return [255, 92, 64, 96]
  if (((word & masks.caution) >>> 0) !== 0) return [255, 196, 64, 64]
  return null
}
