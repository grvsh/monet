import { create } from 'zustand'

export interface RecentSearch {
  id: string
  query: string
  timestamp: string
}

const STORAGE_KEY = 'monet-recent-searches'
const MAX_SEARCHES = 20

function load(): RecentSearch[] {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v) return JSON.parse(v) as RecentSearch[]
  } catch { /* ignore */ }
  return []
}

function persist(searches: RecentSearch[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(searches))
  } catch { /* ignore */ }
}

interface RecentSearchesState {
  searches: RecentSearch[]
  add: (query: string) => void
  remove: (id: string) => void
  clear: () => void
}

export const useRecentSearchesStore = create<RecentSearchesState>((set) => ({
  searches: load(),
  add: (query) =>
    set((s) => {
      const filtered = s.searches.filter((r) => r.query !== query)
      const entry: RecentSearch = {
        id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`,
        query,
        timestamp: new Date().toISOString(),
      }
      const next = [entry, ...filtered].slice(0, MAX_SEARCHES)
      persist(next)
      return { searches: next }
    }),
  remove: (id) =>
    set((s) => {
      const next = s.searches.filter((r) => r.id !== id)
      persist(next)
      return { searches: next }
    }),
  clear: () =>
    set(() => {
      persist([])
      return { searches: [] }
    }),
}))
