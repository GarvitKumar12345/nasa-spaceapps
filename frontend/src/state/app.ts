/* App-level store: current section (synced with location.hash), API health, and
 * a polite live-region message for screen readers. */
import { create } from 'zustand'
import { api, describeError } from '../api/client'
import type { HealthStatus } from '../api/contracts.gen'

export type Section = 'observatory' | 'motion' | 'evidence' | 'methods' | 'blinkir'
export const SECTIONS: { id: Section; label: string }[] = [
  { id: 'observatory', label: 'Observatory' },
  { id: 'motion', label: 'Motion lab' },
  { id: 'evidence', label: 'Evidence notebook' },
  { id: 'methods', label: 'Methods' },
  { id: 'blinkir', label: 'BlinkIR' },
]

export type ApiState =
  | { kind: 'checking' }
  | { kind: 'online'; health: HealthStatus }
  | { kind: 'offline'; message: string }

interface AppState {
  section: Section
  api: ApiState
  liveMessage: string
  setSection: (section: Section) => void
  announce: (message: string) => void
  checkApi: () => Promise<void>
}

export function sectionFromHash(hash: string): Section {
  const id = hash.replace(/^#\/?/, '').split(/[/?]/)[0]
  return (SECTIONS.find((s) => s.id === id)?.id ?? 'observatory') as Section
}

export const useAppStore = create<AppState>((set) => ({
  section: typeof window === 'undefined' ? 'observatory' : sectionFromHash(window.location.hash),
  api: { kind: 'checking' },
  liveMessage: '',
  setSection: (section) => {
    if (typeof window !== 'undefined' && sectionFromHash(window.location.hash) !== section) {
      window.location.hash = `#/${section}`
    }
    set({ section })
  },
  announce: (message) => {
    // Clear first so repeated identical messages are re-announced.
    set({ liveMessage: '' })
    setTimeout(() => set({ liveMessage: message }), 30)
  },
  checkApi: async () => {
    set({ api: { kind: 'checking' } })
    try {
      const health = await api.health()
      set({ api: { kind: 'online', health } })
    } catch (error) {
      set({ api: { kind: 'offline', message: describeError(error) } })
    }
  },
}))

if (typeof window !== 'undefined') {
  window.addEventListener('hashchange', () => {
    const section = sectionFromHash(window.location.hash)
    if (useAppStore.getState().section !== section) useAppStore.setState({ section })
  })
}
