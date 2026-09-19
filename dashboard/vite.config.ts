import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // Use VITE_API_PROXY target env var (defaults to localhost for host-side
        // `npm run dev`); set to http://server:8443 when running inside Docker Compose
        // via the VITE_API_PROXY env var in docker-compose.dev.yml.
        target: process.env.VITE_API_PROXY || 'https://localhost:8443',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
