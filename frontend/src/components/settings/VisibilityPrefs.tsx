import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listRootFolders, getRootPrefs, updateRootPrefs } from '../../api/rootFolders'
import type { RootPrefItem } from '../../types/api'
import { Toggle } from '../ui/Toggle'
import { Spinner } from '../ui/Spinner'

export default function VisibilityPrefs() {
  const queryClient = useQueryClient()

  const { data: rootFolders, isLoading: loadingFolders } = useQuery({
    queryKey: ['root-folders'],
    queryFn: listRootFolders,
  })

  const { data: prefsData, isLoading: loadingPrefs } = useQuery({
    queryKey: ['root-prefs'],
    queryFn: getRootPrefs,
  })

  const mutation = useMutation({
    mutationFn: (prefs: RootPrefItem[]) => updateRootPrefs(prefs),
    onMutate: async (newPrefs) => {
      await queryClient.cancelQueries({ queryKey: ['root-prefs'] })
      const previous = queryClient.getQueryData(['root-prefs'])
      queryClient.setQueryData(['root-prefs'], { prefs: newPrefs })
      return { previous }
    },
    onError: (_err, _vars, context) => {
      queryClient.setQueryData(['root-prefs'], context?.previous)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['root-prefs'] })
    },
  })

  if (loadingFolders || loadingPrefs) {
    return (
      <div className="flex justify-center py-6">
        <Spinner />
      </div>
    )
  }

  if (!rootFolders || rootFolders.length === 0) {
    return (
      <p className="text-sm text-neutral-500">No root folders configured yet.</p>
    )
  }

  const prefMap = new Map((prefsData?.prefs ?? []).map((p) => [p.root_folder_id, p.is_visible]))

  function handleToggle(folderId: string, visible: boolean) {
    const currentPrefs = prefsData?.prefs ?? []
    const existing = currentPrefs.find((p) => p.root_folder_id === folderId)

    let updated: RootPrefItem[]
    if (existing) {
      updated = currentPrefs.map((p) =>
        p.root_folder_id === folderId ? { ...p, is_visible: visible } : p
      )
    } else {
      updated = [...currentPrefs, { root_folder_id: folderId, is_visible: visible }]
    }

    mutation.mutate(updated)
  }

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 divide-y divide-neutral-800">
      {rootFolders.map((folder) => {
        const isVisible = prefMap.get(folder.id) !== false
        return (
          <div
            key={folder.id}
            className="flex items-center justify-between px-4 py-3"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium text-neutral-200 truncate">{folder.name}</p>
              <p className="text-xs text-neutral-500 truncate">{folder.path}</p>
            </div>
            <Toggle
              checked={isVisible}
              onChange={(checked) => handleToggle(folder.id, checked)}
              disabled={mutation.isPending}
            />
          </div>
        )
      })}
    </div>
  )
}
