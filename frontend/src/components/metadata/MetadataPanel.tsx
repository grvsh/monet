import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getFile } from '../../api/files'
import { formatBytes, formatDateTime } from '../../lib/utils'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { Spinner } from '../ui/Spinner'

interface MetadataPanelProps {
  fileId: string
}

interface MetaRow {
  label: string
  value: string | number | null | undefined
}

function MetaSection({ title, rows }: { title: string; rows: MetaRow[] }) {
  const visible = rows.filter((r) => r.value != null && r.value !== '')
  if (visible.length === 0) return null

  return (
    <div className="border-b border-neutral-800 py-3 px-4">
      <h4 className="text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2">
        {title}
      </h4>
      <dl className="space-y-1.5">
        {visible.map((row) => (
          <div key={row.label} className="flex justify-between gap-3 text-sm">
            <dt className="text-neutral-500 shrink-0">{row.label}</dt>
            <dd className="text-neutral-200 text-right break-all">{String(row.value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function ExifSection({ metadata }: { metadata: Record<string, unknown> | null }) {
  const [open, setOpen] = useState(false)

  if (!metadata || Object.keys(metadata).length === 0) return null

  return (
    <div className="py-3 px-4">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-xs font-semibold text-neutral-400 uppercase tracking-wider mb-2 w-full text-left"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        All EXIF / Metadata
      </button>
      {open && (
        <div className="max-h-64 overflow-y-auto rounded border border-neutral-800 bg-neutral-950 p-2">
          <dl className="space-y-1">
            {Object.entries(metadata).map(([key, val]) => (
              <div key={key} className="flex gap-2 text-xs">
                <dt className="text-neutral-500 shrink-0 min-w-0 break-all">{key}:</dt>
                <dd className="text-neutral-300 break-all">
                  {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  )
}

export default function MetadataPanel({ fileId }: MetadataPanelProps) {
  const { data: file, isLoading, error } = useQuery({
    queryKey: ['file', fileId],
    queryFn: () => getFile(fileId),
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Spinner />
      </div>
    )
  }

  if (error || !file) {
    return (
      <div className="px-4 py-6 text-sm text-red-400">Failed to load file details.</div>
    )
  }

  const gpsString =
    file.gps_lat != null && file.gps_lon != null
      ? `${Math.abs(file.gps_lat).toFixed(4)}°${file.gps_lat >= 0 ? 'N' : 'S'}, ${Math.abs(file.gps_lon).toFixed(4)}°${file.gps_lon >= 0 ? 'E' : 'W'}${file.gps_alt_m != null ? `, ${file.gps_alt_m.toFixed(0)}m` : ''}`
      : null

  return (
    <div className="text-sm">
      <MetaSection
        title="Camera"
        rows={[
          { label: 'Make', value: file.camera_make },
          { label: 'Model', value: file.camera_model },
          { label: 'Lens', value: file.lens_model },
          {
            label: 'Focal length',
            value: file.focal_length_mm != null ? `${file.focal_length_mm}mm` : null,
          },
          {
            label: 'Aperture',
            value: file.aperture != null ? `f/${file.aperture}` : null,
          },
          { label: 'Shutter speed', value: file.shutter_speed },
          { label: 'ISO', value: file.iso },
        ]}
      />

      <MetaSection
        title="Date & Time"
        rows={[
          { label: 'Taken', value: formatDateTime(file.taken_at) },
          { label: 'Indexed', value: formatDateTime(file.indexed_at) },
        ]}
      />

      <MetaSection
        title="Dimensions"
        rows={[
          {
            label: 'Resolution',
            value:
              file.width != null && file.height != null
                ? `${file.width} × ${file.height}px`
                : null,
          },
          {
            label: 'Duration',
            value:
              file.duration_sec != null
                ? `${Math.floor(file.duration_sec / 60)}m ${Math.floor(file.duration_sec % 60)}s`
                : null,
          },
          { label: 'Format', value: file.extension.toUpperCase() },
          { label: 'RAW', value: file.is_raw ? 'Yes' : null },
          { label: 'Orientation', value: file.orientation },
        ]}
      />

      <MetaSection
        title="File"
        rows={[
          { label: 'Filename', value: file.filename },
          { label: 'Size', value: formatBytes(file.size_bytes) },
          { label: 'Path', value: file.path },
          { label: 'MIME type', value: file.mime_type },
        ]}
      />

      {(gpsString || file.location) && (
        <MetaSection
          title="Location"
          rows={[
            { label: 'Place', value: file.location },
            { label: 'GPS', value: gpsString },
          ]}
        />
      )}

      <ExifSection metadata={file.metadata} />
    </div>
  )
}
