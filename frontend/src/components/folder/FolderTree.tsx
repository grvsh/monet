import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { ChevronRight, ChevronDown, FolderOpen, Folder, Link as LinkIcon } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { listRootLevelFolders, listChildFolders } from '../../api/folders'
import type { RootFolderResponse } from '../../types/api'
import FolderTreeNode from './FolderTreeNode'
import { Badge } from '../ui/Badge'
import { cn } from '../../lib/utils'

interface FolderTreeProps {
  rootFolder: RootFolderResponse
  descendantRoots?: RootFolderResponse[]
}

function sessionKey(id: string) {
  return `monet-tree-open-${id}`
}


export default function FolderTree({ rootFolder, descendantRoots = [] }: FolderTreeProps) {
  const navigate = useNavigate()
  const location = useLocation()

  const [open, setOpen] = useState(() => {
    try { return sessionStorage.getItem(sessionKey(rootFolder.id)) === 'true' } catch { return false }
  })

  // Always fetch root-level folders so we know child counts before expanding
  const { data: rootLevelFolders } = useQuery({
    queryKey: ['root-level-folders'],
    queryFn: listRootLevelFolders,
  })

  const rootFolderRecord = (rootLevelFolders ?? []).find(
    (f) => f.root_folder_id === rootFolder.id && f.path === ''
  )

  const hasSubfolders = descendantRoots.length > 0 || (rootFolderRecord?.child_folder_count ?? 1) > 0

  const { data: children } = useQuery({
    queryKey: ['folder-children', rootFolderRecord?.id],
    queryFn: () => listChildFolders(rootFolderRecord!.id),
    enabled: open && !!rootFolderRecord,
  })

  useEffect(() => {
    try { sessionStorage.setItem(sessionKey(rootFolder.id), String(open)) } catch { /* ignore */ }
  }, [open, rootFolder.id])

  const rootPath = `/browse/${rootFolder.id}`
  const isRootActive = decodeURIComponent(location.pathname) === rootPath

  return (
    <div>
      {/* Root folder row */}
      <div
        onClick={() => navigate(rootPath)}
        className={cn(
          'flex items-center gap-1.5 rounded px-2 py-1.5 text-sm cursor-pointer transition-colors select-none',
          isRootActive ? 'bg-blue-900/40 text-blue-100 ring-1 ring-inset ring-blue-700/40' : 'text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800'
        )}
      >
        {hasSubfolders ? (
          <button
            onClick={(e) => { e.stopPropagation(); setOpen(v => !v) }}
            className="flex-shrink-0 text-neutral-500 hover:text-neutral-300"
            aria-label={open ? 'Collapse' : 'Expand'}
          >
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : (
          <span className="flex-shrink-0 w-[14px]" />
        )}
        <button
          onClick={() => navigate(rootPath)}
          className="flex items-center gap-2 flex-1 min-w-0 text-left"
          title={rootFolder.path}
        >
          {open
            ? <FolderOpen size={14} className="shrink-0 text-blue-400" />
            : <Folder size={14} className="shrink-0 text-blue-400" />}
          <span className="truncate font-medium">{rootFolder.name}</span>
        </button>
        {rootFolderRecord && (rootFolderRecord.file_count > 0 || rootFolderRecord.child_folder_count > 0) && (
          <span
            title={`${rootFolderRecord.file_count} ${rootFolderRecord.file_count === 1 ? 'file' : 'files'} and ${rootFolderRecord.child_folder_count} ${rootFolderRecord.child_folder_count === 1 ? 'folder' : 'folders'}`}
            className="flex items-center gap-0.5 shrink-0"
          >
            {rootFolderRecord.file_count > 0 && (
              <Badge variant="neutral" className="tabular-nums">
                {rootFolderRecord.file_count}
              </Badge>
            )}
            {rootFolderRecord.child_folder_count > 0 && (
              <Badge variant="neutral" className="tabular-nums flex items-center gap-0.5">
                <Folder size={9} className="opacity-50" />
                {rootFolderRecord.child_folder_count}
              </Badge>
            )}
          </span>
        )}
      </div>

      {open && (
        <ul className="ml-4 border-l border-neutral-800 pl-2 mt-0.5 space-y-0.5">
          {/* Descendant root folders pinned at the top — navigate to their own root */}
          {descendantRoots.map((desc) => {
            const descPath = `/browse/${desc.id}`
            const isActive = decodeURIComponent(location.pathname) === descPath
            return (
              <li key={desc.id}>
                <button
                  onClick={() => navigate(descPath)}
                  title={desc.path}
                  className={cn(
                    'w-full flex items-center gap-2 rounded px-2 py-1.5 text-sm transition-colors select-none text-left',
                    isActive
                      ? 'bg-blue-900/40 text-blue-100 ring-1 ring-inset ring-blue-700/40'
                      : 'text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800'
                  )}
                >
                  <LinkIcon size={12} className="shrink-0 text-blue-400/70 flex-shrink-0" />
                  <span className="truncate flex-1 font-medium">{desc.name}</span>
                </button>
              </li>
            )
          })}

          {/* Regular subfolders */}
          {children?.map((folder) => (
            <li key={folder.id}>
              <FolderTreeNode folder={folder} rootPath={rootFolder.path} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
