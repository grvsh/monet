import { useEffect } from 'react'
import { useAuthStore } from '../store/auth'
import { refresh, getMe } from '../api/auth'

/**
 * Called once at the app root. Tries to restore the session from the
 * refresh-token cookie. Sets isInitializing=false when done so that
 * RequireAuth can make the redirect decision.
 */
export function useInitAuth() {
  const setAuth = useAuthStore((s) => s.setAuth)
  const setInitializing = useAuthStore((s) => s.setInitializing)

  useEffect(() => {
    refresh()
      .then(({ access_token }) => getMe().then((user) => setAuth(access_token, user)))
      .catch(() => {/* no valid session — stay logged out */})
      .finally(() => setInitializing(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
}
