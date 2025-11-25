import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendTarget = env.VITE_BACKEND_URL ?? 'http://backend:8000'

  return {
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
  }
})
