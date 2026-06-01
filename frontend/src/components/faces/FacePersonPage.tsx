import { useState, useRef, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Pencil, Check, X, GitMerge, Users } from 'lucide-react'
import { getPerson, getPersonFiles, updatePerson, mergePeople, listPeople } from '../../api/faces'
import type { PersonResponse } from '../../types/api'
import { useGalleryStore } from '../../store/gallery'
import MediaTile from '../gallery/MediaTile'
import MediaLightbox from '../lightbox/MediaLightbox'
import { Spinner } from '../ui/Spinner'
import { Modal } from '../ui/Modal'
import { cn } from '../../lib/utils'

const TILE_SIZE = 200
const GAP = 4

// ---------------------------------------------------------------------------
// Inline name editor
// ---------------------------------------------------------------------------

function NameEditor({ person, onSaved }: { person: PersonResponse; onSaved: (name: string | null) => void }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(person.name ?? '')
  const inputRef = useRef<HTMLInputElement>(null)

  const mutation = useMutation({
    mutationFn: (name: string | null) => updatePerson(person.id, name),
    onSuccess: (updated) => {
      setEditing(false)
      onSaved(updated.name)
    },
  })

  function startEdit() {
    setValue(person.name ?? '')
    setEditing(true)
    setTimeout(() => inputRef.current?.select(), 0)
  }

  function save() {
    const trimmed = value.trim() || null
    mutation.mutate(trimmed)
  }

  function cancel() {
    setEditing(false)
    setValue(person.name ?? '')
  }

  if (editing) {
    return (
      <div className="flex items-center gap-2">
        <input
          ref={inputRef}
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save()
            if (e.key === 'Escape') cancel()
          }}
          placeholder="Enter name…"
          className="rounded border border-neutral-600 bg-neutral-800 px-2 py-1 text-lg font-semibold text-neutral-100 focus:outline-none focus:ring-1 focus:ring-blue-500 min-w-0 w-48"
        />
        <button
          type="button"
          onClick={save}
          disabled={mutation.isPending}
          className="text-green-400 hover:text-green-300 transition-colors"
          aria-label="Save"
        >
          {mutation.isPending ? <Spinner size="sm" /> : <Check size={16} />}
        </button>
        <button
          type="button"
          onClick={cancel}
          className="text-neutral-500 hover:text-neutral-300 transition-colors"
          aria-label="Cancel"
        >
          <X size={16} />
        </button>
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={startEdit}
      className="group flex items-center gap-2"
      title="Click to set name"
    >
      <span className={cn('text-lg font-semibold', person.name ? 'text-neutral-100' : 'text-neutral-500 italic')}>
        {person.name ?? 'Unnamed person'}
      </span>
      <Pencil size={14} className="text-neutral-600 group-hover:text-neutral-400 transition-colors" />
    </button>
  )
}

// ---------------------------------------------------------------------------
// Merge modal
// ---------------------------------------------------------------------------

function MergeModal({
  open,
  onClose,
  currentPersonId,
  onMerged,
}: {
  open: boolean
  onClose: () => void
  currentPersonId: string
  onMerged: () => void
}) {
  const { data } = useQuery({
    queryKey: ['people'],
    queryFn: listPeople,
    enabled: open,
  })

  const [selectedId, setSelectedId] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () => mergePeople(currentPersonId, selectedId!),
    onSuccess: () => {
      onClose()
      onMerged()
    },
  })

  const candidates = (data?.people ?? []).filter((p) => p.id !== currentPersonId)

  return (
    <Modal open={open} onClose={onClose} title="Merge into another person">
      <div className="space-y-3">
        <p className="text-sm text-neutral-400">
          All photos of this person will be moved to the selected person, and this entry will be removed.
        </p>

        {candidates.length === 0 ? (
          <p className="text-sm text-neutral-500 py-4 text-center">No other people to merge into.</p>
        ) : (
          <ul className="space-y-1 max-h-64 overflow-y-auto">
            {candidates.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(p.id)}
                  className={cn(
                    'w-full flex items-center gap-3 rounded px-3 py-2 text-left transition-colors',
                    selectedId === p.id
                      ? 'bg-blue-900/40 text-blue-100 ring-1 ring-inset ring-blue-700/40'
                      : 'hover:bg-neutral-800 text-neutral-300'
                  )}
                >
                  {p.sample_thumbnail_urls[0] ? (
                    <img src={p.sample_thumbnail_urls[0]} alt="" className="w-8 h-8 rounded object-cover shrink-0" />
                  ) : (
                    <div className="w-8 h-8 rounded bg-neutral-700 shrink-0 flex items-center justify-center">
                      <Users size={14} className="text-neutral-500" />
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className={cn('text-sm font-medium truncate', p.name ? '' : 'italic text-neutral-500')}>
                      {p.name ?? 'Unnamed person'}
                    </p>
                    <p className="text-xs text-neutral-500">{p.face_count.toLocaleString()} photos</p>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="flex justify-end gap-3 pt-2 border-t border-neutral-800">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-neutral-400 hover:text-neutral-200 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => mutation.mutate()}
            disabled={!selectedId || mutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {mutation.isPending ? <Spinner size="sm" /> : <GitMerge size={13} />}
            Merge
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function FacePersonPage() {
  const { personId } = useParams<{ personId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const lightboxIndex = useGalleryStore((s) => s.lightboxIndex)
  const setLightboxIndex = useGalleryStore((s) => s.setLightboxIndex)
  const selectedIds = useGalleryStore((s) => s.selectedIds)
  const toggleSelection = useGalleryStore((s) => s.toggleSelection)

  const [mergeOpen, setMergeOpen] = useState(false)
  const [localName, setLocalName] = useState<string | null | undefined>(undefined)

  useEffect(() => { setLightboxIndex(-1) }, [setLightboxIndex])

  const { data: person, isLoading: personLoading } = useQuery({
    queryKey: ['person', personId],
    queryFn: () => getPerson(personId!),
    enabled: !!personId,
  })

  const { data: filesData, isLoading: filesLoading } = useQuery({
    queryKey: ['person-files', personId],
    queryFn: () => getPersonFiles(personId!),
    enabled: !!personId,
  })

  const files = filesData?.items ?? []
  const displayName = localName !== undefined ? localName : person?.name ?? null

  if (personLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Spinner size="lg" />
      </div>
    )
  }

  if (!person) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-neutral-400 text-sm">Person not found.</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-neutral-800 shrink-0 flex items-center gap-3">
        <button
          type="button"
          onClick={() => navigate('/faces')}
          className="text-neutral-500 hover:text-neutral-200 transition-colors shrink-0"
          aria-label="Back to people"
        >
          <ArrowLeft size={16} />
        </button>

        <div className="flex-1 min-w-0">
          <NameEditor
            person={{ ...person, name: displayName }}
            onSaved={(name) => {
              setLocalName(name)
              queryClient.invalidateQueries({ queryKey: ['people'] })
              queryClient.invalidateQueries({ queryKey: ['person', personId] })
            }}
          />
          {!filesLoading && (
            <p className="text-xs text-neutral-500">
              {filesData?.total ?? 0} {(filesData?.total ?? 0) === 1 ? 'photo' : 'photos'}
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={() => setMergeOpen(true)}
          className="flex items-center gap-1.5 rounded px-2.5 py-1.5 text-xs text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800 border border-neutral-700 transition-colors shrink-0"
          title="Merge this person into another"
        >
          <GitMerge size={13} />
          Merge
        </button>
      </div>

      {/* Gallery */}
      <div className="flex-1 overflow-y-auto bg-neutral-950 p-2">
        {filesLoading && (
          <div className="flex items-center justify-center h-64">
            <Spinner size="lg" />
          </div>
        )}

        {!filesLoading && files.length === 0 && (
          <div className="flex items-center justify-center h-64">
            <p className="text-neutral-500 text-sm">No photos found for this person.</p>
          </div>
        )}

        {files.length > 0 && (
          <div className="flex flex-wrap" style={{ gap: GAP }}>
            {files.map((file, index) => (
              <div key={file.id} style={{ width: TILE_SIZE, height: TILE_SIZE + 52, flexShrink: 0 }}>
                <MediaTile
                  file={file}
                  imageSize={TILE_SIZE}
                  onClick={() => setLightboxIndex(index)}
                  selected={selectedIds.has(file.id)}
                  anySelected={selectedIds.size > 0}
                  onSelect={(id) => toggleSelection(id)}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {lightboxIndex >= 0 && files.length > 0 && (
        <MediaLightbox
          files={files}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(-1)}
        />
      )}

      <MergeModal
        open={mergeOpen}
        onClose={() => setMergeOpen(false)}
        currentPersonId={personId!}
        onMerged={() => {
          queryClient.invalidateQueries({ queryKey: ['people'] })
          navigate('/faces')
        }}
      />
    </div>
  )
}
