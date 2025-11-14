import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const backendTarget = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true
      },
      '/download': {
        target: backendTarget,
        changeOrigin: true
      },
      '/storage': {
        target: backendTarget,
        changeOrigin: true
      }
    }
  }
})
