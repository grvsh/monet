import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Images } from 'lucide-react'
import { listAlbums, createAlbum } from '../../api/albums'
import { cn } from '../../lib/utils'
import { Spinner } from '../ui/Spinner'

// Characters of `query` must all appear in `text`, in order (case-insensitive)
function fuzzyMatch(text: string, query: string): boolean {
  if (!query) return true
  const t = text.toLowerCase()
  const q = query.toLowerCase()
  let qi = 0
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi++
  }
  return qi === q.length
}

interface AlbumListProps {
  filter?: string
}

export default function AlbumList({ filter = '' }: AlbumListProps) {
  const location = useLocation()
  const queryClient = useQueryClient()
  const [showNew, setShowNew] = useState(false)
  const [newName, setNewName] = useState('')

  const { data: albums, isLoading } = useQuery({
    queryKey: ['albums'],
    queryFn: listAlbums,
    staleTime: 30_000,
  })

  const { mutate: doCreate, isPending } = useMutation({
    mutationFn: (name: string) => createAlbum(name),
    onSuccess: () => {
      setNewName('')
      setShowNew(false)
      queryClient.invalidateQueries({ queryKey: ['albums'] })
    },
  })

  function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    const name = newName.trim()
    if (name) doCreate(name)
  }

  const visible = albums?.filter((a) => fuzzyMatch(a.name, filter)) ?? []

  return (
    <div className="px-2 space-y-0.5">
      {isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner size="sm" />
        </div>
      ) : (
        <>
          {albums?.length === 0 && !showNew && (
            <p className="text-xs text-neutral-500 px-3 py-4 text-center">No albums yet.</p>
          )}

          {filter && visible.length === 0 && (albums?.length ?? 0) > 0 && (
            <p className="text-xs text-neutral-500 px-3 py-4 text-center">
              No albums match "{filter}".
            </p>
          )}

          {visible.map((album) => (
            <Link
              key={album.id}
              to={`/albums/${album.id}`}
              className={cn(
                'flex items-center gap-2.5 rounded px-3 py-2 text-sm transition-colors',
                location.pathname === `/albums/${album.id}`
                  ? 'bg-blue-900/40 text-blue-100 ring-1 ring-inset ring-blue-700/40'
                  : 'text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800'
              )}
            >
              {album.cover_url ? (
                <img
                  src={album.cover_url}
                  alt=""
                  className="w-5 h-5 rounded object-cover shrink-0"
                />
              ) : (
                <Images size={16} className="shrink-0" />
              )}
              <span className="flex-1 truncate">{album.name}</span>
              <span className="text-xs text-neutral-500 shrink-0">
                {album.file_count.toLocaleString()}
              </span>
            </Link>
          ))}
        </>
      )}

      {/* New album inline form — only show when not filtering */}
      {!filter && showNew && (
        <form onSubmit={handleCreate} className="px-3 py-1">
          <input
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setShowNew(false)
                setNewName('')
              }
            }}
            placeholder="Album name…"
            className="w-full rounded border border-neutral-700 bg-neutral-800 px-2 py-1 text-xs text-neutral-200 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <div className="flex gap-3 mt-1.5">
            <button
              type="submit"
              disabled={!newName.trim() || isPending}
              className="text-xs text-blue-400 hover:text-blue-300 disabled:text-neutral-600 transition-colors"
            >
              {isPending ? 'Creating…' : 'Create'}
            </button>
            <button
              type="button"
              onClick={() => {
                setShowNew(false)
                setNewName('')
              }}
              className="text-xs text-neutral-500 hover:text-neutral-300 transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* New album button — hidden while filtering so it doesn't confuse */}
      {!filter && !showNew && (
        <button
          type="button"
          onClick={() => setShowNew(true)}
          className="flex items-center gap-2 w-full px-3 py-2 text-xs text-neutral-500 hover:text-neutral-200 transition-colors"
        >
          <Plus size={14} />
          New album
        </button>
      )}
    </div>
  )
}
