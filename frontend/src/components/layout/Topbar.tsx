import { useState, useRef, useEffect, type FormEvent } from 'react'
import { useLocation, Link, useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { LogOut, User, Search, MoreHorizontal } from 'lucide-react'
import { useAuthStore } from '../../store/auth'
import { useGalleryStore } from '../../store/gallery'
import { useRecentSearchesStore } from '../../store/recentSearches'
import { logout } from '../../api/auth'
import { useQuery } from '@tanstack/react-query'
import { listRootFolders } from '../../api/rootFolders'

type SearchScope = 'library' | 'current'

function useBreadcrumbs() {
  const location = useLocation()
  const { rootFolderId } = useParams<{ rootFolderId?: string }>()

  const { data: rootFolders } = useQuery({
    queryKey: ['root-folders'],
    queryFn: listRootFolders,
  })

  const segments: Array<{ label: string; to?: string }> = []

  if (location.pathname.startsWith('/browse')) {
    segments.push({ label: 'Browse', to: '/browse' })

    if (rootFolderId && rootFolders) {
      const rf = rootFolders.find((r) => r.id === rootFolderId)
      if (rf) {
        segments.push({ label: rf.name, to: `/browse/${rootFolderId}` })
      }
    }

    const rest = location.pathname.replace(`/browse/${rootFolderId ?? ''}`, '').replace(/^\//, '')
    if (rest) {
      const parts = rest.split('/').filter(Boolean)
      let builtPath = `/browse/${rootFolderId}`
      for (const part of parts) {
        builtPath += `/${part}`
        segments.push({ label: decodeURIComponent(part), to: builtPath })
      }
    }
  } else if (location.pathname.startsWith('/search')) {
    segments.push({ label: 'Search results' })
  } else if (location.pathname.startsWith('/settings')) {
    segments.push({ label: 'Settings' })
  }

  return segments
}

export default function Topbar() {
  const storeLogout = useAuthStore((s) => s.logout)
  const user = useAuthStore((s) => s.user)
  const currentFolderId = useGalleryStore((s) => s.currentFolderId)
  const currentAlbumId = useGalleryStore((s) => s.currentAlbumId)
  const setLightboxIndex = useGalleryStore((s) => s.setLightboxIndex)
  const addRecentSearch = useRecentSearchesStore((s) => s.add)
  const breadcrumbs = useBreadcrumbs()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()

  const [query, setQuery] = useState(() =>
    location.pathname.startsWith('/search') ? (searchParams.get('q') ?? '') : ''
  )
  const [scope, setScope] = useState<SearchScope>('library')
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  const canScopeToFolder = !!currentFolderId
  const canScopeToAlbum = !!currentAlbumId
  const hasCurrentContext = canScopeToFolder || canScopeToAlbum

  // Reset scope to library when context disappears
  useEffect(() => {
    if (!hasCurrentContext) setScope('library')
  }, [hasCurrentContext])

  // Sync input with URL when navigating to/from search
  useEffect(() => {
    if (location.pathname.startsWith('/search')) {
      setQuery(searchParams.get('q') ?? '')
    }
  }, [location.pathname, searchParams])

  // Close menu on outside click
  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [])

  async function handleLogout() {
    try {
      await logout()
    } finally {
      storeLogout()
      window.location.href = '/login'
    }
  }

  function handleSearch(e: FormEvent) {
    e.preventDefault()
    const q = query.trim()
    if (!q) return
    const params = new URLSearchParams({ q })
    if (scope === 'current') {
      if (currentFolderId) params.set('folder_id', currentFolderId)
      else if (currentAlbumId) params.set('album_id', currentAlbumId)
    }
    try { addRecentSearch(q) } catch { /* non-critical */ }
    setLightboxIndex(-1)
    navigate(`/search?${params.toString()}`)
    setMenuOpen(false)
  }

  const scopeLabel =
    scope === 'current'
      ? currentAlbumId
        ? 'Current album'
        : 'Current folder'
      : 'Whole library'

  return (
    <header className="flex items-center justify-between h-12 px-4 border-b border-neutral-800 bg-neutral-900 shrink-0 gap-4">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1 text-sm text-neutral-400 overflow-hidden min-w-0 shrink">
        {breadcrumbs.map((crumb, i) => (
          <span key={i} className="flex items-center gap-1 min-w-0">
            {i > 0 && <span className="text-neutral-600">/</span>}
            {crumb.to && i < breadcrumbs.length - 1 ? (
              <Link
                to={crumb.to}
                className="hover:text-neutral-100 transition-colors truncate max-w-[200px]"
              >
                {crumb.label}
              </Link>
            ) : (
              <span className="text-neutral-200 truncate max-w-[200px]">{crumb.label}</span>
            )}
          </span>
        ))}
      </nav>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex items-center gap-1 shrink-0">
        <div className="flex items-center gap-1.5 rounded-md border border-neutral-700 bg-neutral-800 px-2.5 h-8 w-64 focus-within:border-neutral-500 transition-colors">
          <Search size={13} className="text-neutral-500 shrink-0" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search captions…"
            className="flex-1 bg-transparent text-sm text-neutral-200 placeholder:text-neutral-600 outline-none min-w-0"
          />
        </div>

        {/* Scope menu */}
        <div ref={menuRef} className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((o) => !o)}
            title={`Search scope: ${scopeLabel}`}
            className="flex items-center justify-center w-8 h-8 rounded-md text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800 transition-colors"
          >
            <MoreHorizontal size={15} />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full mt-1 w-48 rounded-md border border-neutral-700 bg-neutral-800 shadow-lg z-50 py-1">
              <p className="px-3 pt-1 pb-1.5 text-xs text-neutral-500 font-medium uppercase tracking-wide">
                Search scope
              </p>
              <button
                type="button"
                onClick={() => { setScope('library'); setMenuOpen(false) }}
                className={`w-full text-left px-3 py-1.5 text-sm transition-colors ${
                  scope === 'library'
                    ? 'text-neutral-100 bg-neutral-700'
                    : 'text-neutral-300 hover:bg-neutral-700 hover:text-neutral-100'
                }`}
              >
                Whole library
              </button>
              <button
                type="button"
                disabled={!hasCurrentContext}
                onClick={() => { if (hasCurrentContext) { setScope('current'); setMenuOpen(false) } }}
                className={`w-full text-left px-3 py-1.5 text-sm transition-colors ${
                  scope === 'current'
                    ? 'text-neutral-100 bg-neutral-700'
                    : hasCurrentContext
                    ? 'text-neutral-300 hover:bg-neutral-700 hover:text-neutral-100'
                    : 'text-neutral-600 cursor-not-allowed'
                }`}
              >
                {currentAlbumId ? 'Current album' : 'Current folder'}
                {!hasCurrentContext && (
                  <span className="block text-xs text-neutral-600">Open a folder or album first</span>
                )}
              </button>
            </div>
          )}
        </div>
      </form>

      {/* User info + logout */}
      <div className="flex items-center gap-3 shrink-0">
        {user && (
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-neutral-700 flex items-center justify-center">
              <User size={12} className="text-neutral-400" />
            </div>
            <span className="text-sm text-neutral-300 hidden sm:block">
              {user.full_name ?? user.email}
            </span>
          </div>
        )}
        <button
          onClick={handleLogout}
          className="flex items-center gap-1.5 rounded px-2 py-1 text-xs text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800 transition-colors"
          title="Sign out"
        >
          <LogOut size={14} />
          <span className="hidden sm:inline">Sign out</span>
        </button>
      </div>
    </header>
  )
}
