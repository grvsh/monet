import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { browseFs } from '../../api/fsBrowse'
import { Folder, Link as LinkIcon, ChevronRight } from 'lucide-react'
import { Spinner } from '../ui/Spinner'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { cn } from '../../lib/utils'

interface DirectoryBrowserProps {
  onSelect: (path: string) => void
}

export default function DirectoryBrowser({ onSelect }: DirectoryBrowserProps) {
  // null = showing allowed roots, string = browsing inside a path
  const [currentPath, setCurrentPath] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['fs-browse', currentPath],
    queryFn: () => browseFs(currentPath),
    staleTime: 10_000,
  })

  const atRootsView = currentPath === null

  // Build breadcrumb segments from current path
  function buildBreadcrumbs(path: string): Array<{ label: string; path: string }> {
    const parts = path.split('/').filter(Boolean)
    let built = ''
    const crumbs: Array<{ label: string; path: string }> = []
    for (const part of parts) {
      built += `/${part}`
      crumbs.push({ label: part, path: built })
    }
    return crumbs
  }

  const breadcrumbs = currentPath ? buildBreadcrumbs(currentPath) : []

  return (
    <div className="flex flex-col gap-3">
      {/* Breadcrumb */}
      <div className="flex items-center flex-wrap gap-1 bg-neutral-800 rounded px-3 py-2 text-sm">
        <button
          onClick={() => setCurrentPath(null)}
          className={cn(
            'hover:text-blue-400 transition-colors',
            atRootsView ? 'text-neutral-200 font-medium' : 'text-neutral-400'
          )}
        >
          Allowed folders
        </button>
        {breadcrumbs.map((crumb, i) => (
          <span key={crumb.path} className="flex items-center gap-1">
            <ChevronRight size={12} className="text-neutral-600" />
            <button
              onClick={() => setCurrentPath(crumb.path)}
              className={cn(
                'hover:text-blue-400 transition-colors',
                i === breadcrumbs.length - 1
                  ? 'text-neutral-200 font-medium'
                  : 'text-neutral-400'
              )}
            >
              {crumb.label}
            </button>
          </span>
        ))}
      </div>

      {/* Directory listing */}
      <div className="rounded border border-neutral-700 bg-neutral-950 overflow-hidden min-h-[200px] max-h-[300px] overflow-y-auto">
        {isLoading ? (
          <div className="flex justify-center items-center h-32">
            <Spinner />
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-32 text-sm text-red-400">
            Failed to load directory.
          </div>
        ) : data?.entries.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-sm text-neutral-500">
            No subdirectories found.
          </div>
        ) : (
          <ul className="divide-y divide-neutral-800">
            {data?.entries.map((entry) =>
              entry.is_configured ? (
                <li key={entry.path}>
                  <div className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-neutral-600 select-none">
                    <Folder size={15} className="shrink-0 text-neutral-700" />
                    <span className="flex-1 truncate font-mono">{entry.name}</span>
                    {entry.is_symlink && (
                      <Badge variant="blue">
                        <LinkIcon size={10} className="mr-1" />
                        symlink
                      </Badge>
                    )}
                    <Badge variant="yellow">Already added</Badge>
                  </div>
                </li>
              ) : (
                <li key={entry.path}>
                  <button
                    onClick={() => setCurrentPath(entry.path)}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left transition-colors hover:bg-neutral-800 text-neutral-200 cursor-pointer"
                  >
                    <Folder size={15} className="shrink-0 text-neutral-500" />
                    <span className="flex-1 truncate font-mono">{entry.name}</span>
                    {entry.is_symlink && (
                      <Badge variant="blue">
                        <LinkIcon size={10} className="mr-1" />
                        symlink
                      </Badge>
                    )}
                  </button>
                </li>
              )
            )}
          </ul>
        )}
      </div>

      {/* Go up — only when inside an allowed root (backend sets parent=null at boundary) */}
      {!atRootsView && data?.parent != null && (
        <button
          onClick={() => setCurrentPath(data.parent!)}
          className="text-xs text-neutral-400 hover:text-neutral-200 text-left transition-colors"
        >
          ← Go up
        </button>
      )}
      {!atRootsView && data?.parent == null && (
        <button
          onClick={() => setCurrentPath(null)}
          className="text-xs text-neutral-400 hover:text-neutral-200 text-left transition-colors"
        >
          ← Back to allowed folders
        </button>
      )}

      {/* Use this folder button */}
      <Button
        variant="primary"
        onClick={() => currentPath && onSelect(currentPath)}
        disabled={atRootsView || !!data?.path_is_configured}
        className="w-full"
      >
        Use this folder
      </Button>
      {!atRootsView && data?.path_is_configured && (
        <p className="text-xs text-amber-500 text-center">
          This folder (or a parent) is already added as a root.
        </p>
      )}
      {!atRootsView && !data?.path_is_configured && (
        <p className="text-xs text-neutral-500 text-center">
          Selected: <span className="text-neutral-300 font-mono">{currentPath}</span>
        </p>
      )}
    </div>
  )
}
