import { useLocation, Link, useParams } from 'react-router-dom'
import { LogOut, User } from 'lucide-react'
import { useAuthStore } from '../../store/auth'
import { logout } from '../../api/auth'
import { useQuery } from '@tanstack/react-query'
import { listRootFolders } from '../../api/rootFolders'

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

    // Additional path segments from the splat
    const rest = location.pathname.replace(`/browse/${rootFolderId ?? ''}`, '').replace(/^\//, '')
    if (rest) {
      const parts = rest.split('/').filter(Boolean)
      let builtPath = `/browse/${rootFolderId}`
      for (const part of parts) {
        builtPath += `/${part}`
        segments.push({ label: decodeURIComponent(part), to: builtPath })
      }
    }
  } else if (location.pathname.startsWith('/settings')) {
    segments.push({ label: 'Settings' })
  }

  return segments
}

export default function Topbar() {
  const storeLogout = useAuthStore((s) => s.logout)
  const user = useAuthStore((s) => s.user)
  const breadcrumbs = useBreadcrumbs()

  async function handleLogout() {
    try {
      await logout()
    } finally {
      storeLogout()
      window.location.href = '/login'
    }
  }

  return (
    <header className="flex items-center justify-between h-12 px-4 border-b border-neutral-800 bg-neutral-900 shrink-0">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1 text-sm text-neutral-400 overflow-hidden">
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
