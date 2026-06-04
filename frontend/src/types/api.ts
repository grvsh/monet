export interface UserResponse {
  id: string
  email: string
  full_name: string | null
  role: 'admin' | 'viewer'
  is_active: boolean
  created_at: string
  last_login_at: string | null
  allow_disk_deletion: boolean
  face_cluster_min_size: number
}

export interface RootFolderResponse {
  id: string
  name: string
  path: string
  is_active: boolean
  created_at: string
  last_scanned_at: string | null
  parent_root_id: string | null
  created_by: string | null
}

export interface FolderResponse {
  id: string
  root_folder_id: string
  parent_id: string | null
  path: string
  name: string
  file_count: number
  child_folder_count: number
  indexed_at: string | null
}

export interface FileResponse {
  id: string
  folder_id: string
  root_folder_id: string
  filename: string
  extension: string
  media_type: 'image' | 'video' | 'audio'
  mime_type: string
  is_raw: boolean
  width: number | null
  height: number | null
  duration_sec: number | null
  taken_at: string | null
  camera_make: string | null
  camera_model: string | null
  has_gps: boolean
  has_thumbnail: boolean
  has_preview: boolean
  has_video_preview: boolean
  size_bytes: number | null
  thumbnail_url: string
  preview_url: string
  video_preview_url: string | null
  lens_model: string | null
  location: string | null
  caption: string | null
  trashed_at: string | null
  missing_since: string | null
  face_bbox: { x: number; y: number; w: number; h: number } | null
  face_detection_id: string | null
}

export interface FileDetailResponse extends FileResponse {
  path: string
  focal_length_mm: number | null
  aperture: number | null
  shutter_speed: string | null
  iso: number | null
  gps_lat: number | null
  gps_lon: number | null
  gps_alt_m: number | null
  orientation: number | null
  indexed_at: string
  processed_at: string | null
  metadata: Record<string, unknown> | null
  face_count: number | null
  clip_embedding: boolean
  dino_embedding: boolean
  ai_analyzed_at: string | null
  ai_versions: Record<string, unknown> | null
  ml_error: string | null
}

export interface PaginatedFiles {
  items: FileResponse[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface AlbumResponse {
  id: string
  name: string
  owner_id: string
  file_count: number
  cover_url: string | null
  created_at: string
  updated_at: string
}

export interface ScanJobResponse {
  id: string
  root_folder_id: string | null
  trigger_type: string
  status: string
  folders_found: number
  folders_scanned: number
  files_found: number
  files_new: number
  files_updated: number
  files_deleted: number
  files_skipped: number
  files_failed: number
  ml_files_pending: number
  ml_files_done: number
  ml_files_failed: number
  error_message: string | null
  started_at: string
  completed_at: string | null
}

export interface FsEntry {
  name: string
  path: string
  is_symlink: boolean
  is_configured: boolean
}

export interface FsBrowseResponse {
  path: string
  parent: string | null
  entries: FsEntry[]
  path_is_configured: boolean
}

export interface PersonResponse {
  id: string
  name: string | null
  face_count: number
  sample_thumbnail_urls: string[]
  cover_face_detection_id: string | null
}

export interface PeopleListResponse {
  people: PersonResponse[]
}

export interface RootPrefItem {
  root_folder_id: string
  is_visible: boolean
}

export interface RootPrefsResponse {
  prefs: RootPrefItem[]
}

export interface RootFolderStats {
  root_folder_id: string
  image_count: number
  video_count: number
  audio_count: number
  total_count: number
}
