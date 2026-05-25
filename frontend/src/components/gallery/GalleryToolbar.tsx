import { Trash2 } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useGalleryStore } from '../../store/gallery'
import { bulkDeleteFiles } from '../../api/files'
import { cn } from '../../lib/utils'

interface GalleryToolbarProps {
  totalCount: number
  allFileIds: string[]
}

type SortOption = {
  label: string
  field: 'taken_at' | 'filename' | 'size_bytes'
  order: 'asc' | 'desc'
}

const SORT_OPTIONS: SortOption[] = [
  { label: 'Date ↓', field: 'taken_at', order: 'desc' },
  { label: 'Date ↑', field: 'taken_at', order: 'asc' },
  { label: 'Name', field: 'filename', order: 'asc' },
  { label: 'Size', field: 'size_bytes', order: 'desc' },
]

type MediaTab = { label: string; value: 'all' | 'image' | 'video' | 'audio' }

const MEDIA_TABS: MediaTab[] = [
  { label: 'All', value: 'all' },
  { label: 'Photos', value: 'image' },
  { label: 'Videos', value: 'video' },
  { label: 'Audio', value: 'audio' },
]

export default function GalleryToolbar({ totalCount, allFileIds }: GalleryToolbarProps) {
  const sortField = useGalleryStore((s) => s.sortField)
  const sortOrder = useGalleryStore((s) => s.sortOrder)
  const mediaTypeFilter = useGalleryStore((s) => s.mediaTypeFilter)
  const setSortField = useGalleryStore((s) => s.setSortField)
  const setSortOrder = useGalleryStore((s) => s.setSortOrder)
  const setMediaTypeFilter = useGalleryStore((s) => s.setMediaTypeFilter)
  const selectedIds = useGalleryStore((s) => s.selectedIds)
  const clearSelection = useGalleryStore((s) => s.clearSelection)
  const selectAll = useGalleryStore((s) => s.selectAll)

  const queryClient = useQueryClient()
  const { mutate: deleteSelected, isPending: isDeleting } = useMutation({
    mutationFn: () => bulkDeleteFiles(Array.from(selectedIds)),
    onSuccess: () => {
      clearSelection()
      queryClient.invalidateQueries({ queryKey: ['folder-files'] })
      queryClient.invalidateQueries({ queryKey: ['folder-trashed'] })
      queryClient.invalidateQueries({ queryKey: ['trash'] })
    },
  })

  function handleSortChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const opt = SORT_OPTIONS[parseInt(e.target.value, 10)]
    if (opt) {
      setSortField(opt.field)
      setSortOrder(opt.order)
    }
  }

  function handleDelete() {
    const count = selectedIds.size
    if (window.confirm(`Move ${count} ${count === 1 ? 'file' : 'files'} to Trash? Files will be permanently deleted after 30 days.`)) {
      deleteSelected()
    }
  }

  const currentSortIndex = SORT_OPTIONS.findIndex(
    (o) => o.field === sortField && o.order === sortOrder
  )

  const selectionCount = selectedIds.size
  const allSelected = allFileIds.length > 0 && selectionCount === allFileIds.length

  return (
    <div className="shrink-0 border-b border-neutral-800 bg-neutral-900">
      {/* Main toolbar */}
      <div className="flex items-center gap-4 px-4 py-2.5">
        {/* Media type tabs */}
        <div className="flex items-center gap-1 bg-neutral-800 rounded p-0.5">
          {MEDIA_TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => setMediaTypeFilter(tab.value)}
              className={cn(
                'px-3 py-1 rounded text-xs font-medium transition-colors',
                mediaTypeFilter === tab.value
                  ? 'bg-neutral-700 text-neutral-100'
                  : 'text-neutral-400 hover:text-neutral-200'
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Sort selector */}
        <div className="flex items-center gap-2">
          <label htmlFor="sort-select" className="text-xs text-neutral-400 shrink-0">
            Sort:
          </label>
          <select
            id="sort-select"
            value={currentSortIndex === -1 ? 0 : currentSortIndex}
            onChange={handleSortChange}
            className="rounded border border-neutral-700 bg-neutral-800 px-2 py-1 text-xs text-neutral-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            {SORT_OPTIONS.map((opt, i) => (
              <option key={i} value={i}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* File count */}
        <span className="ml-auto text-xs text-neutral-500 shrink-0">
          {totalCount.toLocaleString()} {totalCount === 1 ? 'item' : 'items'}
        </span>
      </div>

      {/* Selection action bar — only visible when items are selected */}
      {selectionCount > 0 && (
        <div className="flex items-center gap-3 px-4 py-2 bg-blue-950/60 border-t border-blue-800/50">
          <span className="text-xs text-blue-200 font-medium">
            {selectionCount} {selectionCount === 1 ? 'item' : 'items'} selected
          </span>

          <button
            onClick={() => allSelected ? clearSelection() : selectAll(allFileIds)}
            className="text-xs text-blue-300 hover:text-blue-100 underline underline-offset-2"
          >
            {allSelected ? 'Deselect all' : 'Select all'}
          </button>

          <button
            onClick={clearSelection}
            className="text-xs text-neutral-400 hover:text-neutral-200"
          >
            Clear
          </button>

          <button
            onClick={handleDelete}
            disabled={isDeleting}
            className="ml-auto flex items-center gap-1.5 rounded px-3 py-1 text-xs font-medium bg-red-700 hover:bg-red-600 text-white disabled:opacity-50 transition-colors"
          >
            <Trash2 size={12} />
            {isDeleting ? 'Moving…' : `Move to Trash (${selectionCount})`}
          </button>
        </div>
      )}
    </div>
  )
}
