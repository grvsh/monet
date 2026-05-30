import { Image, Video, Music } from 'lucide-react'
import { cn } from '../../lib/utils'

type MediaType = 'all' | 'image' | 'video' | 'audio'

interface TypeCounts {
  image: number
  video: number
  audio: number
}

interface MediaTypeTabsProps {
  value: MediaType
  typeCounts?: TypeCounts
  onChange: (v: MediaType) => void
}

const TABS: { label: string; value: MediaType; icon?: React.ReactNode }[] = [
  { label: 'All', value: 'all' },
  { label: 'Photos', value: 'image', icon: <Image size={12} /> },
  { label: 'Videos', value: 'video', icon: <Video size={12} /> },
  { label: 'Audio',  value: 'audio', icon: <Music size={12} /> },
]

export default function MediaTypeTabs({ value, typeCounts, onChange }: MediaTypeTabsProps) {
  const visibleTabs = TABS.filter((tab) => {
    if (tab.value === 'all') return true
    if (!typeCounts) return true
    return typeCounts[tab.value as 'image' | 'video' | 'audio'] > 0
  })

  return (
    <div className="flex items-center gap-1 bg-neutral-800 rounded p-0.5 shrink-0">
      {visibleTabs.map((tab) => {
        const count =
          tab.value === 'all'
            ? (typeCounts ? typeCounts.image + typeCounts.video + typeCounts.audio : null)
            : typeCounts?.[tab.value as 'image' | 'video' | 'audio'] ?? null

        return (
          <button
            key={tab.value}
            type="button"
            title={tab.label}
            onClick={() => onChange(tab.value)}
            className={cn(
              'flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium transition-colors',
              value === tab.value
                ? 'bg-neutral-700 text-neutral-100'
                : 'text-neutral-400 hover:text-neutral-200'
            )}
          >
            {tab.icon ?? tab.label}
            {count !== null && (
              <span className="text-neutral-500">
                {count.toLocaleString()}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
