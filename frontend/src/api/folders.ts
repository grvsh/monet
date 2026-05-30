import client from './client'
import type { FileResponse, FolderResponse, PaginatedFiles } from '../types/api'

export async function listRootLevelFolders(): Promise<FolderResponse[]> {
  const { data } = await client.get<FolderResponse[]>('/api/folders')
  return data
}

export async function searchFolders(q: string): Promise<FolderResponse[]> {
  const { data } = await client.get<FolderResponse[]>('/api/folders/search', { params: { q } })
  return data
}

export async function resolveFolderByPath(
  rootFolderId: string,
  path: string
): Promise<FolderResponse> {
  const { data } = await client.get<FolderResponse>('/api/folders/by-path', {
    params: { root_folder_id: rootFolderId, path },
  })
  return data
}

export async function listChildFolders(folderId: string): Promise<FolderResponse[]> {
  const { data } = await client.get<FolderResponse[]>(`/api/folders/${folderId}/children`)
  return data
}

export interface FolderFilesParams {
  page?: number
  page_size?: number
  sort?: 'taken_at' | 'filename' | 'size_bytes'
  order?: 'asc' | 'desc'
  media_type?: 'all' | 'image' | 'video' | 'audio'
}

export async function listFolderFiles(
  folderId: string,
  params: FolderFilesParams = {}
): Promise<PaginatedFiles> {
  const { data } = await client.get<PaginatedFiles>(`/api/folders/${folderId}/files`, {
    params: {
      page: params.page ?? 1,
      page_size: params.page_size ?? 100,
      sort: params.sort ?? 'taken_at',
      order: params.order ?? 'desc',
      media_type: params.media_type ?? 'all',
    },
  })
  return data
}

export interface FolderTypeCounts {
  image: number
  video: number
  audio: number
}

export async function getFolderTypeCounts(folderId: string): Promise<FolderTypeCounts> {
  const { data } = await client.get<FolderTypeCounts>(`/api/folders/${folderId}/type-counts`)
  return data
}

export async function listFolderMissingFiles(folderId: string): Promise<FileResponse[]> {
  const { data } = await client.get<FileResponse[]>(`/api/folders/${folderId}/missing-files`)
  return data
}

export async function listFolderTrashedFiles(folderId: string): Promise<FileResponse[]> {
  const { data } = await client.get<FileResponse[]>(`/api/folders/${folderId}/trashed-files`)
  return data
}

export async function getFolderDiskStats(folderId: string): Promise<{ file_count: number }> {
  const { data } = await client.get<{ file_count: number }>(`/api/folders/${folderId}/disk-stats`)
  return data
}

export async function removeFolderFromMonet(folderId: string): Promise<void> {
  await client.post(`/api/folders/${folderId}/remove-from-monet`)
}

export async function deleteEmptyFolder(folderId: string): Promise<void> {
  await client.delete(`/api/folders/${folderId}`)
}
