import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2, RotateCcw, AlertTriangle } from 'lucide-react'
import { listTrashFiles, bulkRestoreFiles } from '../../api/files'
import type { FileResponse } from '../../types/api'
import { cn } from '../../lib/utils'
import { Spinner } from '../ui/Spinner'
import MediaLightbox from '../lightbox/MediaLightbox'
import { FileThumbnail } from './FileThumbnail'

const TRASH_DAYS = 30

function daysUntilPurge(trashedAt: string): number {
  const trashed = new Date(trashedAt).getTime()
  const elapsed = (Date.now() - trashed) / (1000 * 60 * 60 * 24)
  return Math.max(0, Math.ceil(TRASH_DAYS - elapsed))
}

function TrashTile({
  file,
  selected,
  onSelect,
  onClickImage,
}: {
  file: FileResponse
  selected: boolean
  onSelect: (id: string) => void
  onClickImage: () => void
}) {
  const days = file.trashed_at ? daysUntilPurge(file.trashed_at) : TRASH_DAYS

  return (
    <div className={cn('group relative rounded overflow-hidden bg-neutral-800 flex flex-col', selected && 'ring-2 ring-blue-500')}>
      {/* Thumbnail */}
      <div className="relative w-full aspect-square cursor-pointer" onClick={onClickImage}>
        <FileThumbnail
          file={file}
          imgClassName="w-full h-full object-cover"
          fallback={
            <div className="w-full h-full flex items-center justify-center bg-neutral-800">
              <Trash2 size={24} className="text-neutral-600" />
            </div>
          }
        />
        {/* Overlay on hover */}
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/40 transition-colors flex items-center justify-center opacity-0 group-hover:opacity-100">
          <span className="text-xs text-white font-medium px-2 text-center">{file.filename}</span>
        </div>
      </div>

      {/* Checkbox */}
      <div className={cn('absolute top-1.5 left-1.5 transition-opacity', selected ? 'opacity-100' : 'opacity-0 group-hover:opacity-100')}>
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onSelect(file.id)}
          onClick={(e) => e.stopPropagation()}
          className="w-4 h-4 rounded accent-blue-500 cursor-pointer"
        />
      </div>

      {/* Caption */}
      <div className="px-2 py-1.5 text-xs space-y-0.5">
        <p className="text-neutral-300 truncate">{file.filename}</p>
        <p className={cn('font-medium', days <= 3 ? 'text-red-400' : days <= 7 ? 'text-orange-400' : 'text-neutral-500')}>
          {days === 0 ? 'Purging soon' : `${days}d until deletion`}
        </p>
      </div>
    </div>
  )
}

export default function TrashView() {
  const queryClient = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [lightboxIndex, setLightboxIndex] = useState(-1)

  const { data, isLoading, error } = useQuery({
    queryKey: ['trash'],
    queryFn: () => listTrashFiles(),
  })

  const files = data?.items ?? []
  const total = data?.total ?? 0

  const { mutate: restore, isPending: isRestoring } = useMutation({
    mutationFn: (ids: string[]) => bulkRestoreFiles(ids),
    onSuccess: () => {
      setSelectedIds(new Set())
      queryClient.invalidateQueries({ queryKey: ['trash'] })
      queryClient.invalidateQueries({ queryKey: ['folder-files'] })
      queryClient.invalidateQueries({ queryKey: ['folder-trashed'] })
    },
  })

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selCount = selectedIds.size
  const allSelected = files.length > 0 && selCount === files.length

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Spinner size="lg" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-red-400 text-sm">Failed to load trash.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="shrink-0 border-b border-neutral-800 bg-neutral-900">
        <div className="flex items-center gap-3 px-4 py-3">
          <Trash2 size={16} className="text-neutral-400" />
          <h1 className="text-sm font-semibold text-neutral-100">Trash</h1>
          <span className="text-xs text-neutral-500">{total} {total === 1 ? 'item' : 'items'}</span>
          <div className="ml-auto flex items-center gap-2 text-xs text-neutral-500">
            <AlertTriangle size={12} />
            Files are permanently deleted after {TRASH_DAYS} days
          </div>
        </div>

        {/* Selection action bar */}
        {selCount > 0 && (
          <div className="flex items-center gap-3 px-4 py-2 bg-blue-950/60 border-t border-blue-800/50">
            <span className="text-xs text-blue-200 font-medium">
              {selCount} {selCount === 1 ? 'item' : 'items'} selected
            </span>
            <button
              onClick={() =>
                allSelected
                  ? setSelectedIds(new Set())
                  : setSelectedIds(new Set(files.map((f) => f.id)))
              }
              className="text-xs text-blue-300 hover:text-blue-100 underline underline-offset-2"
            >
              {allSelected ? 'Deselect all' : 'Select all'}
            </button>
            <button
              onClick={() => setSelectedIds(new Set())}
              className="text-xs text-neutral-400 hover:text-neutral-200"
            >
              Clear
            </button>
            <button
              onClick={() => restore(Array.from(selectedIds))}
              disabled={isRestoring}
              className="ml-auto flex items-center gap-1.5 rounded px-3 py-1 text-xs font-medium bg-green-700 hover:bg-green-600 text-white disabled:opacity-50 transition-colors"
            >
              <RotateCcw size={12} />
              {isRestoring ? 'Restoring…' : `Restore ${selCount}`}
            </button>
          </div>
        )}
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-y-auto bg-neutral-950 p-4">
        {files.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 gap-3">
            <Trash2 size={40} className="text-neutral-700" />
            <p className="text-neutral-500 text-sm">Trash is empty</p>
          </div>
        ) : (
          <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))' }}>
            {files.map((file, i) => (
              <TrashTile
                key={file.id}
                file={file}
                selected={selectedIds.has(file.id)}
                onSelect={toggleSelect}
                onClickImage={() => setLightboxIndex(i)}
              />
            ))}
          </div>
        )}
      </div>

      {lightboxIndex >= 0 && (
        <MediaLightbox
          files={files}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(-1)}
        />
      )}
    </div>
  )
}
