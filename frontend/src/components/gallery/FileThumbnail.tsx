import type { FileResponse } from '../../types/api'

interface FileThumbnailProps {
  file: Pick<FileResponse, 'has_thumbnail' | 'thumbnail_url' | 'filename'>
  imgClassName?: string
  fallback?: React.ReactNode
}

export function FileThumbnail({ file, imgClassName, fallback }: FileThumbnailProps) {
  if (file.has_thumbnail) {
    return (
      <img
        src={file.thumbnail_url}
        alt={file.filename}
        loading="lazy"
        draggable={false}
        className={imgClassName}
      />
    )
  }
  return <>{fallback ?? null}</>
}
