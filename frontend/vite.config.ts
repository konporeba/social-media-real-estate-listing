import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/runs': 'http://localhost:8000',
      '/events': {
        target: 'http://localhost:8000',
        changeOrigin: false,
      },
      '/health': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
  },
});
