import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/app/',
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/auth': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/uploads': { target: 'http://127.0.0.1:5000', changeOrigin: true },
    },
  },
  build: {
    outDir: '../app/static/dist',
    emptyOutDir: true,
  },
})
