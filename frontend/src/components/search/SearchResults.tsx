import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useGalleryStore } from '../../store/gallery'
import { searchFiles } from '../../api/search'
import MediaTile from '../gallery/MediaTile'
import MediaLightbox from '../lightbox/MediaLightbox'
import { Spinner } from '../ui/Spinner'

const TILE_SIZE = 200
const GAP = 4

export default function SearchResults() {
  const [searchParams] = useSearchParams()
  const q = searchParams.get('q') ?? ''
  const folderId = searchParams.get('folder_id') ?? undefined
  const albumId = searchParams.get('album_id') ?? undefined

  const lightboxIndex = useGalleryStore((s) => s.lightboxIndex)
  const setLightboxIndex = useGalleryStore((s) => s.setLightboxIndex)
  const selectedIds = useGalleryStore((s) => s.selectedIds)
  const toggleSelection = useGalleryStore((s) => s.toggleSelection)

  useEffect(() => { setLightboxIndex(-1) }, [setLightboxIndex])

  const { data, isLoading, error } = useQuery({
    queryKey: ['search', q, folderId, albumId],
    queryFn: () => searchFiles({ q, folder_id: folderId, album_id: albumId, page_size: 500 }),
    enabled: q.length > 0,
  })

  const files = data?.items ?? []

  const scopeLabel = albumId ? 'album' : folderId ? 'folder' : 'library'

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-neutral-800 shrink-0">
        <p className="text-sm text-neutral-400">
          {q ? (
            isLoading ? (
              'Searching…'
            ) : (
              <>
                <span className="text-neutral-100 font-medium">{data?.total ?? 0}</span>
                {' result'}
                {(data?.total ?? 0) !== 1 ? 's' : ''} for{' '}
                <span className="text-neutral-100 font-medium">"{q}"</span>
                {' in '}
                <span className="text-neutral-300">{scopeLabel}</span>
              </>
            )
          ) : (
            'Enter a search query in the bar above.'
          )}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto bg-neutral-950 p-2">
        {isLoading && (
          <div className="flex items-center justify-center h-64">
            <Spinner size="lg" />
          </div>
        )}
        {error && (
          <div className="flex items-center justify-center h-64">
            <p className="text-red-400 text-sm">Search failed. Please try again.</p>
          </div>
        )}
        {!isLoading && !error && q && files.length === 0 && (
          <div className="flex items-center justify-center h-64">
            <p className="text-neutral-500 text-sm">No results found.</p>
          </div>
        )}
        {!isLoading && files.length > 0 && (
          <div
            className="flex flex-wrap"
            style={{ gap: GAP }}
          >
            {files.map((file, index) => (
              <div key={file.id} style={{ width: TILE_SIZE, height: TILE_SIZE + 52, flexShrink: 0 }}>
                <MediaTile
                  file={file}
                  imageSize={TILE_SIZE}
                  onClick={() => setLightboxIndex(index)}
                  selected={selectedIds.has(file.id)}
                  anySelected={selectedIds.size > 0}
                  onSelect={(id) => toggleSelection(id)}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {lightboxIndex >= 0 && files.length > 0 && (
        <MediaLightbox
          files={files}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(-1)}
        />
      )}
    </div>
  )
}
