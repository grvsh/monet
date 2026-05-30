import client from './client'
import type { UserResponse } from '../types/api'

interface LoginResponse {
  access_token: string
  token_type: string
  user: UserResponse
}

interface RefreshResponse {
  access_token: string
  token_type: string
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const { data } = await client.post<LoginResponse>('/api/auth/login', { email, password })
  return data
}

export async function refresh(): Promise<RefreshResponse> {
  const { data } = await client.post<RefreshResponse>('/api/auth/refresh')
  return data
}

export async function logout(): Promise<void> {
  await client.post('/api/auth/logout')
}

export async function getMe(): Promise<UserResponse> {
  const { data } = await client.get<UserResponse>('/api/auth/me')
  return data
}

export async function patchMyPreferences(prefs: { allow_disk_deletion: boolean }): Promise<UserResponse> {
  const { data } = await client.patch<UserResponse>('/api/users/me/preferences', prefs)
  return data
}
