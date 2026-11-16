import { describe, expect, it } from 'vitest'
import { skyToPlot, stretchStamp } from './TargetMotion'

describe('[ui] target-motion view helpers', () => {
  it('[ui] sky offsets map east to the left and north up, centred, with the stated limit at the edges', () => {
    expect(skyToPlot(0, 0, 200, 2)).toEqual([100, 100])
    expect(skyToPlot(2, 0, 200, 2)).toEqual([0, 100]) // +east -> left edge
    expect(skyToPlot(0, 2, 200, 2)).toEqual([100, 0]) // +north -> top edge
    expect(skyToPlot(-1, -1, 200, 2)).toEqual([150, 150])
  })

  it('[ui] the stamp stretch keeps missing pixels missing, never darkens below background and is monotonic', () => {
    const g = stretchStamp([1, 1, 1, 2, 5, 50, Number.NaN, 1, 1])
    expect(Number.isNaN(g[6])).toBe(true)
    expect(g[0]).toBe(0)
    expect(g[5]).toBe(255)
    expect(g[3] <= g[4] && g[4] <= g[5]).toBe(true)
  })
})
