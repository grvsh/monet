import { useRef, useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listAlbumFiles, removeFilesFromAlbum } from '../../api/albums'
import { useGalleryStore } from '../../store/gallery'
import type { FileResponse } from '../../types/api'
import MediaTile from '../gallery/MediaTile'
import MediaLightbox from '../lightbox/MediaLightbox'
import { Spinner } from '../ui/Spinner'
import { ArrowUp, Images } from 'lucide-react'
import { cn } from '../../lib/utils'
import MediaTypeTabs from '../gallery/MediaTypeTabs'

const TILE_SIZE = 200
const GAP = 4
const MIN_COLUMNS = 2
const CAPTION_HEIGHT = 52


function useContainerWidth(ref: React.RefObject<HTMLDivElement | null>) {
  const [width, setWidth] = useState(0)
  useEffect(() => {
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

export default function AlbumView() {
  const { albumId } = useParams<{ albumId: string }>()
  const containerRef = useRef<HTMLDivElement>(null)
  const containerWidth = useContainerWidth(containerRef)

  const [mediaTypeFilter, setMediaTypeFilter] = useState<'all' | 'image' | 'video' | 'audio'>('all')

  const lightboxIndex = useGalleryStore((s) => s.lightboxIndex)
  const setLightboxIndex = useGalleryStore((s) => s.setLightboxIndex)
  const selectedIds = useGalleryStore((s) => s.selectedIds)
  const toggleSelection = useGalleryStore((s) => s.toggleSelection)
  const clearSelection = useGalleryStore((s) => s.clearSelection)
  const selectAll = useGalleryStore((s) => s.selectAll)
  const selectRange = useGalleryStore((s) => s.selectRange)
  const lastSelectedIndex = useRef<number | null>(null)

  const queryClient = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['album-files', albumId],
    queryFn: () => listAlbumFiles(albumId!),
    enabled: !!albumId,
  })

  const { mutate: removeFiles, isPending: isRemoving } = useMutation({
    mutationFn: () => removeFilesFromAlbum(albumId!, Array.from(selectedIds)),
    onSuccess: () => {
      clearSelection()
      queryClient.invalidateQueries({ queryKey: ['album-files', albumId] })
      queryClient.invalidateQueries({ queryKey: ['albums'] })
    },
  })

  useEffect(() => {
    clearSelection()
    setMediaTypeFilter('all')
    lastSelectedIndex.current = null
  }, [albumId, clearSelection])

  // Clear selection when filter changes so stale cross-type selections don't linger
  useEffect(() => {
    clearSelection()
    lastSelectedIndex.current = null
  }, [mediaTypeFilter, clearSelection])

  // All files from API (unfiltered) — used for counts
  const allFiles: FileResponse[] = data?.items ?? []

  const typeCounts = {
    image: allFiles.filter((f) => f.media_type === 'image').length,
    video: allFiles.filter((f) => f.media_type === 'video').length,
    audio: allFiles.filter((f) => f.media_type === 'audio').length,
  }

  // Files shown in the grid (filtered)
  const files = mediaTypeFilter === 'all'
    ? allFiles
    : allFiles.filter((f) => f.media_type === mediaTypeFilter)

  const allFileIds = files.map((f) => f.id)
  const anySelected = selectedIds.size > 0
  const selectionCount = selectedIds.size

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

  function handleSelect(id: string, index: number, shiftKey: boolean) {
    if (shiftKey && lastSelectedIndex.current !== null) {
      const lo = Math.min(lastSelectedIndex.current, index)
      const hi = Math.max(lastSelectedIndex.current, index)
      selectRange(files.slice(lo, hi + 1).map((f) => f.id))
    } else {
      toggleSelection(id)
      lastSelectedIndex.current = index
    }
  }

  function handleRemove() {
    if (window.confirm(`Remove ${selectionCount} ${selectionCount === 1 ? 'file' : 'files'} from this album?`)) {
      removeFiles()
    }
  }

  let inner: React.ReactNode
  if (isLoading) {
    inner = <div className="flex items-center justify-center h-64"><Spinner size="lg" /></div>
  } else if (error) {
    inner = <div className="flex items-center justify-center h-64"><p className="text-red-400 text-sm">Failed to load album.</p></div>
  } else if (!albumId) {
    inner = (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-neutral-500">
        <Images size={40} strokeWidth={1.2} />
        <p className="text-sm">Select an album from the sidebar.</p>
      </div>
    )
  } else if (allFiles.length === 0) {
    inner = <div className="flex items-center justify-center h-64"><p className="text-neutral-500 text-sm">This album is empty.</p></div>
  } else if (files.length === 0) {
    inner = <div className="flex items-center justify-center h-64"><p className="text-neutral-500 text-sm">No {mediaTypeFilter}s in this album.</p></div>
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
                    onSelect={(id, shiftKey) => handleSelect(id, startIndex + colIndex, shiftKey)}
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
      {/* Toolbar */}
      <div className="shrink-0 border-b border-neutral-800 bg-neutral-900">
        <div className="flex items-center gap-3 px-4 py-2.5">

          {/* Media type tabs */}
          <MediaTypeTabs
            value={mediaTypeFilter}
            typeCounts={typeCounts}
            onChange={setMediaTypeFilter}
          />

          <div className="w-px h-4 bg-neutral-700 shrink-0" />

          {/* Select all */}
          <button
            type="button"
            onClick={() => selectAll(allFileIds)}
            disabled={allFileIds.length === 0}
            className="text-xs text-neutral-400 hover:text-neutral-200 disabled:text-neutral-600 disabled:cursor-not-allowed shrink-0 transition-colors"
          >
            Select all
          </button>

          {/* Selection actions */}
          {selectionCount > 0 && (
            <>
              <button
                type="button"
                onClick={clearSelection}
                className="text-xs text-neutral-400 hover:text-neutral-200 shrink-0 transition-colors"
              >
                Clear selection
              </button>

              <button
                type="button"
                onClick={handleRemove}
                disabled={isRemoving}
                className={cn(
                  'flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium',
                  'bg-neutral-700 hover:bg-neutral-600 text-white disabled:opacity-50 transition-colors shrink-0'
                )}
              >
                <ArrowUp size={12} className="rotate-45" />
                {isRemoving ? 'Removing…' : `Remove from album (${selectionCount})`}
              </button>
            </>
          )}
        </div>
      </div>

      <div ref={containerRef} className="flex-1 overflow-y-auto bg-neutral-950 p-2">
        {inner}
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
