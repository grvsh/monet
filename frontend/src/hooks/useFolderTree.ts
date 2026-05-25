import { useQuery } from '@tanstack/react-query'
import { listRootFolders, getRootPrefs } from '../api/rootFolders'
import type { RootFolderResponse } from '../types/api'

/**
 * Returns visible root folders for the current user.
 * Merges the root folder list with user prefs — a folder absent from prefs defaults to visible.
 */
export function useFolderTree(): {
  visibleRootFolders: RootFolderResponse[]
  isLoading: boolean
  error: Error | null
} {
  const {
    data: rootFolders,
    isLoading: loadingFolders,
    error: foldersError,
  } = useQuery({
    queryKey: ['root-folders'],
    queryFn: listRootFolders,
  })

  const {
    data: prefsData,
    isLoading: loadingPrefs,
    error: prefsError,
  } = useQuery({
    queryKey: ['root-prefs'],
    queryFn: getRootPrefs,
  })

  const visibleRootFolders: RootFolderResponse[] = (() => {
    if (!rootFolders) return []
    if (!prefsData) return rootFolders.filter((f) => f.is_active)

    const prefMap = new Map(prefsData.prefs.map((p) => [p.root_folder_id, p.is_visible]))

    return rootFolders.filter((folder) => {
      if (!folder.is_active) return false
      // If no pref row, default is visible
      return prefMap.get(folder.id) !== false
    })
  })()

  return {
    visibleRootFolders,
    isLoading: loadingFolders || loadingPrefs,
    error: (foldersError ?? prefsError) as Error | null,
  }
}
