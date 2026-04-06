import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const proxyTarget =
  process.env.SENTINELFLOW_API_PROXY_TARGET ||
  process.env.VITE_SENTINELFLOW_API_BASE_URL ||
  'http://127.0.0.1:8001'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5174,
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: proxyTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 5174,
    host: '127.0.0.1',
  },
})
