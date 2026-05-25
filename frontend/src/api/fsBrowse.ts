import client from './client'
import type { FsBrowseResponse } from '../types/api'

export async function browseFs(path: string | null): Promise<FsBrowseResponse> {
  const { data } = await client.get<FsBrowseResponse>('/api/fs/browse', {
    params: path != null ? { path } : {},
  })
  return data
}
