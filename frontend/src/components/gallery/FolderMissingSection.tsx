import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, FileQuestion, Trash2, X } from 'lucide-react'
import { listFolderMissingFiles } from '../../api/folders'
import { bulkTrashMissingFiles, bulkDismissMissingFiles } from '../../api/files'
import type { FileResponse } from '../../types/api'
import { FileThumbnail } from './FileThumbnail'

function MissingTile({ file, tileSize }: { file: FileResponse; tileSize: number }) {
  const queryClient = useQueryClient()

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['folder-missing'] })
    queryClient.invalidateQueries({ queryKey: ['folder-files'] })
    queryClient.invalidateQueries({ queryKey: ['trash'] })
    queryClient.invalidateQueries({ queryKey: ['folder-trashed'] })
  }

  const { mutate: moveToTrash, isPending: isTrashing } = useMutation({
    mutationFn: () => bulkTrashMissingFiles([file.id]),
    onSuccess: invalidate,
  })

  const { mutate: dismiss, isPending: isDismissing } = useMutation({
    mutationFn: () => bulkDismissMissingFiles([file.id]),
    onSuccess: invalidate,
  })

  const isPending = isTrashing || isDismissing

  return (
    <div className="group relative flex flex-col" style={{ width: tileSize }}>
      {/* Thumbnail */}
      <div
        className="relative flex-shrink-0 overflow-hidden rounded border-2 border-dashed border-amber-600/60 bg-neutral-800/60"
        style={{ height: tileSize }}
      >
        <FileThumbnail
          file={file}
          imgClassName="w-full h-full object-cover opacity-30 grayscale"
          fallback={
            <div className="w-full h-full flex items-center justify-center">
              <FileQuestion size={24} className="text-amber-600/60" />
            </div>
          }
        />

        {/* Action buttons on hover */}
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity bg-black/50">
          <button
            onClick={() => moveToTrash()}
            disabled={isPending}
            className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium bg-red-700/90 hover:bg-red-600 text-white disabled:opacity-50 w-28 justify-center"
          >
            <Trash2 size={11} />
            {isTrashing ? '…' : 'Move to Trash'}
          </button>
          <button
            onClick={() => dismiss()}
            disabled={isPending}
            className="flex items-center gap-1 rounded px-2 py-1 text-xs font-medium bg-neutral-700/90 hover:bg-neutral-600 text-white disabled:opacity-50 w-28 justify-center"
          >
            <X size={11} />
            {isDismissing ? '…' : 'Remove record'}
          </button>
        </div>
      </div>

      {/* Caption */}
      <div className="px-0.5 pt-1">
        <p className="text-xs text-amber-600/80 truncate leading-4">{file.filename}</p>
        <p className="text-xs text-neutral-600 leading-4">Not found on disk</p>
      </div>
    </div>
  )
}

interface FolderMissingSectionProps {
  folderId: string
  tileSize: number
  gap: number
}

export default function FolderMissingSection({ folderId, tileSize, gap }: FolderMissingSectionProps) {
  const [expanded, setExpanded] = useState(true)

  const { data: files = [] } = useQuery({
    queryKey: ['folder-missing', folderId],
    queryFn: () => listFolderMissingFiles(folderId),
  })

  if (files.length === 0) return null

  return (
    <div className="mt-4 border-t border-amber-800/40 pt-3">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 mb-2 text-xs font-medium text-amber-600/80 hover:text-amber-500 transition-colors"
      >
        {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <FileQuestion size={12} />
        Missing from disk ({files.length}) — moved or deleted outside the app
      </button>

      {expanded && (
        <div className="flex flex-wrap" style={{ gap }}>
          {files.map((file: FileResponse) => (
            <MissingTile key={file.id} file={file} tileSize={tileSize} />
          ))}
        </div>
      )}
    </div>
  )
}
