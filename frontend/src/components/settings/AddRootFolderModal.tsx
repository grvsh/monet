import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createRootFolder } from '../../api/rootFolders'
import { Modal } from '../ui/Modal'
import { Input } from '../ui/Input'
import { Button } from '../ui/Button'
import DirectoryBrowser from './DirectoryBrowser'
import { basename } from '../../lib/utils'

interface AddRootFolderModalProps {
  open: boolean
  onClose: () => void
}

export default function AddRootFolderModal({ open, onClose }: AddRootFolderModalProps) {
  const queryClient = useQueryClient()
  const [path, setPath] = useState('')
  const [name, setName] = useState('')
  const [showBrowser, setShowBrowser] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (effectiveName: string) => createRootFolder(effectiveName, path.trim()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['root-folders'] })
      queryClient.invalidateQueries({ queryKey: ['root-prefs'] })
      handleClose()
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Failed to add root folder'
      setError(typeof msg === 'string' ? msg : 'Failed to add root folder')
    },
  })

  function handleClose() {
    setPath('')
    setName('')
    setShowBrowser(false)
    setError(null)
    onClose()
  }

  function handleBrowserSelect(selected: string) {
    setPath(selected)
    if (!name || name === basename(path) || name === path) {
      setName(basename(selected) || selected)
    }
    setShowBrowser(false)
    setError(null)
  }

  function handleAdd() {
    if (!path.trim()) {
      setError('Please enter a path.')
      return
    }
    const effectiveName = name.trim() || basename(path.trim()) || path.trim()
    setName(effectiveName)
    setError(null)
    mutation.mutate(effectiveName)
  }

  return (
    <Modal open={open} onClose={handleClose} title="Add Root Folder" size="lg">
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-1">
          <Input
            id="root-folder-path"
            label="Path"
            value={path}
            onChange={(e) => {
              setPath(e.target.value)
              setError(null)
            }}
            placeholder="/mnt/photos"
            autoFocus
          />
          <button
            type="button"
            onClick={() => setShowBrowser((v) => !v)}
            className="self-start text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            {showBrowser ? 'Hide browser' : 'Browse filesystem…'}
          </button>
        </div>

        {showBrowser && (
          <DirectoryBrowser onSelect={handleBrowserSelect} />
        )}

        <Input
          id="root-folder-name"
          label="Display name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. My Photos"
        />

        {error && (
          <p className="text-sm text-red-400">{error}</p>
        )}

        <div className="flex gap-3 justify-end">
          <Button variant="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleAdd}
            loading={mutation.isPending}
            disabled={!path.trim()}
          >
            Add Root Folder
          </Button>
        </div>
      </div>
    </Modal>
  )
}
