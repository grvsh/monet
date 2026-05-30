import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { Modal } from '../ui/Modal'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { bulkDeleteFromDisk } from '../../api/files'
import { useGalleryStore } from '../../store/gallery'

const CONFIRM_PHRASE = 'Delete permanently'

interface DeleteFromDiskModalProps {
  open: boolean
  fileIds: string[]
  onClose: () => void
}

export default function DeleteFromDiskModal({ open, fileIds, onClose }: DeleteFromDiskModalProps) {
  const [confirmText, setConfirmText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const clearSelection = useGalleryStore((s) => s.clearSelection)
  const queryClient = useQueryClient()

  const count = fileIds.length

  const { mutate, isPending } = useMutation({
    mutationFn: () => bulkDeleteFromDisk(fileIds),
    onSuccess: () => {
      clearSelection()
      queryClient.invalidateQueries({ queryKey: ['folder-files'] })
      queryClient.invalidateQueries({ queryKey: ['folder-children'] })
      queryClient.invalidateQueries({ queryKey: ['root-level-folders'] })
      handleClose()
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to delete files'
      setError(typeof msg === 'string' ? msg : 'Failed to delete files')
    },
  })

  function handleClose() {
    setConfirmText('')
    setError(null)
    onClose()
  }

  const confirmed = confirmText === CONFIRM_PHRASE

  return (
    <Modal open={open} onClose={handleClose} title="Delete" size="sm">
      <div className="space-y-4">
        <div className="flex gap-3 p-3 rounded-lg bg-red-950/40 border border-red-800/50">
          <AlertTriangle size={18} className="shrink-0 text-red-400 mt-0.5" />
          <div className="text-sm text-red-300 space-y-1">
            <p className="font-medium">This action cannot be undone.</p>
            <p className="text-red-400/80">
              {count === 1 ? '1 file' : `${count} files`} will be permanently deleted from disk,
              including all thumbnails and metadata. They cannot be recovered.
            </p>
          </div>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs text-neutral-400">
            Type <span className="font-mono text-neutral-200">{CONFIRM_PHRASE}</span> to confirm
          </label>
          <Input
            id="delete-confirm"
            type="text"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder={CONFIRM_PHRASE}
            autoComplete="off"
            autoFocus
          />
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        <div className="flex gap-3 justify-end pt-1">
          <Button variant="secondary" type="button" onClick={handleClose} disabled={isPending}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => mutate()}
            disabled={!confirmed || isPending}
            loading={isPending}
            className="bg-red-700 hover:bg-red-600 disabled:bg-red-900 text-white border-0"
          >
            Delete permanently
          </Button>
        </div>
      </div>
    </Modal>
  )
}
