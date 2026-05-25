import { create } from 'zustand'
import type { UserResponse } from '../types/api'

interface AuthState {
  accessToken: string | null
  user: UserResponse | null
  isInitializing: boolean
  setAuth: (token: string, user: UserResponse) => void
  setToken: (token: string) => void
  setInitializing: (v: boolean) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  isInitializing: true,
  setAuth: (token, user) => set({ accessToken: token, user }),
  setToken: (token) => set({ accessToken: token }),
  setInitializing: (v) => set({ isInitializing: v }),
  logout: () => set({ accessToken: null, user: null }),
}))
