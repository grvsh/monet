import { useRef, useCallback, useEffect, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useVirtualizer } from '@tanstack/react-virtual'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listFolderFiles, resolveFolderByPath, listChildFolders, deleteEmptyFolder, getFolderDiskStats, removeFolderFromMonet } from '../../api/folders'
import { listRootFolders } from '../../api/rootFolders'
import { useGalleryStore } from '../../store/gallery'
import { useAuthStore } from '../../store/auth'
import { bulkDeleteFiles } from '../../api/files'
import type { FileResponse } from '../../types/api'
import MediaTile from './MediaTile'
import FolderTile from './FolderTile'
import GalleryToolbar from './GalleryToolbar'
import FolderTrashSection from './FolderTrashSection'
import FolderMissingSection from './FolderMissingSection'
import MediaLightbox from '../lightbox/MediaLightbox'
import DeleteFromDiskModal from './DeleteFromDiskModal'
import { Spinner } from '../ui/Spinner'

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

  const { rootFolderId } = useParams<{ rootFolderId?: string; '*'?: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const currentUser = useAuthStore((s) => s.user)
  const { folderId, isResolving } = useFolderIdForRoute()
  const sortField = useGalleryStore((s) => s.sortField)
  const sortOrder = useGalleryStore((s) => s.sortOrder)
  const mediaTypeFilter = useGalleryStore((s) => s.mediaTypeFilter)
  const lightboxIndex = useGalleryStore((s) => s.lightboxIndex)
  const setLightboxIndex = useGalleryStore((s) => s.setLightboxIndex)
  const selectedIds = useGalleryStore((s) => s.selectedIds)
  const toggleSelection = useGalleryStore((s) => s.toggleSelection)
  const clearSelection = useGalleryStore((s) => s.clearSelection)
  const selectRange = useGalleryStore((s) => s.selectRange)

  // Anchor for shift-click range selection
  const lastSelectedIndex = useRef<number | null>(null)

  const [showDeleteFromDiskModal, setShowDeleteFromDiskModal] = useState(false)

  const queryClient = useQueryClient()

  // Root folders — already cached by the sidebar, no extra fetch
  const { data: rootFolders } = useQuery({
    queryKey: ['root-folders'],
    queryFn: listRootFolders,
  })

  const currentRootFolder = rootFolders?.find((rf) => rf.id === rootFolderId)
  const canDeleteFromDisk = Boolean(
    currentUser?.allow_disk_deletion &&
      (currentUser.role === 'admin' || currentRootFolder?.created_by === currentUser.id)
  )

  // Always fetch all files for the folder (no backend type filter).
  // Filtering is done client-side so tab switching is instant and type
  // counts are always available from the single loaded dataset.
  const { data, isLoading, error } = useQuery({
    queryKey: ['folder-files', folderId, sortField, sortOrder],
    queryFn: () =>
      listFolderFiles(folderId!, {
        page: 1,
        page_size: 500,
        sort: sortField,
        order: sortOrder,
      }),
    enabled: !!folderId,
  })

  const { data: childFolders } = useQuery({
    queryKey: ['folder-children', folderId],
    queryFn: () => listChildFolders(folderId!),
    enabled: !!folderId,
  })

  const folderAppearsEmpty = !isLoading && !isResolving && !!folderId &&
    (data?.items.length ?? 0) === 0 && (childFolders?.length ?? 0) === 0

  const { data: diskStats } = useQuery({
    queryKey: ['folder-disk-stats', folderId],
    queryFn: () => getFolderDiskStats(folderId!),
    enabled: folderAppearsEmpty,
    staleTime: 10_000,
  })

  const { mutate: deleteSelected, isPending: isDeleting } = useMutation({
    mutationFn: () => bulkDeleteFiles(Array.from(selectedIds)),
    onSuccess: () => {
      clearSelection()
      queryClient.invalidateQueries({ queryKey: ['folder-files'] })
      queryClient.invalidateQueries({ queryKey: ['folder-trashed'] })
      queryClient.invalidateQueries({ queryKey: ['trash'] })
    },
  })

  // Clear selection and anchor when folder or sort changes
  useEffect(() => {
    clearSelection()
    lastSelectedIndex.current = null
  }, [folderId, sortField, sortOrder, clearSelection])

  // Escape clears selection (unless a modal is open — let the modal handle it)
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && selectedIds.size > 0 && !showDeleteFromDiskModal && lightboxIndex < 0) {
        clearSelection()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [selectedIds.size, clearSelection, showDeleteFromDiskModal, lightboxIndex])

  // All files loaded from the server (unfiltered)
  const allFiles: FileResponse[] = data?.items ?? []

  // Client-side type filtering — no extra request needed
  const files =
    mediaTypeFilter === 'all'
      ? allFiles
      : allFiles.filter((f) => f.media_type === mediaTypeFilter)

  // Counts derived directly from the loaded dataset
  const typeCounts = {
    image: allFiles.filter((f) => f.media_type === 'image').length,
    video: allFiles.filter((f) => f.media_type === 'video').length,
    audio: allFiles.filter((f) => f.media_type === 'audio').length,
  }

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

  function handleSelect(id: string, index: number, shiftKey: boolean) {
    if (shiftKey && lastSelectedIndex.current !== null) {
      const lo = Math.min(lastSelectedIndex.current, index)
      const hi = Math.max(lastSelectedIndex.current, index)
      selectRange(files.slice(lo, hi + 1).map((f) => f.id))
      // anchor stays — successive shift-clicks extend from the same origin
    } else {
      toggleSelection(id)
      lastSelectedIndex.current = index
    }
  }

  function handleDelete() {
    const count = selectedIds.size
    if (window.confirm(`Trash ${count} ${count === 1 ? 'file' : 'files'}? This removes them from Monet but keeps the files on disk.`)) {
      deleteSelected()
    }
  }

  function handleDeleteFromDisk() {
    setShowDeleteFromDiskModal(true)
  }

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
  } else if (files.length === 0 && (!childFolders || childFolders.length === 0)) {
    const diskFileCount = diskStats?.file_count ?? 0
    const hasNonMediaFiles = diskFileCount > 0

    function goToParent() {
      const pathParts = decodeURIComponent(location.pathname).split('/').filter(Boolean)
      const parentPath = pathParts.length > 2
        ? '/' + pathParts.slice(0, -1).join('/')
        : pathParts.length > 1
        ? '/browse/' + pathParts[1]
        : '/'
      navigate(parentPath)
    }

    inner = (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        {hasNonMediaFiles ? (
          <>
            <p className="text-neutral-500 text-sm text-center">
              This folder has no media files but has{' '}
              <span className="text-neutral-300">{diskFileCount} other {diskFileCount === 1 ? 'file' : 'files'}</span> on disk.
            </p>
            <button
              onClick={async () => {
                if (!window.confirm('Remove this folder from Monet? The folder and its files will remain on disk.')) return
                try {
                  await removeFolderFromMonet(folderId!)
                  queryClient.invalidateQueries({ queryKey: ['folder-children'] })
                  queryClient.invalidateQueries({ queryKey: ['root-level-folders'] })
                  goToParent()
                } catch {
                  alert('Failed to remove folder.')
                }
              }}
              className="px-3 py-1.5 rounded border border-neutral-700 bg-neutral-800 hover:bg-neutral-700 text-xs font-medium text-neutral-300 hover:text-neutral-100 transition-colors"
            >
              Remove from Monet
            </button>
            <p className="text-xs text-neutral-600 text-center max-w-xs leading-relaxed">
              Removes this folder from Monet but does not delete anything from disk.
              If you scan again, it will reappear.
            </p>
          </>
        ) : (
          <>
            <p className="text-neutral-500 text-sm">This folder is empty.</p>
            {canDeleteFromDisk && folderId && (
              <button
                onClick={async () => {
                  if (!window.confirm('Delete this empty folder from disk? This cannot be undone.')) return
                  try {
                    await deleteEmptyFolder(folderId)
                    queryClient.invalidateQueries({ queryKey: ['folder-children'] })
                    queryClient.invalidateQueries({ queryKey: ['root-level-folders'] })
                    goToParent()
                  } catch {
                    alert('Failed to delete folder.')
                  }
                }}
                className="px-3 py-1.5 rounded border border-red-800/60 bg-red-950/40 hover:bg-red-900/50 text-xs font-medium text-red-300 hover:text-red-200 transition-colors"
              >
                Delete folder
              </button>
            )}
          </>
        )}
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
      {!isResolving && !isLoading && folderId && (
        <GalleryToolbar
          typeCounts={typeCounts}
          folderCount={childFolders?.length ?? 0}
          allFileIds={allFileIds}
          onDelete={handleDelete}
          isDeleting={isDeleting}
          canDeleteFromDisk={canDeleteFromDisk}
          onDeleteFromDisk={handleDeleteFromDisk}
        />
      )}

      {/* containerRef is always mounted so ResizeObserver fires on first render */}
      <div ref={containerRef} className="flex-1 overflow-y-auto bg-neutral-950 p-2">
        {inner}
        {/* Subfolder tiles — shown after files, always regardless of active media filter */}
        {columnCount > 0 && childFolders && childFolders.length > 0 && (
          <>
            {allFiles.length > 0 && <div className="border-t border-neutral-800 my-3" />}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: `repeat(${columnCount}, ${tileSize}px)`,
                gap: GAP,
                marginBottom: GAP * 3,
              }}
            >
              {childFolders.map((folder) => (
                <FolderTile key={folder.id} folder={folder} size={tileSize} />
              ))}
            </div>
          </>
        )}
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

      <DeleteFromDiskModal
        open={showDeleteFromDiskModal}
        fileIds={Array.from(selectedIds)}
        onClose={() => setShowDeleteFromDiskModal(false)}
      />
    </div>
  )
}
