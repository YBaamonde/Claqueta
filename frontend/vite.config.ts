import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// En desarrollo, el frontend (5173) habla con el backend (8000) a través del proxy.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 700 },
})
