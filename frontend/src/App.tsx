import type { ReactNode } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/auth'
import { useInitAuth } from './hooks/useAuth'
import LoginPage from './components/auth/LoginPage'
import AppShell from './components/layout/AppShell'
import GalleryGrid from './components/gallery/GalleryGrid'
import TrashView from './components/gallery/TrashView'
import SettingsPage from './components/settings/SettingsPage'

function RequireAuth({ children }: { children: ReactNode }) {
  const token = useAuthStore((s) => s.accessToken)
  const isInitializing = useAuthStore((s) => s.isInitializing)
  if (isInitializing) return null
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  useInitAuth()

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/browse" replace />} />
        <Route path="browse" element={<GalleryGrid />} />
        <Route path="browse/:rootFolderId" element={<GalleryGrid />} />
        <Route path="browse/:rootFolderId/*" element={<GalleryGrid />} />
        <Route path="trash" element={<TrashView />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}
