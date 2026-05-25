import client from './client'
import type { RootFolderResponse, RootPrefsResponse, RootPrefItem } from '../types/api'

export async function listRootFolders(): Promise<RootFolderResponse[]> {
  const { data } = await client.get<RootFolderResponse[]>('/api/root-folders')
  return data
}

export async function createRootFolder(name: string, path: string): Promise<RootFolderResponse> {
  const { data } = await client.post<RootFolderResponse>('/api/root-folders', { name, path })
  return data
}

export async function updateRootFolder(
  id: string,
  updates: { name?: string; path?: string }
): Promise<RootFolderResponse> {
  const { data } = await client.patch<RootFolderResponse>(`/api/root-folders/${id}`, updates)
  return data
}

export async function deleteRootFolder(id: string): Promise<void> {
  await client.delete(`/api/root-folders/${id}`)
}

export async function getRootPrefs(): Promise<RootPrefsResponse> {
  const { data } = await client.get<RootPrefsResponse>('/api/users/me/root-prefs')
  return data
}

export async function updateRootPrefs(prefs: RootPrefItem[]): Promise<RootPrefsResponse> {
  const { data } = await client.put<RootPrefsResponse>('/api/users/me/root-prefs', { prefs })
  return data
}
