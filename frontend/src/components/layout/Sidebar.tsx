import { useRef, useState, useEffect, useCallback } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Settings, Trash2, FolderOpen, Images, Search, X, Folder, AlertTriangle, Clock, Users } from 'lucide-react'
import { useQueryClient, useQuery } from '@tanstack/react-query'
import { format, isToday, isYesterday } from 'date-fns'
import { cn } from '../../lib/utils'
import { useAuthStore } from '../../store/auth'
import { useFolderTree } from '../../hooks/useFolderTree'
import FolderTree from '../folder/FolderTree'
import AlbumList from '../album/AlbumList'
import { listAlbums } from '../../api/albums'
import { searchFolders } from '../../api/folders'
import { Spinner } from '../ui/Spinner'
import { Badge } from '../ui/Badge'
import type { RootFolderResponse } from '../../types/api'
import { useRecentSearchesStore } from '../../store/recentSearches'


interface RootFolderTreeProps {
  folders: RootFolderResponse[]
}

function RootFolderTree({ folders }: RootFolderTreeProps) {
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

interface SearchInputProps {
  value: string
  onChange: (v: string) => void
  placeholder: string
}

function SearchInput({ value, onChange, placeholder }: SearchInputProps) {
  return (
    <div className="relative mx-2 mb-1">
      <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded border border-neutral-700 bg-neutral-800 pl-7 pr-6 py-1 text-xs text-neutral-200 placeholder-neutral-600 focus:outline-none focus:ring-1 focus:ring-blue-500/60 focus:border-blue-500/60"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-500 hover:text-neutral-300"
          aria-label="Clear search"
        >
          <X size={11} />
        </button>
      )}
    </div>
  )
}

function FolderSearchResults({
  query,
  rootFolders,
}: {
  query: string
  rootFolders: RootFolderResponse[]
}) {
  const navigate = useNavigate()
  const location = useLocation()

  const rootNameById = new Map(rootFolders.map((r) => [r.id, r.name]))

  const { data, isFetching } = useQuery({
    queryKey: ['folder-search', query],
    queryFn: () => searchFolders(query),
    enabled: query.length > 0,
    staleTime: 10_000,
  })

  if (isFetching) {
    return (
      <div className="flex justify-center py-6">
        <Spinner size="sm" />
      </div>
    )
  }

  if (!data?.length) {
    return (
      <p className="px-4 py-4 text-xs text-neutral-500 text-center">
        No folders match "{query}".
      </p>
    )
  }

  return (
    <ul className="space-y-0.5 px-2">
      {data.map((folder) => {
        const href = `/browse/${folder.root_folder_id}${folder.path ? '/' + folder.path : ''}`
        const isActive = decodeURIComponent(location.pathname) === href

        // Build full display path: "RootName / seg1 / seg2 / folderName"
        const rootName = rootNameById.get(folder.root_folder_id) ?? ''
        const segments = folder.path ? folder.path.split('/') : []
        const fullParts = rootName ? [rootName, ...segments] : segments
        const displayPath = fullParts.join(' / ')

        return (
          <li key={folder.id}>
            <button
              type="button"
              onClick={() => navigate(href)}
              className={cn(
                'w-full flex items-start gap-2 rounded px-2 py-1.5 text-left transition-colors',
                isActive
                  ? 'bg-neutral-800 text-neutral-100'
                  : 'text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800'
              )}
            >
              <Folder size={14} className="shrink-0 mt-0.5 text-blue-400" />
              <span className="text-xs leading-snug break-all flex-1">{displayPath}</span>
              {(folder.file_count > 0 || folder.child_folder_count > 0) && (
                <span
                  title={`${folder.file_count} ${folder.file_count === 1 ? 'file' : 'files'} and ${folder.child_folder_count} ${folder.child_folder_count === 1 ? 'folder' : 'folders'}`}
                  className="flex items-center gap-0.5 shrink-0 self-start mt-0.5"
                >
                  {folder.file_count > 0 && (
                    <Badge variant="neutral" className="tabular-nums">
                      {folder.file_count}
                    </Badge>
                  )}
                  {folder.child_folder_count > 0 && (
                    <Badge variant="neutral" className="tabular-nums flex items-center gap-0.5">
                      <Folder size={9} className="opacity-50" />
                      {folder.child_folder_count}
                    </Badge>
                  )}
                </span>
              )}
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function formatSearchTime(isoString: string): string {
  const date = new Date(isoString)
  if (isToday(date)) return `Today at ${format(date, 'h:mm a')}`
  if (isYesterday(date)) return `Yesterday at ${format(date, 'h:mm a')}`
  return format(date, 'MMM d, yyyy · h:mm a')
}

function RecentSearchesPanel() {
  const navigate = useNavigate()
  const { searches, remove, clear } = useRecentSearchesStore()

  if (searches.length === 0) {
    return (
      <p className="px-4 py-6 text-xs text-neutral-500 text-center">
        No recent searches yet.
      </p>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 pb-1.5 shrink-0">
        <span className="text-xs text-neutral-500">{searches.length} search{searches.length !== 1 ? 'es' : ''}</span>
        <button
          type="button"
          onClick={clear}
          className="text-xs text-neutral-600 hover:text-neutral-400 transition-colors"
        >
          Clear all
        </button>
      </div>
      <ul className="space-y-0.5 px-2 overflow-y-auto">
        {searches.map((s) => (
          <li key={s.id} className="group flex items-start gap-1.5 rounded px-2 py-1.5 hover:bg-neutral-800 transition-colors">
            <button
              type="button"
              onClick={() => navigate(`/search?q=${encodeURIComponent(s.query)}`)}
              className="flex items-start gap-2 flex-1 min-w-0 text-left"
            >
              <Search size={12} className="shrink-0 mt-0.5 text-neutral-500" />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-neutral-200 truncate">{s.query}</p>
                <p className="text-xs text-neutral-600 mt-0.5">{formatSearchTime(s.timestamp)}</p>
              </div>
            </button>
            <button
              type="button"
              onClick={() => remove(s.id)}
              title="Remove"
              className="shrink-0 mt-0.5 text-neutral-700 hover:text-neutral-400 opacity-0 group-hover:opacity-100 transition-opacity"
              aria-label="Remove search"
            >
              <X size={12} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

const MIN_WIDTH = 160
const MAX_WIDTH = 480
const DEFAULT_WIDTH = 260
const STORAGE_KEY = 'monet-sidebar-width'
const TAB_KEY = 'monet-sidebar-tab'

type SidebarTab = 'folders' | 'albums' | 'searches'

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

function getSavedTab(): SidebarTab {
  try {
    const v = localStorage.getItem(TAB_KEY)
    if (v === 'albums') return 'albums'
    if (v === 'searches') return 'searches'
  } catch { /* ignore */ }
  return 'folders'
}

export default function Sidebar() {
  const location = useLocation()
  const { visibleRootFolders, isLoading } = useFolderTree()

  const currentUser = useAuthStore((s) => s.user)
  const [width, setWidth] = useState(getSavedWidth)
  const [activeTab, setActiveTab] = useState<SidebarTab>(getSavedTab)
  const [folderSearch, setFolderSearch] = useState('')
  const [albumSearch, setAlbumSearch] = useState('')
  const dragging = useRef(false)
  const queryClient = useQueryClient()

  // Warm the albums cache immediately so the Albums tab renders without a spinner
  useEffect(() => {
    queryClient.prefetchQuery({ queryKey: ['albums'], queryFn: listAlbums })
  }, [queryClient])

  // Switch to albums tab when navigating to an album
  useEffect(() => {
    if (location.pathname.startsWith('/albums')) {
      setActiveTab('albums')
    }
  }, [location.pathname])

  function switchTab(tab: SidebarTab) {
    setActiveTab(tab)
    try { localStorage.setItem(TAB_KEY, tab) } catch { /* ignore */ }
  }

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
        <img src="/icon.svg" alt="" className="w-7 h-7 rounded-md" aria-hidden="true" />
        <span className="text-base font-bold tracking-tight text-neutral-100">Monet</span>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-neutral-800 shrink-0">
        <button
          type="button"
          onClick={() => switchTab('folders')}
          className={cn(
            'flex-1 flex items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors',
            activeTab === 'folders'
              ? 'text-neutral-100 border-b-2 border-blue-500'
              : 'text-neutral-500 hover:text-neutral-300'
          )}
        >
          <FolderOpen size={13} />
          Folders
        </button>
        <button
          type="button"
          onClick={() => switchTab('albums')}
          className={cn(
            'flex-1 flex items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors',
            activeTab === 'albums'
              ? 'text-neutral-100 border-b-2 border-blue-500'
              : 'text-neutral-500 hover:text-neutral-300'
          )}
        >
          <Images size={13} />
          Albums
        </button>
        <button
          type="button"
          onClick={() => switchTab('searches')}
          className={cn(
            'flex-1 flex items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors',
            activeTab === 'searches'
              ? 'text-neutral-100 border-b-2 border-blue-500'
              : 'text-neutral-500 hover:text-neutral-300'
          )}
        >
          <Clock size={13} />
          Searches
        </button>
      </div>

      {/* Disk deletion banner — outside the scroll area so it stays visible */}
      {currentUser?.allow_disk_deletion && (
        <div
          title="Deleting files from disk is active. You can select files and delete them from disk, the selected files will be deleted permanently and the action is irrevocable."
          className="mx-2 mt-2 shrink-0 rounded bg-red-950/60 border border-red-800/50 px-2.5 py-2 space-y-1"
        >
          <div className="flex items-center gap-1.5">
            <AlertTriangle size={12} className="shrink-0 text-red-400" />
            <span className="flex-1 text-xs font-medium text-red-300">Disk deletion active</span>
            <Link to="/settings" state={{ tab: 'account' }} className="text-xs text-red-500 hover:text-red-300 shrink-0">
              Turn off
            </Link>
          </div>
          <p className="text-xs text-red-400/70 leading-snug pl-0.5">
            Selected files can be permanently deleted from disk.
          </p>
        </div>
      )}

      {/* Search — outside scroll area so it stays visible */}
      {activeTab !== 'searches' && (
        <div className="pt-2 pb-1 shrink-0">
          {activeTab === 'folders' ? (
            <SearchInput
              value={folderSearch}
              onChange={setFolderSearch}
              placeholder="Search folders…"
            />
          ) : (
            <SearchInput
              value={albumSearch}
              onChange={setAlbumSearch}
              placeholder="Search albums…"
            />
          )}
        </div>
      )}

      {/* Content */}
      <nav className="flex-1 overflow-y-auto pt-1">
        {activeTab === 'folders' ? (
          <>
            {folderSearch ? (
              <FolderSearchResults query={folderSearch} rootFolders={visibleRootFolders} />
            ) : isLoading ? (
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
          </>
        ) : activeTab === 'albums' ? (
          <AlbumList filter={albumSearch} />
        ) : (
          <RecentSearchesPanel />
        )}
      </nav>

      {/* Bottom: Faces + Trash + Settings */}
      <div className="border-t border-neutral-800 px-2 py-2 space-y-0.5">
        <Link
          to="/faces"
          className={cn(
            'flex items-center gap-2.5 rounded px-3 py-2 text-sm transition-colors',
            location.pathname.startsWith('/faces')
              ? 'bg-blue-900/40 text-blue-100 ring-1 ring-inset ring-blue-700/40'
              : 'text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800'
          )}
        >
          <Users size={16} />
          <span>People</span>
        </Link>
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
