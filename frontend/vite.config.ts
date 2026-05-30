import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // Set VITE_API_URL in frontend/.env.local to proxy API calls to a remote backend.
  // Defaults to localhost for standard local development.
  const apiTarget = env.VITE_API_URL ?? 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      host: true,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true },
      },
    },
  }
})
