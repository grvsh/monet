import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { ChevronRight, ChevronDown, Folder, FolderOpen } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { listChildFolders } from '../../api/folders'
import type { FolderResponse } from '../../types/api'
import { cn } from '../../lib/utils'
import { Badge } from '../ui/Badge'

interface FolderTreeNodeProps {
  folder: FolderResponse
  rootPath: string
  depth?: number
}

function sessionKey(id: string) {
  return `monet-tree-open-${id}`
}

export default function FolderTreeNode({ folder, rootPath, depth = 0 }: FolderTreeNodeProps) {
  const navigate = useNavigate()
  const location = useLocation()

  const [open, setOpen] = useState(() => {
    try {
      return sessionStorage.getItem(sessionKey(folder.id)) === 'true'
    } catch {
      return false
    }
  })

  const hasChildren = folder.child_folder_count > 0

  const { data: children } = useQuery({
    queryKey: ['folder-children', folder.id],
    queryFn: () => listChildFolders(folder.id),
    enabled: open && hasChildren,
  })

  useEffect(() => {
    try {
      sessionStorage.setItem(sessionKey(folder.id), String(open))
    } catch {
      // ignore
    }
  }, [open, folder.id])

  const folderPath = `/browse/${folder.root_folder_id}/${folder.path}`
  const isActive = location.pathname === folderPath

  function handleNavigate() {
    navigate(folderPath)
  }

  return (
    <div>
      <div
        className={cn(
          'flex items-center gap-1.5 rounded px-2 py-1.5 text-sm cursor-pointer transition-colors select-none',
          isActive
            ? 'bg-neutral-800 text-neutral-100'
            : 'text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800'
        )}
      >
        {/* Expand/collapse button or spacer */}
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation()
              setOpen((v) => !v)
            }}
            className="flex-shrink-0 text-neutral-500 hover:text-neutral-300"
            aria-label={open ? 'Collapse' : 'Expand'}
          >
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        ) : (
          <span className="w-[13px] shrink-0" />
        )}

        {/* Icon + name */}
        <button
          onClick={handleNavigate}
          title={rootPath.replace(/\/$/, '') + '/' + folder.path}
          className="flex items-center gap-2 flex-1 min-w-0 text-left"
        >
          {open ? (
            <FolderOpen size={13} className="shrink-0 text-neutral-500" />
          ) : (
            <Folder size={13} className="shrink-0 text-neutral-500" />
          )}
          <span className="truncate">{folder.name}</span>
        </button>

        {/* File count badge */}
        {folder.file_count > 0 && (
          <Badge variant="neutral" className="shrink-0 tabular-nums">
            {folder.file_count}
          </Badge>
        )}
      </div>

      {/* Children */}
      {open && children && children.length > 0 && (
        <ul
          className={cn(
            'border-l border-neutral-800 pl-2 mt-0.5 space-y-0.5',
            depth < 2 ? 'ml-4' : 'ml-3'
          )}
        >
          {children.map((child) => (
            <li key={child.id}>
              <FolderTreeNode folder={child} rootPath={rootPath} depth={depth + 1} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
