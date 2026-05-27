import client from './client'
import type { AlbumResponse, PaginatedFiles } from '../types/api'

export async function listAlbums(): Promise<AlbumResponse[]> {
  const { data } = await client.get<AlbumResponse[]>('/api/albums')
  return data
}

export async function createAlbum(name: string): Promise<AlbumResponse> {
  const { data } = await client.post<AlbumResponse>('/api/albums', { name })
  return data
}

export async function renameAlbum(id: string, name: string): Promise<AlbumResponse> {
  const { data } = await client.patch<AlbumResponse>(`/api/albums/${id}`, { name })
  return data
}

export async function deleteAlbum(id: string): Promise<void> {
  await client.delete(`/api/albums/${id}`)
}

export async function listAlbumFiles(
  id: string,
  params: { page?: number; page_size?: number } = {}
): Promise<PaginatedFiles> {
  const { data } = await client.get<PaginatedFiles>(`/api/albums/${id}/files`, {
    params: { page: params.page ?? 1, page_size: params.page_size ?? 500 },
  })
  return data
}

export async function addFilesToAlbum(id: string, fileIds: string[]): Promise<void> {
  await client.post(`/api/albums/${id}/files`, { file_ids: fileIds })
}

export async function removeFilesFromAlbum(id: string, fileIds: string[]): Promise<void> {
  await client.delete(`/api/albums/${id}/files`, { data: { file_ids: fileIds } })
}
