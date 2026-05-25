import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    allowedHosts: ['<monet-dev-host>', '<monet-dev-ip>'],
    proxy: {
      '/api': { target: 'http://<monet-dev-ip>:8000', changeOrigin: true },
    },
  },
})
