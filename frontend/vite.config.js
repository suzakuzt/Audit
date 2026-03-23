import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/static/foundation/',
  build: {
    outDir: '../src/audit_system/frontend_dist',
    emptyOutDir: true,
  },
});
