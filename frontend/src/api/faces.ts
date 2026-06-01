import client from './client'
import type { PaginatedFiles, PeopleListResponse, PersonResponse } from '../types/api'

export async function listPeople(): Promise<PeopleListResponse> {
  const { data } = await client.get<PeopleListResponse>('/api/faces/people')
  return data
}

export async function getPerson(personId: string): Promise<PersonResponse> {
  const { data } = await client.get<PersonResponse>(`/api/faces/people/${personId}`)
  return data
}

export async function getPersonFiles(personId: string, page = 1, pageSize = 200): Promise<PaginatedFiles> {
  const { data } = await client.get<PaginatedFiles>(`/api/faces/people/${personId}/files`, {
    params: { page, page_size: pageSize },
  })
  return data
}

export async function updatePerson(personId: string, name: string | null): Promise<PersonResponse> {
  const { data } = await client.patch<PersonResponse>(`/api/faces/people/${personId}`, { name })
  return data
}

export async function mergePeople(sourceId: string, targetId: string): Promise<PersonResponse> {
  const { data } = await client.post<PersonResponse>('/api/faces/people/merge', {
    source_id: sourceId,
    target_id: targetId,
  })
  return data
}

export async function unassignDetection(detectionId: string): Promise<void> {
  await client.delete(`/api/faces/detections/${detectionId}`)
}

export async function triggerCluster(): Promise<void> {
  await client.post('/api/faces/cluster')
}

export interface ClusterStatus {
  running: boolean
  step?: string
  pct?: number
}

export async function getClusterStatus(): Promise<ClusterStatus> {
  const { data } = await client.get<ClusterStatus>('/api/faces/cluster/status')
  return data
}
