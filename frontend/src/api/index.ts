import client from './client'
import type { ScanJobResponse, UserResponse } from '../types/api'

export interface FailedFileInfo {
  id: string
  path: string
  error: string
}

export interface ProcessingStatusResponse {
  total: number
  processed: number
  pending: number
  failed: number
  failed_files: FailedFileInfo[]
}

interface ScanTriggerResponse {
  scan_job_id: string
  message: string
}

interface ScanStatusResponse {
  jobs: ScanJobResponse[]
}

export async function triggerScan(rootFolderId?: string): Promise<ScanTriggerResponse> {
  if (rootFolderId) {
    const { data } = await client.post<ScanTriggerResponse>(`/api/index/scan/${rootFolderId}`)
    return data
  }
  const { data } = await client.post<ScanTriggerResponse>('/api/index/scan', {
    root_folder_id: undefined,
  })
  return data
}

export async function getScanStatus(): Promise<ScanStatusResponse> {
  const { data } = await client.get<ScanStatusResponse>('/api/index/status')
  return data
}

export async function getRootScanStatus(rootFolderId: string): Promise<ScanJobResponse> {
  const { data } = await client.get<ScanJobResponse>(`/api/index/status/${rootFolderId}`)
  return data
}

export async function getProcessingStatus(rootFolderId: string): Promise<ProcessingStatusResponse> {
  const { data } = await client.get<ProcessingStatusResponse>(`/api/index/processing-status/${rootFolderId}`)
  return data
}

export interface CreateUserData {
  email: string
  password: string
  full_name?: string
  role?: 'admin' | 'viewer'
}

export interface UpdateUserData {
  full_name?: string
  role?: 'admin' | 'viewer'
  is_active?: boolean
}

export async function listUsers(): Promise<UserResponse[]> {
  const { data } = await client.get<UserResponse[]>('/api/users')
  return data
}

export async function createUser(data: CreateUserData): Promise<UserResponse> {
  const { data: user } = await client.post<UserResponse>('/api/users', data)
  return user
}

export async function updateUser(id: string, updates: UpdateUserData): Promise<UserResponse> {
  const { data } = await client.patch<UserResponse>(`/api/users/${id}`, updates)
  return data
}

export async function deleteUser(id: string): Promise<void> {
  await client.delete(`/api/users/${id}`)
}
