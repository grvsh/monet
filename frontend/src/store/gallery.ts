import { create } from 'zustand'

type SortField = 'taken_at' | 'filename' | 'size_bytes'
type SortOrder = 'asc' | 'desc'
type MediaTypeFilter = 'all' | 'image' | 'video' | 'audio'

interface GalleryState {
  selectedFileId: string | null
  lightboxIndex: number
  sortField: SortField
  sortOrder: SortOrder
  mediaTypeFilter: MediaTypeFilter
  selectedIds: Set<string>
  currentFolderId: string | null
  currentAlbumId: string | null
  setSelectedFile: (id: string | null) => void
  setLightboxIndex: (i: number) => void
  setSortField: (f: SortField) => void
  setSortOrder: (o: SortOrder) => void
  setMediaTypeFilter: (t: MediaTypeFilter) => void
  toggleSelection: (id: string) => void
  clearSelection: () => void
  selectAll: (ids: string[]) => void
  selectRange: (ids: string[]) => void
  setCurrentFolderId: (id: string | null) => void
  setCurrentAlbumId: (id: string | null) => void
}

export const useGalleryStore = create<GalleryState>((set) => ({
  selectedFileId: null,
  lightboxIndex: -1,
  sortField: 'taken_at',
  sortOrder: 'desc',
  mediaTypeFilter: 'all',
  selectedIds: new Set<string>(),
  currentFolderId: null,
  currentAlbumId: null,
  setSelectedFile: (id) => set({ selectedFileId: id }),
  setLightboxIndex: (i) => set({ lightboxIndex: i }),
  setSortField: (f) => set({ sortField: f }),
  setSortOrder: (o) => set({ sortOrder: o }),
  setMediaTypeFilter: (t) => set({ mediaTypeFilter: t }),
  toggleSelection: (id) =>
    set((s) => {
      const next = new Set(s.selectedIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { selectedIds: next }
    }),
  clearSelection: () => set({ selectedIds: new Set<string>() }),
  selectAll: (ids) => set({ selectedIds: new Set(ids) }),
  selectRange: (ids) =>
    set((s) => ({ selectedIds: new Set([...s.selectedIds, ...ids]) })),
  setCurrentFolderId: (id) => set({ currentFolderId: id }),
  setCurrentAlbumId: (id) => set({ currentAlbumId: id }),
}))
