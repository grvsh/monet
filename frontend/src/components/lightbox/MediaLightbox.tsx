import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import Lightbox from 'yet-another-react-lightbox'
import Video from 'yet-another-react-lightbox/plugins/video'
import 'yet-another-react-lightbox/styles.css'
import type { FileResponse } from '../../types/api'
import MetadataPanel from '../metadata/MetadataPanel'
import { Info, Download, PanelRight } from 'lucide-react'
import { cn } from '../../lib/utils'
import { downloadFile } from '../../api/download'

interface MediaLightboxProps {
  files: FileResponse[]
  index: number
  onClose: () => void
}

function buildSlides(files: FileResponse[]) {
  return files.map((file) => {
    if (file.media_type === 'video') {
      const videoSrc = file.has_video_preview && file.video_preview_url
        ? file.video_preview_url
        : `/api/stream/${file.id}`
      return {
        type: 'video' as const,
        sources: [{ src: videoSrc, type: 'video/mp4' }],
        poster: file.has_thumbnail ? file.thumbnail_url : undefined,
        description: file.filename,
        _fileId: file.id,
      }
    }
    return {
      src: file.has_preview ? file.preview_url : file.thumbnail_url,
      alt: file.filename,
      description: file.filename,
      _fileId: file.id,
      _isAudio: file.media_type === 'audio',
      _audioSrc: `/api/stream/${file.id}`,
      _audioBg: file.thumbnail_url,
    }
  })
}

export default function MediaLightbox({ files, index, onClose }: MediaLightboxProps) {
  const [currentIndex, setCurrentIndex] = useState(index)
  const [showMeta, setShowMeta] = useState(true)
  const [showDownloadMenu, setShowDownloadMenu] = useState(false)
  const downloadMenuRef = useRef<HTMLDivElement>(null)
  // isEntering: portal fade-in has started — show panel in sync with image
  const [isEntering, setIsEntering] = useState(false)
  // isEntered: portal fully open — safe to show the Info toggle button
  const [isEntered, setIsEntered] = useState(false)
  // isClosing: portal fade-out has started — hide panel in sync with image
  const [isClosing, setIsClosing] = useState(false)

  // Refs so callbacks always see the latest values without stale closures.
  const filesRef = useRef(files)
  filesRef.current = files
  const currentIndexRef = useRef(index)
  const showMetaRef = useRef(showMeta)
  showMetaRef.current = showMeta
  const preFullscreenShowMeta = useRef<boolean | null>(null)

  const currentFile = files[currentIndex]

  // Find the <video> element for the currently visible slide by matching its
  // source URL. YARL preloads adjacent slides so querySelectorAll returns
  // multiple <video> elements; we must identify the right one.
  const findCurrentVideo = useCallback((): HTMLVideoElement | null => {
    const file = filesRef.current[currentIndexRef.current]
    if (!file || file.media_type !== 'video') return null
    const src = file.has_video_preview && file.video_preview_url
      ? file.video_preview_url
      : `/api/stream/${file.id}`
    const videos = Array.from(document.querySelectorAll('.yarl__portal video')) as HTMLVideoElement[]
    return videos.find(v => v.querySelector('source')?.getAttribute('src') === src) ?? null
  }, [])

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'i' || e.key === 'I') {
      setShowMeta((v) => !v)
    } else if (e.key === ' ') {
      const video = findCurrentVideo()
      // When the video element itself is the fullscreen element, the browser's
      // native <video controls> handles Space — our handler would double-toggle.
      if (video && document.fullscreenElement !== video) {
        e.preventDefault()
        video.paused ? video.play().catch(() => {}) : video.pause()
      }
    }
  }, [findCurrentVideo])

  const handleDoubleClick = useCallback(() => {
    if (!document.fullscreenElement) {
      const video = findCurrentVideo()
      if (video) {
        // Fullscreen the video element directly — same as the native controls button.
        video.requestFullscreen().catch(() => {})
      } else {
        // Image: fullscreen the YARL portal root (rendered into document.body via portal).
        const yarlRoot = document.querySelector('.yarl__portal') as HTMLElement | null
        ;(yarlRoot ?? document.documentElement).requestFullscreen().catch(() => {})
      }
    } else {
      document.exitFullscreen().catch(() => {})
    }
  }, [findCurrentVideo])

  const handleClose = useCallback(() => {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {})
    }
    onClose()
  }, [onClose])

  useEffect(() => {
    // Capture phase so our handler fires before YARL's onKeyDown stopPropagation.
    document.addEventListener('keydown', handleKeyDown, true)
    return () => document.removeEventListener('keydown', handleKeyDown, true)
  }, [handleKeyDown])

  useEffect(() => {
    const handleFullscreenChange = () => {
      if (document.fullscreenElement) {
        preFullscreenShowMeta.current = showMetaRef.current
        setShowMeta(false)
      } else if (preFullscreenShowMeta.current !== null) {
        setShowMeta(preFullscreenShowMeta.current)
        preFullscreenShowMeta.current = null
      }
    }
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange)
  }, [])

  useEffect(() => {
    if (!showDownloadMenu) return
    function handleClickOutside(e: MouseEvent) {
      if (downloadMenuRef.current && !downloadMenuRef.current.contains(e.target as Node)) {
        setShowDownloadMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showDownloadMenu])

  const slides = buildSlides(files)

  const panelVisible = showMeta && isEntering && !isClosing && !!currentFile
  const buttonVisible = isEntered && !isClosing

  const portalContent = isEntering && !isClosing && currentFile ? (
    <>
      {/* ── Metadata panel OR reopen button ── */}
      {panelVisible ? (
        <div
          style={{ zIndex: 99999 }}
          className="w-[360px] fixed right-0 top-0 bottom-0 overflow-y-auto border-l border-neutral-700 bg-neutral-900"
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-700">
            <h3 className="text-sm font-semibold text-neutral-100">File Info</h3>
            <button
              onClick={() => setShowMeta(false)}
              className="text-neutral-400 hover:text-neutral-100 text-xs"
            >
              Close
            </button>
          </div>
          <MetadataPanel fileId={currentFile.id} />
        </div>
      ) : (
        <button
          style={{ zIndex: 99999 }}
          onClick={() => setShowMeta(true)}
          className="fixed top-14 right-3 p-2 rounded-md bg-neutral-800/80 text-neutral-300 hover:bg-neutral-700 hover:text-white transition-colors"
          title="Show file info (I)"
        >
          <PanelRight size={18} />
        </button>
      )}

      {/* ── 1080p badge ── */}
      {buttonVisible && currentFile.media_type === 'video' && currentFile.has_video_preview && (
        <div style={{ zIndex: 99999 }} className="fixed bottom-4 left-4">
          <span className="rounded-full px-3 py-1.5 text-xs font-medium bg-neutral-800/80 text-neutral-300">
            1080p
          </span>
        </div>
      )}

      {/* ── Download + Info toolbar ── */}
      {buttonVisible && (
        <div
          style={{ zIndex: 99999 }}
          className={cn('fixed bottom-4 flex items-center gap-2', showMeta ? 'right-[376px]' : 'right-4')}
        >
          <div className="relative" ref={downloadMenuRef}>
            <button
              onClick={() => setShowDownloadMenu((v) => !v)}
              className={cn(
                'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors',
                showDownloadMenu
                  ? 'bg-blue-600 text-white'
                  : 'bg-neutral-800/80 text-neutral-300 hover:bg-neutral-700'
              )}
              title="Download"
            >
              <Download size={14} />
              Download
            </button>
            {showDownloadMenu && (
              <div className="absolute bottom-full mb-2 right-0 bg-neutral-800 border border-neutral-700 rounded-lg shadow-xl py-1 min-w-[180px]">
                {currentFile.has_preview && (
                  <button
                    onClick={() => {
                      const stem = currentFile.filename.replace(/\.[^.]+$/, '')
                      downloadFile(`/api/previews/${currentFile.id}/download`, `${stem}_preview.jpg`)
                      setShowDownloadMenu(false)
                    }}
                    className="w-full text-left px-4 py-2 text-sm text-neutral-200 hover:bg-neutral-700 transition-colors"
                  >
                    Preview (JPEG)
                  </button>
                )}
                <button
                  onClick={() => {
                    downloadFile(`/api/original/${currentFile.id}`, currentFile.filename)
                    setShowDownloadMenu(false)
                  }}
                  className="w-full text-left px-4 py-2 text-sm text-neutral-200 hover:bg-neutral-700 transition-colors"
                >
                  Original ({currentFile.filename.split('.').pop()?.toUpperCase() ?? 'File'})
                </button>
              </div>
            )}
          </div>

          <button
            onClick={() => setShowMeta((v) => !v)}
            className={cn(
              'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors',
              showMeta
                ? 'bg-blue-600 text-white'
                : 'bg-neutral-800/80 text-neutral-300 hover:bg-neutral-700'
            )}
            title="Toggle info panel (I)"
          >
            <Info size={14} />
            Info
          </button>
        </div>
      )}
    </>
  ) : null

  return (
    <>
      <div className="fixed inset-0 z-50 flex">
        <div className={cn('flex-1 relative', showMeta ? 'mr-[360px]' : '')} onDoubleClick={handleDoubleClick}>
          <Lightbox
            open
            close={handleClose}
            index={currentIndex}
            slides={slides}
            plugins={[Video]}
            on={{
              view: ({ index: i }) => { setCurrentIndex(i); currentIndexRef.current = i },
              entering: () => setIsEntering(true),
              entered: () => setIsEntered(true),
              exiting: () => {
                setIsClosing(true)
                setIsEntering(false)
                setIsEntered(false)
              },
            }}
            styles={{
              container: {
                backgroundColor: 'rgba(10,10,10,0.97)',
                right: showMeta ? '360px' : 0,
              },
            }}
            render={{
              slide: ({ slide }) => {
                const s = slide as typeof slides[0] & {
                  _isAudio?: boolean
                  _audioSrc?: string
                  _audioBg?: string
                }
                if (s._isAudio) {
                  return (
                    <div className="flex flex-col items-center justify-center gap-6 h-full text-neutral-100">
                      {s._audioBg && (
                        <img
                          src={s._audioBg}
                          alt="cover art"
                          className="w-48 h-48 object-cover rounded-lg shadow-2xl"
                        />
                      )}
                      <p className="text-sm text-neutral-300 max-w-xs text-center">
                        {(slide as { description?: string }).description}
                      </p>
                      <audio controls src={s._audioSrc} className="w-72" autoPlay />
                    </div>
                  )
                }
                return null
              },
            }}
          />

        </div>
      </div>

      {/* Panel / reopen button rendered into document.body — outside YARL's stacking context */}
      {createPortal(portalContent, document.body)}
    </>
  )
}
