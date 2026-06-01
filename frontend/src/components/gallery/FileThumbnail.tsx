import type { FileResponse } from '../../types/api'

interface FileThumbnailProps {
  file: Pick<FileResponse, 'has_thumbnail' | 'thumbnail_url' | 'filename'>
  imgClassName?: string
  fallback?: React.ReactNode
  onNaturalSize?: (w: number, h: number) => void
}

export function FileThumbnail({ file, imgClassName, fallback, onNaturalSize }: FileThumbnailProps) {
  if (file.has_thumbnail) {
    return (
      <img
        src={file.thumbnail_url}
        alt={file.filename}
        loading="lazy"
        draggable={false}
        className={imgClassName}
        onLoad={onNaturalSize ? (e) => {
          const img = e.currentTarget
          onNaturalSize(img.naturalWidth, img.naturalHeight)
        } : undefined}
      />
    )
  }
  return <>{fallback ?? null}</>
}
