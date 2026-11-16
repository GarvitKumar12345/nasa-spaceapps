// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api/client'
import type { GaiaFrameOverlay } from '../../api/types'
import { useGaiaStore } from '../../state/gaia'
import { useGaiaOverlay } from './ObservedGaia'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  useGaiaStore.getState().reset(null)
})

it('[ui] loads the overlay when the parent selects its dataset after the child mounts', async () => {
  useGaiaStore.getState().reset(null)
  const data = { dataset_id: 'ds-a', frame_id: 'f1', predictions: [] } as unknown as GaiaFrameOverlay
  const request = vi.spyOn(api, 'gaiaOverlay').mockResolvedValue(data)
  const { result } = renderHook(() => useGaiaOverlay('ds-a', 'f1', true))
  expect(request).not.toHaveBeenCalled()
  act(() => useGaiaStore.getState().reset('ds-a'))
  await waitFor(() => expect(result.current).toEqual({ status: 'ready', data }))
  expect(request).toHaveBeenCalledExactlyOnceWith('ds-a', 'f1')
})
