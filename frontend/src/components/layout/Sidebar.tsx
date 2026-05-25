import { useRef, useState, useEffect, useCallback } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Settings, Image, Trash2 } from 'lucide-react'
import { cn } from '../../lib/utils'
import { useFolderTree } from '../../hooks/useFolderTree'
import FolderTree from '../folder/FolderTree'
import { Spinner } from '../ui/Spinner'
import type { RootFolderResponse } from '../../types/api'

interface RootFolderTreeProps {
  folders: RootFolderResponse[]
}

function RootFolderTree({ folders }: RootFolderTreeProps) {
  // Separate top-level roots (no parent) from descendant roots
  const topLevel = folders.filter((f) => !f.parent_root_id || !folders.find((p) => p.id === f.parent_root_id))
  const byParent = new Map<string, RootFolderResponse[]>()
  for (const f of folders) {
    if (f.parent_root_id && folders.find((p) => p.id === f.parent_root_id)) {
      const arr = byParent.get(f.parent_root_id) ?? []
      arr.push(f)
      byParent.set(f.parent_root_id, arr)
    }
  }

  return (
    <ul className="space-y-0.5 px-2">
      {topLevel.map((rf) => (
        <li key={rf.id}>
          <FolderTree
            rootFolder={rf}
            descendantRoots={byParent.get(rf.id) ?? []}
          />
        </li>
      ))}
    </ul>
  )
}

const MIN_WIDTH = 160
const MAX_WIDTH = 480
const DEFAULT_WIDTH = 260
const STORAGE_KEY = 'monet-sidebar-width'

function getSavedWidth(): number {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v) {
      const n = parseInt(v, 10)
      if (n >= MIN_WIDTH && n <= MAX_WIDTH) return n
    }
  } catch { /* ignore */ }
  return DEFAULT_WIDTH
}

export default function Sidebar() {
  const location = useLocation()
  const { visibleRootFolders, isLoading } = useFolderTree()

  const [width, setWidth] = useState(getSavedWidth)
  const dragging = useRef(false)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [])

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return
      setWidth(Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, e.clientX)))
    }
    const onMouseUp = () => {
      if (!dragging.current) return
      dragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      setWidth(w => {
        try { localStorage.setItem(STORAGE_KEY, String(w)) } catch { /* ignore */ }
        return w
      })
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [])

  return (
    <aside
      className="relative flex flex-col shrink-0 border-r border-neutral-800 bg-neutral-900 overflow-hidden"
      style={{ width }}
      aria-label="Sidebar"
    >
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 py-4 border-b border-neutral-800">
        <div className="w-7 h-7 rounded-md bg-blue-600 flex items-center justify-center">
          <Image size={16} className="text-white" />
        </div>
        <span className="text-base font-bold tracking-tight text-neutral-100">Monet</span>
      </div>

      {/* Folder tree */}
      <nav className="flex-1 overflow-y-auto py-2">
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Spinner size="sm" />
          </div>
        ) : visibleRootFolders.length === 0 ? (
          <div className="px-4 py-6 text-center">
            <p className="text-xs text-neutral-500">No folders configured.</p>
            <Link
              to="/settings"
              className="mt-1 text-xs text-blue-400 hover:text-blue-300 underline"
            >
              Go to Settings
            </Link>
          </div>
        ) : (
          <RootFolderTree folders={visibleRootFolders} />
        )}
      </nav>

      {/* Bottom: Trash + Settings */}
      <div className="border-t border-neutral-800 px-2 py-2 space-y-0.5">
        <Link
          to="/trash"
          className={cn(
            'flex items-center gap-2.5 rounded px-3 py-2 text-sm transition-colors',
            location.pathname === '/trash'
              ? 'bg-neutral-800 text-neutral-100'
              : 'text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800'
          )}
        >
          <Trash2 size={16} />
          <span>Trash</span>
        </Link>
        <Link
          to="/settings"
          className={cn(
            'flex items-center gap-2.5 rounded px-3 py-2 text-sm transition-colors',
            location.pathname.startsWith('/settings')
              ? 'bg-neutral-800 text-neutral-100'
              : 'text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800'
          )}
        >
          <Settings size={16} />
          <span>Settings</span>
        </Link>
      </div>

      {/* Resize handle */}
      <div
        onMouseDown={onMouseDown}
        className="absolute top-0 right-0 h-full w-1 cursor-col-resize hover:bg-blue-500/40 transition-colors"
        aria-hidden
      />
    </aside>
  )
}
