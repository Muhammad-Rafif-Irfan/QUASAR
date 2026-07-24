import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: true,
    host: true, // allows external access
    port: 5173, // optional (can also be set in .env or passed via env.PORT)
  },
})
