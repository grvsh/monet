import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listRootFolders, deleteRootFolder, updateRootFolder } from '../../api/rootFolders'
import { triggerScan, getRootScanStatus, getProcessingStatus } from '../../api/index'
import type { ProcessingStatusResponse } from '../../api/index'
import type { RootFolderResponse, ScanJobResponse } from '../../types/api'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Badge } from '../ui/Badge'
import { Spinner } from '../ui/Spinner'
import AddRootFolderModal from './AddRootFolderModal'
import { formatDateTime } from '../../lib/utils'
import { Pencil, Trash2, RefreshCw, Check, X, ChevronDown, ChevronRight } from 'lucide-react'

interface ScanStatusBadge {
  rootFolderId: string
}

function ScanStatus({ rootFolderId }: ScanStatusBadge) {
  const [scanPolling, setScanPolling] = useState(true)
  const [assetPolling, setAssetPolling] = useState(true)
  const [mlPolling, setMlPolling] = useState(true)
  const [captionPolling, setCaptionPolling] = useState(true)
  const [showFailures, setShowFailures] = useState(false)

  const { data: job } = useQuery<ScanJobResponse>({
    queryKey: ['scan-status', rootFolderId],
    queryFn: () => getRootScanStatus(rootFolderId),
    refetchInterval: scanPolling ? 1000 : false,
  })

  // Reset all polling whenever a new scan job starts
  const jobId = job?.id
  useEffect(() => {
    setScanPolling(true)
    setAssetPolling(true)
    setMlPolling(true)
    setCaptionPolling(true)
  }, [jobId])

  const { data: processing } = useQuery<ProcessingStatusResponse>({
    queryKey: ['processing-status', rootFolderId],
    queryFn: () => getProcessingStatus(rootFolderId),
    refetchInterval: (assetPolling || mlPolling || captionPolling) ? 2000 : false,
  })

  const scanDone = job?.status === 'completed' || job?.status === 'failed'
  const assetsDone = processing != null && processing.total > 0 && processing.pending === 0
  const mlTotal = processing?.ml_total ?? 0
  const mlDone = processing?.ml_done ?? 0
  const mlPending = processing?.ml_pending ?? 0
  const mlActive = mlTotal > 0
  const mlDoneAll = mlActive && mlPending === 0
  const captionPending = processing?.caption_pending ?? 0
  const captionActive = captionPending > 0
  const fullyDone = scanDone && assetsDone && (!mlActive || mlDoneAll) && !captionActive

  useEffect(() => { if (scanDone) setScanPolling(false) }, [scanDone])
  useEffect(() => { if (assetsDone) setAssetPolling(false) }, [assetsDone])
  useEffect(() => { if (mlDoneAll) setMlPolling(false) }, [mlDoneAll])
  useEffect(() => { if (!captionActive && processing != null) setCaptionPolling(false) }, [captionActive, processing])

  if (!job) return null

  const isRunning = job.status === 'running'
  const isQueued = isRunning && job.folders_scanned === 0 && job.files_found === 0
  const assetsRunning = (processing?.total ?? 0) > 0 && !assetsDone
  const mlRunning = mlActive && !mlDoneAll

  const badgeVariant = isQueued ? 'neutral'
    : isRunning || assetsRunning || mlRunning || captionActive ? 'blue'
    : job.status === 'failed' ? 'red'
    : 'green'
  const badgeLabel = isQueued ? 'queued'
    : isRunning ? 'scanning'
    : assetsRunning ? 'processing'
    : mlRunning ? 'analyzing'
    : captionActive ? 'captioning'
    : job.status === 'failed' ? 'failed'
    : 'completed'

  const folderFound = Math.max(job.folders_found, job.folders_scanned)
  const assetTotal = processing?.total ?? 0
  const assetProcessed = processing?.processed ?? 0
  const failedFiles = processing?.failed_files ?? []

  return (
    <div className="mt-2 rounded border border-neutral-700 bg-neutral-800/50 px-3 py-2.5 text-xs space-y-1.5">

      {/* Status + completion timestamp on one line */}
      <div className="flex items-center gap-2">
        {(isRunning || assetsRunning || mlRunning || captionActive) && !isQueued && <Spinner size="sm" />}
        <Badge variant={badgeVariant}>{badgeLabel}</Badge>
        {fullyDone && (
          <span className="text-neutral-500">Completed {formatDateTime(job.completed_at)}</span>
        )}
      </div>

      {/* All progress counters on a single line, pipe-separated groups */}
      {(isRunning || scanDone) && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-neutral-500">
          {/* Scan */}
          <span>
            Folders <span className="text-neutral-300">{job.folders_scanned.toLocaleString()}/{folderFound.toLocaleString()}</span>
          </span>
          <span className="text-neutral-700">·</span>
          <span>
            Files <span className="text-neutral-300">{job.files_found.toLocaleString()}</span>
            {job.files_new > 0 && <span className="text-neutral-400"> (+{job.files_new.toLocaleString()} new)</span>}
            {job.files_deleted > 0 && <span className="text-neutral-400"> (−{job.files_deleted.toLocaleString()})</span>}
          </span>

          {/* Asset processing */}
          {assetTotal > 0 && <>
            <span className="text-neutral-700">·</span>
            <span>
              Processed <span className="text-neutral-300">{assetProcessed.toLocaleString()}/{assetTotal.toLocaleString()}</span>
            </span>
          </>}

          {/* AI analysis */}
          {mlActive && <>
            <span className="text-neutral-700">·</span>
            <span>
              AI <span className="text-neutral-300">{mlDone.toLocaleString()}/{mlTotal.toLocaleString()}</span>
            </span>
          </>}

          {/* Captions */}
          {captionActive && <>
            <span className="text-neutral-700">·</span>
            <span>
              Captions <span className="text-neutral-300">{captionPending.toLocaleString()} left</span>
            </span>
          </>}

          {/* Asset failures — expandable because we have per-file details */}
          {failedFiles.length > 0 && <>
            <span className="text-neutral-700">·</span>
            <button
              className="flex items-center gap-1 text-red-400 hover:text-red-300"
              onClick={() => setShowFailures(v => !v)}
            >
              {showFailures ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
              {failedFiles.length} failed
            </button>
          </>}
          {/* ML failures — count only, no per-file detail stored */}
          {(processing?.ml_failed ?? 0) > 0 && <>
            <span className="text-neutral-700">·</span>
            <span className="text-red-400">{(processing?.ml_failed ?? 0).toLocaleString()} AI failed</span>
          </>}
        </div>
      )}

      {/* Failed file list (expandable) */}
      {showFailures && failedFiles.length > 0 && (
        <div className="rounded border border-red-900/40 bg-red-950/20 p-2 space-y-1 max-h-40 overflow-y-auto">
          {failedFiles.map(f => (
            <div key={f.id} className="space-y-0.5">
              <p className="font-mono text-neutral-400 truncate">{f.path}</p>
              <p className="text-red-400">{f.error}</p>
            </div>
          ))}
        </div>
      )}

      {job.error_message && (
        <p className="text-red-400">{job.error_message}</p>
      )}
    </div>
  )
}

interface FolderRowProps {
  folder: RootFolderResponse
}

function FolderRow({ folder }: FolderRowProps) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState(folder.name)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [showScanStatus, setShowScanStatus] = useState(true)

  const updateMutation = useMutation({
    mutationFn: (name: string) => updateRootFolder(folder.id, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['root-folders'] })
      setEditing(false)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => deleteRootFolder(folder.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['root-folders'] })
      queryClient.invalidateQueries({ queryKey: ['root-prefs'] })
    },
  })

  const scanMutation = useMutation({
    mutationFn: () => triggerScan(folder.id),
    onSuccess: () => {
      setShowScanStatus(true)
      queryClient.invalidateQueries({ queryKey: ['scan-status', folder.id] })
    },
  })

  return (
    <div className="rounded-lg border border-neutral-700 bg-neutral-900 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="flex items-center gap-2">
              <Input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className="text-sm py-1"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter') updateMutation.mutate(editName)
                  if (e.key === 'Escape') {
                    setEditName(folder.name)
                    setEditing(false)
                  }
                }}
              />
              <button
                onClick={() => updateMutation.mutate(editName)}
                disabled={updateMutation.isPending}
                className="text-green-400 hover:text-green-300"
                aria-label="Save"
              >
                <Check size={15} />
              </button>
              <button
                onClick={() => {
                  setEditName(folder.name)
                  setEditing(false)
                }}
                className="text-neutral-400 hover:text-neutral-200"
                aria-label="Cancel"
              >
                <X size={15} />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-neutral-100">{folder.name}</h3>
              {folder.parent_root_id && <Badge variant="blue">linked</Badge>}
              {!folder.is_active && <Badge variant="yellow">Inactive</Badge>}
            </div>
          )}
          <p className="text-xs text-neutral-500 mt-0.5 font-mono truncate">{folder.path}</p>
          {folder.last_scanned_at && (
            <p className="text-xs text-neutral-600 mt-0.5">
              Last scanned: {formatDateTime(folder.last_scanned_at)}
            </p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              scanMutation.mutate()
            }}
            loading={scanMutation.isPending}
            title="Scan now"
          >
            <RefreshCw size={13} />
            Scan
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setEditing(true)}
            title="Edit name"
          >
            <Pencil size={13} />
          </Button>
          {confirmDelete ? (
            <div className="flex items-center gap-1">
              <span className="text-xs text-red-400">Confirm?</span>
              <Button
                variant="danger"
                size="sm"
                onClick={() => deleteMutation.mutate()}
                loading={deleteMutation.isPending}
              >
                Delete
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setConfirmDelete(false)}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmDelete(true)}
              title="Remove"
              className="text-red-400 hover:text-red-300"
            >
              <Trash2 size={13} />
            </Button>
          )}
        </div>
      </div>

      {/* Scan status */}
      {showScanStatus && <ScanStatus rootFolderId={folder.id} />}
    </div>
  )
}

export default function RootFolderAdmin() {
  const [showAddModal, setShowAddModal] = useState(false)

  const { data: rootFolders, isLoading } = useQuery({
    queryKey: ['root-folders'],
    queryFn: listRootFolders,
  })

  if (isLoading) {
    return (
      <div className="flex justify-center py-6">
        <Spinner />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Folder list */}
      {!rootFolders || rootFolders.length === 0 ? (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 px-4 py-8 text-center">
          <p className="text-sm text-neutral-500">No root folders configured yet.</p>
          <p className="text-xs text-neutral-600 mt-1">
            Add a root folder to start indexing your media.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {rootFolders.map((folder) => (
            <FolderRow key={folder.id} folder={folder} />
          ))}
        </div>
      )}

      {/* Add button */}
      <Button variant="primary" onClick={() => setShowAddModal(true)}>
        + Add Root Folder
      </Button>

      <AddRootFolderModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
      />
    </div>
  )
}
