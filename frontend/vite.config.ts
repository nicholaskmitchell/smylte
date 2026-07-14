/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: `npm run dev` proxies API calls to the FastAPI app on :8080.
// Build: `npm run build` emits dist/, which FastAPI serves statically.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8080',
      '/internal': 'http://127.0.0.1:8080',
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
  test: {
    environment: 'jsdom',
    globals: true,               // lets testing-library auto-cleanup between tests
    setupFiles: './src/test/setup.ts',
    css: false,
  },
})
