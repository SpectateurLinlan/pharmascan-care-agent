import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The dev server proxies /api to the FastAPI backend so the browser never
// needs to know the backend origin and CORS stays simple in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    globals: true,
    environment: 'node',
    setupFiles: ['./src/test-setup.ts'],
    // Allow extension-less imports of .tsx components from tests; Vite's
    // default list does not include .tsx for the SSR/node resolver.
    resolve: {
      extensions: ['.ts', '.tsx', '.js', '.jsx', '.json'],
    },
  },
});
