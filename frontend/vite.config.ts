/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Ports are overridable so several dev/e2e instances can run side by side:
//   SKYSHIFT_WEB_PORT (default 5173), SKYSHIFT_API_PORT (default 8000).
const webPort = Number(process.env.SKYSHIFT_WEB_PORT ?? 5173)
const apiPort = Number(process.env.SKYSHIFT_API_PORT ?? 8000)

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: webPort,
    strictPort: true,
    proxy: {
      '/api': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: false },
    },
  },
  preview: { host: '127.0.0.1', port: 4173 },
  test: {
    include: ['src/**/*.test.{ts,tsx}'],
    environment: 'node',
    reporters: ['default'],
  },
})
