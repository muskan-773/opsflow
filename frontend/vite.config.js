import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy API calls to the FastAPI backend so the browser avoids CORS
    // entirely during development. Calls to /api, /auth, /items, /dashboard,
    // /health are forwarded to localhost:8000.
    proxy: {
      '/auth': 'http://localhost:8000',
      '/items': 'http://localhost:8000',
      '/dashboard': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
