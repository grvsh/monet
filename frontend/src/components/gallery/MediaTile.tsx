import { useState, useRef, useEffect, useCallback } from 'react'
import { Music, Video, ImageOff, Download } from 'lucide-react'
import type { FileResponse } from '../../types/api'
import { formatDate, formatDuration } from '../../lib/utils'
import { Badge } from '../ui/Badge'
import { cn } from '../../lib/utils'
import { downloadFile } from '../../api/download'
import { FileThumbnail } from './FileThumbnail'

interface MediaTileProps {
  file: FileResponse
  onClick: () => void
  imageSize: number
  selected: boolean
  anySelected: boolean
  onSelect: (id: string, shiftKey: boolean) => void
  faceBbox?: { x: number; y: number; w: number; h: number } | null
}


function DownloadMenu({ file, onClose }: { file: FileResponse; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [onClose])

  const stem = file.filename.replace(/\.[^.]+$/, '')
  const ext = file.filename.split('.').pop()?.toUpperCase() ?? 'File'

  return (
    <div
      ref={ref}
      className="absolute top-full mt-1 right-0 bg-neutral-800 border border-neutral-700 rounded-lg shadow-xl py-1 min-w-[170px] z-50"
    >
      {file.has_preview && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            downloadFile(`/api/previews/${file.id}/download`, `${stem}_preview.jpg`)
            onClose()
          }}
          className="w-full text-left px-3 py-2 text-sm text-neutral-200 hover:bg-neutral-700 transition-colors"
        >
          Preview (JPEG)
        </button>
      )}
      <button
        onClick={(e) => {
          e.stopPropagation()
          downloadFile(`/api/original/${file.id}`, file.filename)
          onClose()
        }}
        className="w-full text-left px-3 py-2 text-sm text-neutral-200 hover:bg-neutral-700 transition-colors"
      >
        Original ({ext})
      </button>
    </div>
  )
}

// The ML service resizes images to this longest-side before running face detection.
// Must match monet_ml_image_size in backend config (default 768).
const ML_IMAGE_SIZE = 768

function FaceBboxOverlay({
  bbox,
  origMaxSide,
  thumbW,
  thumbH,
  displaySize,
}: {
  bbox: { x: number; y: number; w: number; h: number }
  origMaxSide: number   // max(file.width, file.height) — used to derive ML image size
  thumbW: number        // thumbnail natural width (exif-corrected, from onLoad)
  thumbH: number        // thumbnail natural height
  displaySize: number
}) {
  // ML input max side: image was resized to ML_IMAGE_SIZE if larger, otherwise kept as-is.
  const mlMaxSide = Math.min(ML_IMAGE_SIZE, origMaxSide)
  // Scale factor from ML input space to thumbnail space (both have same aspect ratio).
  const thumbMaxSide = Math.max(thumbW, thumbH)
  const mlToThumb = thumbMaxSide / mlMaxSide

  // bbox in thumbnail space
  const bx = bbox.x * mlToThumb
  const by = bbox.y * mlToThumb
  const bw = bbox.w * mlToThumb
  const bh = bbox.h * mlToThumb

  // object-cover: scale thumbnail to fill displaySize × displaySize
  const coverScale = Math.max(displaySize / thumbW, displaySize / thumbH)
  const offsetX = (displaySize - thumbW * coverScale) / 2
  const offsetY = (displaySize - thumbH * coverScale) / 2

  return (
    <div
      className="absolute pointer-events-none"
      style={{
        left: bx * coverScale + offsetX,
        top: by * coverScale + offsetY,
        width: bw * coverScale,
        height: bh * coverScale,
        boxShadow: '0 0 0 2px rgba(255,255,255,0.9), 0 0 0 3px rgba(59,130,246,0.8)',
        borderRadius: 2,
      }}
    />
  )
}

export default function MediaTile({ file, onClick, imageSize, selected, onSelect, faceBbox }: MediaTileProps) {
  const dateLabel = file.taken_at ? formatDate(file.taken_at) : null
  const [showDownload, setShowDownload] = useState(false)
  const [thumbNatural, setThumbNatural] = useState<{ w: number; h: number } | null>(null)
  const onNaturalSize = useCallback((w: number, h: number) => setThumbNatural({ w, h }), [])


  return (
    <div
      onClick={(e) => {
        if (e.shiftKey) {
          onSelect(file.id, true)
        } else {
          onClick()
        }
      }}
      className="group cursor-pointer flex flex-col w-full h-full"
      title={file.filename}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onClick()
      }}
      aria-label={file.filename}
    >
      {/* Image area — relative wrapper allows download button to escape overflow-hidden */}
      <div className="relative flex-shrink-0" style={{ height: imageSize }}>
      <div
        className={cn(
          'absolute inset-0 overflow-hidden rounded',
          'bg-neutral-800 transition-all duration-150',
          selected
            ? 'ring-2 ring-blue-500'
            : 'hover:ring-2 hover:ring-blue-500'
        )}
      >
        {file.media_type === 'audio' ? (
          <div className="w-full h-full flex flex-col items-center justify-center gap-2 bg-neutral-800 rounded">
            <Music size={32} className="text-neutral-500" />
            <span className="text-xs text-neutral-500 px-2 text-center truncate w-full">
              {file.filename}
            </span>
          </div>
        ) : (
          <FileThumbnail
            file={file}
            imgClassName="w-full h-full object-cover rounded transition-transform duration-200 group-hover:scale-[1.02]"
            onNaturalSize={faceBbox ? onNaturalSize : undefined}
            fallback={
              <div className="w-full h-full flex flex-col items-center justify-center gap-2 bg-neutral-800 rounded">
                {file.media_type === 'video' ? (
                  <Video size={32} className="text-neutral-500" />
                ) : (
                  <ImageOff size={32} className="text-neutral-500" />
                )}
              </div>
            }
          />
        )}

        {/* Face bounding box overlay */}
        {faceBbox && thumbNatural && file.width && file.height && (
          <FaceBboxOverlay
            bbox={faceBbox}
            origMaxSide={Math.max(file.width, file.height)}
            thumbW={thumbNatural.w}
            thumbH={thumbNatural.h}
            displaySize={imageSize}
          />
        )}

        {/* Checkbox — top-left.
            readOnly suppresses the React controlled-without-onChange warning;
            all selection logic (including shift-key) is handled via onClick. */}
        <div
          className="absolute top-1.5 left-1.5 z-10"
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={selected}
            readOnly
            onClick={(e) => {
              e.stopPropagation()
              onSelect(file.id, e.shiftKey)
            }}
            className="w-4 h-4 rounded accent-blue-500 cursor-pointer"
            aria-label={`Select ${file.filename}`}
          />
        </div>

        {/* Video duration */}
        {file.media_type === 'video' && file.duration_sec != null && (
          <div className="absolute bottom-1.5 right-1.5">
            <span className="rounded bg-black/70 px-1 py-0.5 text-xs text-white font-mono">
              {formatDuration(file.duration_sec)}
            </span>
          </div>
        )}

        {/* Video play icon overlay */}
        {file.media_type === 'video' && file.has_thumbnail && (
          <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
            <div className="w-10 h-10 rounded-full bg-black/60 flex items-center justify-center">
              <Video size={18} className="text-white ml-0.5" />
            </div>
          </div>
        )}
      </div>{/* end inner overflow-hidden div */}

      {/* RAW badge — outside overflow-hidden so it's not covered by download button */}
      {file.is_raw && (
        <div className="absolute top-1.5 right-10 z-10 pointer-events-none">
          <Badge variant="yellow">RAW</Badge>
        </div>
      )}

      {/* Download button — top-right, outside overflow-hidden so dropdown isn't clipped */}
      <div
        className="absolute top-1.5 right-1.5 z-10"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          onClick={(e) => {
            e.stopPropagation()
            setShowDownload((v) => !v)
          }}
          className={cn(
            'flex items-center justify-center p-1.5 rounded transition-colors shadow',
            showDownload
              ? 'bg-blue-600 text-white'
              : 'bg-black/70 text-white hover:bg-blue-600'
          )}
          title="Download"
        >
          <Download size={13} />
        </button>
        {showDownload && (
          <DownloadMenu file={file} onClose={() => setShowDownload(false)} />
        )}
      </div>
      </div>{/* end outer relative wrapper */}

      {/* Below-image info */}
      <div className="px-0.5 pt-1 flex flex-col overflow-hidden">
        {dateLabel && (
          <p className="text-xs text-neutral-400 truncate leading-4">{dateLabel}</p>
        )}
        {file.caption && (
          <p
            className="text-xs text-neutral-500 truncate leading-4"
            title={file.caption}
          >
            {file.caption}
          </p>
        )}
      </div>
    </div>
  )
}
