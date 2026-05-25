import client from './client'
import type { FileDetailResponse, PaginatedFiles } from '../types/api'

export async function getFile(fileId: string): Promise<FileDetailResponse> {
  const { data } = await client.get<FileDetailResponse>(`/api/files/${fileId}`)
  return data
}

export async function bulkDeleteFiles(fileIds: string[]): Promise<{ trashed: number }> {
  const { data } = await client.post<{ trashed: number }>('/api/files/bulk-delete', {
    file_ids: fileIds,
  })
  return data
}

export async function bulkTrashMissingFiles(fileIds: string[]): Promise<{ trashed: number }> {
  const { data } = await client.post<{ trashed: number }>('/api/files/bulk-trash-missing', {
    file_ids: fileIds,
  })
  return data
}

export async function bulkDismissMissingFiles(fileIds: string[]): Promise<{ dismissed: number }> {
  const { data } = await client.post<{ dismissed: number }>('/api/files/bulk-dismiss-missing', {
    file_ids: fileIds,
  })
  return data
}

export async function bulkRestoreFiles(fileIds: string[]): Promise<{ restored: number }> {
  const { data } = await client.post<{ restored: number }>('/api/files/bulk-restore', {
    file_ids: fileIds,
  })
  return data
}

export async function listTrashFiles(page = 1, page_size = 200): Promise<PaginatedFiles> {
  const { data } = await client.get<PaginatedFiles>('/api/files/trash', {
    params: { page, page_size },
  })
  return data
}

export interface SearchParams {
  q?: string
  folder_id?: string
  root_folder_id?: string
  media_type?: 'all' | 'image' | 'video' | 'audio'
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}

export async function searchFiles(params: SearchParams): Promise<PaginatedFiles> {
  const { data } = await client.get<PaginatedFiles>('/api/search', {
    params: {
      q: params.q ?? '',
      folder_id: params.folder_id,
      root_folder_id: params.root_folder_id,
      media_type: params.media_type,
      date_from: params.date_from,
      date_to: params.date_to,
      page: params.page ?? 1,
      page_size: params.page_size ?? 50,
    },
  })
  return data
}
