import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// MapLibre GL JS ships its own Web Worker. When Vite optimises deps
// it cannot follow the worker URL inside the maplibre bundle.
// Excluding it from optimisation lets Vite serve it as-is.
export default defineConfig({
  plugins: [react()],
  optimizeDeps: {
    exclude: ['maplibre-gl'],
  },
});
