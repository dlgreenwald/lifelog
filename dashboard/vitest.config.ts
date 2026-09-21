import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
  coverage: {
    provider: 'v8',
    reporter: ['text', 'html'],
    include: ['src/**'],
    exclude: ['src/test/**', 'src/**/*.test.*', 'src/test/setup.ts'],
  },
});
