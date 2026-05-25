import { useRef, useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useQuery } from '@tanstack/react-query'
import { listFolderFiles, resolveFolderByPath } from '../../api/folders'
import { useGalleryStore } from '../../store/gallery'
import type { FileResponse } from '../../types/api'
import MediaTile from './MediaTile'
import GalleryToolbar from './GalleryToolbar'
import FolderTrashSection from './FolderTrashSection'
import FolderMissingSection from './FolderMissingSection'
import MediaLightbox from '../lightbox/MediaLightbox'
import { Spinner } from '../ui/Spinner'

const TILE_SIZE = 200
const GAP = 4
const MIN_COLUMNS = 2
const CAPTION_HEIGHT = 52

function useContainerWidth(ref: React.RefObject<HTMLDivElement | null>) {
  const [width, setWidth] = useState(0)

  useEffect(() => {
    // Runs after every render so we catch the first time ref.current becomes non-null.
    if (!ref.current) return
    const el = ref.current
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width
      if (w) setWidth(w)
    })
    observer.observe(el)
    return () => observer.disconnect()
  })

  return width
}

function useFolderIdForRoute(): { folderId: string | null; isResolving: boolean } {
  const { rootFolderId, '*': splat } = useParams<{ rootFolderId?: string; '*'?: string }>()

  const normalizedPath = splat ? splat.replace(/^\//, '') : ''

  const { data: folder, isLoading } = useQuery({
    queryKey: ['folder-by-path', rootFolderId, normalizedPath],
    queryFn: () => resolveFolderByPath(rootFolderId!, normalizedPath),
    enabled: !!rootFolderId,
    retry: false,
  })

  if (!rootFolderId) return { folderId: null, isResolving: false }
  if (isLoading) return { folderId: null, isResolving: true }

  return { folderId: folder?.id ?? null, isResolving: false }
}

export default function GalleryGrid() {
  const containerRef = useRef<HTMLDivElement>(null)
  const containerWidth = useContainerWidth(containerRef)

  const { folderId, isResolving } = useFolderIdForRoute()
  const sortField = useGalleryStore((s) => s.sortField)
  const sortOrder = useGalleryStore((s) => s.sortOrder)
  const mediaTypeFilter = useGalleryStore((s) => s.mediaTypeFilter)
  const lightboxIndex = useGalleryStore((s) => s.lightboxIndex)
  const setLightboxIndex = useGalleryStore((s) => s.setLightboxIndex)
  const selectedIds = useGalleryStore((s) => s.selectedIds)
  const toggleSelection = useGalleryStore((s) => s.toggleSelection)
  const clearSelection = useGalleryStore((s) => s.clearSelection)

  const { data, isLoading, error } = useQuery({
    queryKey: ['folder-files', folderId, sortField, sortOrder, mediaTypeFilter],
    queryFn: () =>
      listFolderFiles(folderId!, {
        page: 1,
        page_size: 500,
        sort: sortField,
        order: sortOrder,
        media_type: mediaTypeFilter,
      }),
    enabled: !!folderId,
  })

  // Clear selection when folder/filter changes
  useEffect(() => {
    clearSelection()
  }, [folderId, sortField, sortOrder, mediaTypeFilter, clearSelection])

  const files: FileResponse[] = data?.items ?? []
  const totalCount = data?.total ?? 0
  const allFileIds = files.map((f) => f.id)
  const anySelected = selectedIds.size > 0

  const columnCount = containerWidth > 0
    ? Math.max(MIN_COLUMNS, Math.floor((containerWidth + GAP) / (TILE_SIZE + GAP)))
    : 0
  const tileSize = columnCount > 0
    ? Math.floor((containerWidth - GAP * (columnCount - 1)) / columnCount)
    : TILE_SIZE
  const rowCount = columnCount > 0 ? Math.ceil(files.length / columnCount) : 0

  const rowVirtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => containerRef.current,
    estimateSize: () => tileSize + CAPTION_HEIGHT + GAP,
    overscan: 5,
  })

  const handleTileClick = useCallback(
    (index: number) => setLightboxIndex(index),
    [setLightboxIndex]
  )

  // Derive inner content
  let inner: React.ReactNode

  if (isResolving || isLoading) {
    inner = (
      <div className="flex items-center justify-center h-64">
        <Spinner size="lg" />
      </div>
    )
  } else if (error) {
    inner = (
      <div className="flex items-center justify-center h-64">
        <p className="text-red-400 text-sm">Failed to load files. Please try again.</p>
      </div>
    )
  } else if (!folderId) {
    inner = (
      <div className="flex items-center justify-center h-64">
        <p className="text-neutral-500 text-sm">Select a folder from the sidebar to browse files.</p>
      </div>
    )
  } else if (files.length === 0) {
    inner = (
      <div className="flex items-center justify-center h-64">
        <p className="text-neutral-500 text-sm">No files found in this folder.</p>
      </div>
    )
  } else if (columnCount > 0) {
    inner = (
      <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative', width: '100%' }}>
        {rowVirtualizer.getVirtualItems().map((virtualRow) => {
          const startIndex = virtualRow.index * columnCount
          const rowFiles = files.slice(startIndex, startIndex + columnCount)
          return (
            <div
              key={virtualRow.key}
              style={{
                position: 'absolute',
                top: virtualRow.start,
                left: 0,
                right: 0,
                height: tileSize + CAPTION_HEIGHT,
                display: 'flex',
                gap: GAP,
              }}
            >
              {rowFiles.map((file, colIndex) => (
                <div
                  key={file.id}
                  style={{ width: tileSize, height: tileSize + CAPTION_HEIGHT, flexShrink: 0 }}
                >
                  <MediaTile
                    file={file}
                    imageSize={tileSize}
                    onClick={() => handleTileClick(startIndex + colIndex)}
                    selected={selectedIds.has(file.id)}
                    anySelected={anySelected}
                    onSelect={toggleSelection}
                  />
                </div>
              ))}
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {!isResolving && !isLoading && folderId && (
        <GalleryToolbar totalCount={totalCount} allFileIds={allFileIds} />
      )}

      {/* containerRef is always mounted so ResizeObserver fires on first render */}
      <div ref={containerRef} className="flex-1 overflow-y-auto bg-neutral-950 p-2">
        {inner}
        {folderId && !isLoading && !isResolving && (
          <FolderMissingSection folderId={folderId} tileSize={tileSize || 200} gap={GAP} />
        )}
        {folderId && !isLoading && !isResolving && (
          <FolderTrashSection folderId={folderId} tileSize={tileSize || 200} gap={GAP} />
        )}
      </div>

      {lightboxIndex >= 0 && (
        <MediaLightbox
          files={files}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(-1)}
        />
      )}
    </div>
  )
}
