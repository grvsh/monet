import { Trash2, ArrowUp, HardDrive, Folder } from 'lucide-react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useGalleryStore } from '../../store/gallery'
import { cn } from '../../lib/utils'
import AddToAlbumMenu from '../album/AddToAlbumMenu'
import MediaTypeTabs from './MediaTypeTabs'

interface TypeCounts {
  image: number
  video: number
  audio: number
}

interface GalleryToolbarProps {
  typeCounts?: TypeCounts
  folderCount?: number
  allFileIds: string[]
  onDelete: () => void
  isDeleting: boolean
  canDeleteFromDisk?: boolean
  onDeleteFromDisk?: () => void
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


export default function GalleryToolbar({
  typeCounts,
  folderCount = 0,
  allFileIds,
  onDelete,
  isDeleting,
  canDeleteFromDisk = false,
  onDeleteFromDisk,
}: GalleryToolbarProps) {
  const sortField = useGalleryStore((s) => s.sortField)
  const sortOrder = useGalleryStore((s) => s.sortOrder)
  const mediaTypeFilter = useGalleryStore((s) => s.mediaTypeFilter)
  const setSortField = useGalleryStore((s) => s.setSortField)
  const setSortOrder = useGalleryStore((s) => s.setSortOrder)
  const setMediaTypeFilter = useGalleryStore((s) => s.setMediaTypeFilter)
  const selectedIds = useGalleryStore((s) => s.selectedIds)
  const clearSelection = useGalleryStore((s) => s.clearSelection)
  const selectAll = useGalleryStore((s) => s.selectAll)

  const selectionCount = selectedIds.size

  // Go-up navigation — available when inside a subfolder (path has > 2 segments after /)
  const navigate = useNavigate()
  const location = useLocation()
  const pathParts = location.pathname.split('/').filter(Boolean)
  // pathParts: ['browse', rootFolderId, ...subpath]
  const canGoUp = pathParts.length > 2
  const parentPath = canGoUp ? '/' + pathParts.slice(0, -1).join('/') : null

  function handleSortChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const opt = SORT_OPTIONS[parseInt(e.target.value, 10)]
    if (opt) {
      setSortField(opt.field)
      setSortOrder(opt.order)
    }
  }

  const currentSortIndex = SORT_OPTIONS.findIndex(
    (o) => o.field === sortField && o.order === sortOrder
  )

  return (
    <div className="shrink-0 border-b border-neutral-800 bg-neutral-900">
      <div className="flex items-center gap-3 px-4 py-2.5">

        {/* Media type tabs */}
        <MediaTypeTabs
          value={mediaTypeFilter}
          typeCounts={typeCounts}
          onChange={setMediaTypeFilter}
        />

        {folderCount > 0 && (
          <div className="flex items-center gap-1 bg-neutral-800 rounded px-2.5 py-1 shrink-0">
            <Folder size={12} className="text-neutral-400" />
            <span className="text-xs font-medium text-neutral-400">{folderCount}</span>
          </div>
        )}

        <div className="w-px h-4 bg-neutral-700 shrink-0" />

        {/* Go up — always visible, disabled at root */}
        <button
          onClick={() => canGoUp && navigate(parentPath!)}
          disabled={!canGoUp}
          className={cn(
            'flex items-center gap-1 text-xs shrink-0 transition-colors',
            canGoUp
              ? 'text-neutral-400 hover:text-neutral-200 cursor-pointer'
              : 'text-neutral-600 cursor-not-allowed'
          )}
          title="Go to parent folder"
        >
          <ArrowUp size={12} />
          Up
        </button>

        {/* Select all — always visible */}
        <button
          onClick={() => selectAll(allFileIds)}
          disabled={allFileIds.length === 0}
          className="text-xs text-neutral-400 hover:text-neutral-200 disabled:text-neutral-600 disabled:cursor-not-allowed shrink-0 transition-colors"
        >
          Select all
        </button>

        {/* Selection state — only when items are selected */}
        {selectionCount > 0 && (
          <>
            <button
              onClick={clearSelection}
              className="text-xs text-neutral-400 hover:text-neutral-200 shrink-0 transition-colors"
            >
              Clear selection
            </button>

            <AddToAlbumMenu />

            <button
              onClick={onDelete}
              disabled={isDeleting}
              title={canDeleteFromDisk
                ? 'Removes files from Monet'
                : 'Removes files from Monet. To delete files from disk, turn on Delete in Settings > Account.'}
              className="flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium bg-red-700 hover:bg-red-600 text-white disabled:opacity-50 transition-colors shrink-0"
            >
              <Trash2 size={12} />
              {isDeleting ? 'Trashing…' : `Trash (${selectionCount})`}
            </button>

            {canDeleteFromDisk && (
              <button
                onClick={onDeleteFromDisk}
                className="flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium bg-red-950 hover:bg-red-900 border border-red-700 text-red-300 hover:text-red-200 transition-colors shrink-0"
              >
                <HardDrive size={12} />
                Delete ({selectionCount})
              </button>
            )}
          </>
        )}

        {/* Sort — pushed to the right */}
        <div className="flex items-center gap-2 ml-auto shrink-0">
          <label htmlFor="sort-select" className="text-xs text-neutral-400">
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

      </div>
    </div>
  )
}
