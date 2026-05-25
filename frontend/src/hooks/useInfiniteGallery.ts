import { useQuery } from '@tanstack/react-query'
import { listFolderFiles } from '../api/folders'
import { useGalleryStore } from '../store/gallery'
import type { PaginatedFiles } from '../types/api'

interface UseGalleryOptions {
  folderId: string | null
  enabled?: boolean
}

/**
 * Fetches a paginated list of files for a given folder.
 * Uses gallery store for sort/filter preferences.
 */
export function useGallery({ folderId, enabled = true }: UseGalleryOptions): {
  data: PaginatedFiles | undefined
  isLoading: boolean
  error: Error | null
} {
  const sortField = useGalleryStore((s) => s.sortField)
  const sortOrder = useGalleryStore((s) => s.sortOrder)
  const mediaTypeFilter = useGalleryStore((s) => s.mediaTypeFilter)

  const { data, isLoading, error } = useQuery({
    queryKey: ['folder-files', folderId, sortField, sortOrder, mediaTypeFilter],
    queryFn: () =>
      listFolderFiles(folderId!, {
        page: 1,
        page_size: 1000,
        sort: sortField,
        order: sortOrder,
        media_type: mediaTypeFilter,
      }),
    enabled: enabled && !!folderId,
  })

  return { data, isLoading, error: error as Error | null }
}
