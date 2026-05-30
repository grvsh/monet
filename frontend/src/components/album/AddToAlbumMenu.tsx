import { useRef, useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Images, Plus, Check } from 'lucide-react'
import { listAlbums, createAlbum, addFilesToAlbum } from '../../api/albums'
import { useGalleryStore } from '../../store/gallery'
import { cn } from '../../lib/utils'
import { Spinner } from '../ui/Spinner'

export default function AddToAlbumMenu() {
  const [open, setOpen] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [newName, setNewName] = useState('')
  const [justAdded, setJustAdded] = useState<string | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  const selectedIds = useGalleryStore((s) => s.selectedIds)
  const queryClient = useQueryClient()

  const { data: albums, isLoading } = useQuery({
    queryKey: ['albums'],
    queryFn: listAlbums,
    staleTime: 30_000,
  })

  const { mutate: addFiles, isPending: isAdding } = useMutation({
    mutationFn: (albumId: string) =>
      addFilesToAlbum(albumId, Array.from(selectedIds)),
    onSuccess: (_, albumId) => {
      queryClient.invalidateQueries({ queryKey: ['album-files', albumId] })
      queryClient.invalidateQueries({ queryKey: ['albums'] })
      setJustAdded(albumId)
      setTimeout(() => {
        setJustAdded(null)
        setOpen(false)
      }, 900)
    },
  })

  // Accepts name as argument to avoid stale-closure issues with newName state
  const { mutate: doCreate, isPending: isCreating } = useMutation({
    mutationFn: (name: string) => createAlbum(name),
    onSuccess: (album) => {
      queryClient.invalidateQueries({ queryKey: ['albums'] })
      addFiles(album.id)
      setNewName('')
      setShowNew(false)
    },
  })

  function handleCreate() {
    const name = newName.trim()
    if (name) doCreate(name)
  }

  // Close on outside click
  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false)
        setShowNew(false)
        setNewName('')
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  return (
    <div ref={menuRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors',
          'bg-neutral-700 hover:bg-neutral-600 text-white'
        )}
      >
        <Images size={12} />
        Add to album
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 z-50 w-56 rounded border border-neutral-700 bg-neutral-900 shadow-xl py-1">
          {isLoading ? (
            <div className="flex justify-center py-4">
              <Spinner size="sm" />
            </div>
          ) : (
            <>
              {albums?.length === 0 && !showNew && (
                <p className="px-3 py-2 text-xs text-neutral-500">No albums yet.</p>
              )}

              {albums?.map((album) => (
                <button
                  type="button"
                  key={album.id}
                  onClick={() => !isAdding && addFiles(album.id)}
                  disabled={isAdding}
                  className="flex items-center gap-2 w-full px-3 py-2 text-xs text-neutral-300 hover:bg-neutral-800 hover:text-neutral-100 transition-colors disabled:opacity-60"
                >
                  {justAdded === album.id ? (
                    <Check size={14} className="text-green-400 shrink-0" />
                  ) : (
                    <Images size={14} className="shrink-0 text-neutral-500" />
                  )}
                  <span className="flex-1 truncate text-left">{album.name}</span>
                  <span className="text-neutral-600 shrink-0 text-xs">
                    {album.file_count.toLocaleString()}
                  </span>
                </button>
              ))}

              <div className={cn('pt-1', (albums?.length ?? 0) > 0 && 'border-t border-neutral-800 mt-1')}>
                {showNew ? (
                  <div className="px-3 py-1.5">
                    <input
                      autoFocus
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleCreate()
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
                        type="button"
                        onClick={handleCreate}
                        disabled={!newName.trim() || isCreating}
                        className="text-xs text-blue-400 hover:text-blue-300 disabled:text-neutral-600 transition-colors"
                      >
                        {isCreating ? 'Creating…' : 'Create & add'}
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
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={() => setShowNew(true)}
                    className="flex items-center gap-2 w-full px-3 py-2 text-xs text-neutral-400 hover:bg-neutral-800 hover:text-neutral-200 transition-colors"
                  >
                    <Plus size={14} />
                    New album
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
