import { useNavigate } from 'react-router-dom'
import { Folder } from 'lucide-react'
import type { FolderResponse } from '../../types/api'

const CAPTION_HEIGHT = 52

interface FolderTileProps {
  folder: FolderResponse
  size: number
}

export default function FolderTile({ folder, size }: FolderTileProps) {
  const navigate = useNavigate()

  return (
    <div
      style={{ width: size, height: size + CAPTION_HEIGHT, flexShrink: 0 }}
      onClick={() => navigate(`/browse/${folder.root_folder_id}/${folder.path}`)}
      className="cursor-pointer group flex flex-col"
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ')
          navigate(`/browse/${folder.root_folder_id}/${folder.path}`)
      }}
      aria-label={folder.name}
      title={folder.path}
    >
      {/* Icon area */}
      <div
        style={{ height: size }}
        className="flex-shrink-0 rounded bg-neutral-800 flex items-center justify-center
                   transition-all duration-150 group-hover:ring-2 group-hover:ring-blue-500"
      >
        <Folder
          size={Math.round(size * 0.38)}
          className="text-neutral-500 group-hover:text-neutral-400 transition-colors"
        />
      </div>

      {/* Caption */}
      <div className="px-0.5 pt-1 flex flex-col overflow-hidden">
        <p className="text-xs text-neutral-300 truncate leading-4 font-medium">
          {folder.name}
        </p>
        <p className="text-xs text-neutral-500 leading-4">
          {folder.child_folder_count > 0
            ? `${folder.file_count} files · ${folder.child_folder_count} folders`
            : `${folder.file_count} files`}
        </p>
      </div>
    </div>
  )
}
