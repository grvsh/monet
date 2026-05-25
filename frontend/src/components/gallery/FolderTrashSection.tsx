import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, RotateCcw, Trash2 } from 'lucide-react'
import { listFolderTrashedFiles } from '../../api/folders'
import { bulkRestoreFiles } from '../../api/files'
import type { FileResponse } from '../../types/api'
import { cn } from '../../lib/utils'

const TRASH_DAYS = 30

function daysUntilPurge(trashedAt: string): number {
  const elapsed = (Date.now() - new Date(trashedAt).getTime()) / (1000 * 60 * 60 * 24)
  return Math.max(0, Math.ceil(TRASH_DAYS - elapsed))
}

function TrashedTile({ file, tileSize }: { file: FileResponse; tileSize: number }) {
  const queryClient = useQueryClient()
  const days = file.trashed_at ? daysUntilPurge(file.trashed_at) : TRASH_DAYS

  const { mutate: restore, isPending } = useMutation({
    mutationFn: () => bulkRestoreFiles([file.id]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['folder-trashed'] })
      queryClient.invalidateQueries({ queryKey: ['folder-files'] })
      queryClient.invalidateQueries({ queryKey: ['trash'] })
    },
  })

  return (
    <div className="group relative flex flex-col" style={{ width: tileSize }}>
      <div
        className="relative flex-shrink-0 overflow-hidden rounded opacity-50 group-hover:opacity-70 transition-opacity"
        style={{ height: tileSize }}
      >
        {file.has_thumbnail ? (
          <img
            src={file.thumbnail_url}
            alt={file.filename}
            loading="lazy"
            draggable={false}
            className="w-full h-full object-cover grayscale"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center bg-neutral-800">
            <Trash2 size={20} className="text-neutral-600" />
          </div>
        )}

        {/* Restore button on hover */}
        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={() => restore()}
            disabled={isPending}
            className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium bg-green-700/90 hover:bg-green-600 text-white disabled:opacity-50 transition-colors"
          >
            <RotateCcw size={11} />
            {isPending ? '…' : 'Restore'}
          </button>
        </div>
      </div>

      {/* Caption */}
      <div className="px-0.5 pt-1">
        <p className="text-xs text-neutral-600 truncate leading-4">{file.filename}</p>
        <p className={cn('text-xs leading-4', days <= 3 ? 'text-red-500' : days <= 7 ? 'text-orange-500' : 'text-neutral-600')}>
          {days === 0 ? 'Purging soon' : `${days}d left`}
        </p>
      </div>
    </div>
  )
}

interface FolderTrashSectionProps {
  folderId: string
  tileSize: number
  gap: number
}

export default function FolderTrashSection({ folderId, tileSize, gap }: FolderTrashSectionProps) {
  const [expanded, setExpanded] = useState(true)

  const { data: files = [] } = useQuery({
    queryKey: ['folder-trashed', folderId],
    queryFn: () => listFolderTrashedFiles(folderId),
  })

  if (files.length === 0) return null

  return (
    <div className="mt-4 border-t border-neutral-800 pt-3">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 mb-2 text-xs font-medium text-neutral-500 hover:text-neutral-300 transition-colors"
      >
        {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <Trash2 size={12} />
        Recently Deleted ({files.length})
      </button>

      {expanded && (
        <div className="flex flex-wrap" style={{ gap }}>
          {files.map((file: FileResponse) => (
            <TrashedTile key={file.id} file={file} tileSize={tileSize} />
          ))}
        </div>
      )}
    </div>
  )
}
