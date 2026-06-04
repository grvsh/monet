import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listRootFolders, getRootPrefs, updateRootPrefs, getRootFolderStats } from '../../api/rootFolders'
import type { RootPrefItem, RootFolderStats } from '../../types/api'
import { Toggle } from '../ui/Toggle'
import { Spinner } from '../ui/Spinner'

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

function FolderStatsBadge({ stats }: { stats: RootFolderStats }) {
  if (stats.total_count === 0) {
    return <span className="text-xs text-neutral-600">No files</span>
  }
  const parts: string[] = []
  if (stats.image_count > 0) parts.push(`${formatCount(stats.image_count)} photos`)
  if (stats.video_count > 0) parts.push(`${formatCount(stats.video_count)} videos`)
  if (stats.audio_count > 0) parts.push(`${formatCount(stats.audio_count)} audio`)
  return <span className="text-xs text-neutral-500">{parts.join(' · ')}</span>
}

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

  const { data: statsData, isLoading: loadingStats } = useQuery({
    queryKey: ['root-folder-stats'],
    queryFn: getRootFolderStats,
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

  if (loadingFolders || loadingPrefs || loadingStats) {
    return (
      <div className="flex justify-center py-6">
        <Spinner />
      </div>
    )
  }

  if (!rootFolders || rootFolders.length === 0) {
    return <p className="text-sm text-neutral-500">No root folders configured yet.</p>
  }

  const prefMap = new Map((prefsData?.prefs ?? []).map((p) => [p.root_folder_id, p.is_visible]))
  const statsMap = new Map((statsData ?? []).map((s) => [s.root_folder_id, s]))

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

  const visibleFolders = rootFolders.filter((f) => prefMap.get(f.id) !== false)

  let totalFiles = 0, imageCount = 0, videoCount = 0, audioCount = 0
  for (const f of visibleFolders) {
    const s = statsMap.get(f.id)
    if (s) {
      totalFiles += s.total_count
      imageCount += s.image_count
      videoCount += s.video_count
      audioCount += s.audio_count
    }
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 divide-y divide-neutral-800">
        {rootFolders.map((folder) => {
          const isVisible = prefMap.get(folder.id) !== false
          const folderStats = statsMap.get(folder.id)
          return (
            <div key={folder.id} className="flex items-center justify-between px-4 py-3">
              <div className="min-w-0 flex-1 mr-4">
                <p className="text-sm font-medium text-neutral-200 truncate">{folder.name}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  <p className="text-xs text-neutral-500 truncate">{folder.path}</p>
                  {folderStats && (
                    <>
                      <span className="text-neutral-700">·</span>
                      <FolderStatsBadge stats={folderStats} />
                    </>
                  )}
                </div>
              </div>
              <Toggle
                checked={isVisible}
                onChange={(checked) => handleToggle(folder.id, checked)}
                disabled={mutation.isPending}
              />
            </div>
          )
        })}

        {/* Aggregate summary for all visible folders */}
        {totalFiles > 0 && (
          <div className="px-4 py-3 bg-neutral-800/40">
            <p className="text-xs font-medium text-neutral-400 mb-2">
              Visible total — {visibleFolders.length} of {rootFolders.length} folder{rootFolders.length !== 1 ? 's' : ''}
            </p>
            <div className="flex flex-wrap gap-x-5 gap-y-1">
              <div>
                <p className="text-xs text-neutral-500 uppercase tracking-wide">Files</p>
                <p className="text-sm font-semibold text-neutral-100">{formatCount(totalFiles)}</p>
              </div>
              {imageCount > 0 && (
                <div>
                  <p className="text-xs text-neutral-500 uppercase tracking-wide">Photos</p>
                  <p className="text-sm font-semibold text-neutral-100">{formatCount(imageCount)}</p>
                </div>
              )}
              {videoCount > 0 && (
                <div>
                  <p className="text-xs text-neutral-500 uppercase tracking-wide">Videos</p>
                  <p className="text-sm font-semibold text-neutral-100">{formatCount(videoCount)}</p>
                </div>
              )}
              {audioCount > 0 && (
                <div>
                  <p className="text-xs text-neutral-500 uppercase tracking-wide">Audio</p>
                  <p className="text-sm font-semibold text-neutral-100">{formatCount(audioCount)}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
