import client from './client'
import type { PaginatedFiles } from '../types/api'

export interface SearchParams {
  q: string
  folder_id?: string
  album_id?: string
  page?: number
  page_size?: number
}

export async function searchFiles(params: SearchParams): Promise<PaginatedFiles> {
  const { data } = await client.get<PaginatedFiles>('/api/search', { params })
  return data
}
