import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Users, RefreshCw, Check } from 'lucide-react'
import { listPeople, triggerCluster } from '../../api/faces'
import type { PersonResponse } from '../../types/api'
import { Spinner } from '../ui/Spinner'
import { cn } from '../../lib/utils'

function PersonCard({ person }: { person: PersonResponse }) {
  const navigate = useNavigate()
  const samples = person.sample_thumbnail_urls.slice(0, 4)

  return (
    <button
      type="button"
      onClick={() => navigate(`/faces/${person.id}`)}
      className="group flex flex-col rounded-lg overflow-hidden border border-neutral-800 bg-neutral-900 hover:border-neutral-600 transition-colors text-left"
    >
      {/* 2×2 thumbnail grid */}
      <div className="grid grid-cols-2 gap-0.5 bg-neutral-800 aspect-square">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="bg-neutral-800 overflow-hidden">
            {samples[i] ? (
              <img
                src={samples[i]}
                alt=""
                className="w-full h-full object-cover"
                loading="lazy"
              />
            ) : (
              <div className="w-full h-full bg-neutral-800 flex items-center justify-center">
                <Users size={20} className="text-neutral-700" />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Name + count */}
      <div className="px-3 py-2.5">
        <p className={cn('text-sm font-medium truncate', person.name ? 'text-neutral-100' : 'text-neutral-500 italic')}>
          {person.name ?? 'Unnamed person'}
        </p>
        <p className="text-xs text-neutral-500 mt-0.5">
          {person.face_count.toLocaleString()} {person.face_count === 1 ? 'photo' : 'photos'}
        </p>
      </div>
    </button>
  )
}

export default function FacesPage() {
  const queryClient = useQueryClient()
  const [clustered, setClustered] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['people'],
    queryFn: listPeople,
    staleTime: 60_000,
  })

  const clusterMutation = useMutation({
    mutationFn: triggerCluster,
    onSuccess: () => {
      setClustered(true)
      setTimeout(() => {
        setClustered(false)
        queryClient.invalidateQueries({ queryKey: ['people'] })
      }, 3000)
    },
  })

  const people = data?.people ?? []

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-6 py-4 border-b border-neutral-800 shrink-0 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-neutral-100">People</h1>
          {!isLoading && (
            <p className="text-xs text-neutral-500 mt-0.5">
              {people.length} {people.length === 1 ? 'person' : 'people'} identified
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => clusterMutation.mutate()}
          disabled={clusterMutation.isPending || clustered}
          className={cn(
            'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
            clustered
              ? 'bg-green-900/40 text-green-400 border border-green-700/40'
              : 'bg-neutral-800 text-neutral-300 hover:bg-neutral-700 hover:text-neutral-100 border border-neutral-700'
          )}
          title="Re-run face clustering to update groups"
        >
          {clusterMutation.isPending ? (
            <Spinner size="sm" />
          ) : clustered ? (
            <Check size={13} />
          ) : (
            <RefreshCw size={13} />
          )}
          {clustered ? 'Queued' : 'Re-cluster'}
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading && (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        )}

        {error && (
          <div className="flex justify-center py-16">
            <p className="text-red-400 text-sm">Failed to load people.</p>
          </div>
        )}

        {!isLoading && !error && people.length === 0 && (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <Users size={48} className="text-neutral-700 mb-4" />
            <p className="text-neutral-400 text-sm font-medium">No people identified yet</p>
            <p className="text-neutral-600 text-xs mt-1 max-w-xs">
              Face detection runs automatically when photos are imported. Once enough
              faces are detected, click Re-cluster to group them into people.
            </p>
          </div>
        )}

        {people.length > 0 && (
          <div className="grid gap-4" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))' }}>
            {people.map((person) => (
              <PersonCard key={person.id} person={person} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
