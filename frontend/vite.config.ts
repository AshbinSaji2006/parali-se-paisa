import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],build:{rollupOptions:{output:{manualChunks(id){
  if(id.includes('/node_modules/leaflet/')||id.includes('/node_modules/react-leaflet/'))return 'map-vendor';
  if(id.includes('/node_modules/@tanstack/'))return 'query-vendor';
  if(id.includes('/node_modules/react/')||id.includes('/node_modules/react-dom/')||id.includes('/node_modules/scheduler/'))return 'react-vendor';
}}}},server:{proxy:{'/api':'http://127.0.0.1:8000'}},
  test:{environment:'jsdom',setupFiles:['./src/test/setup.ts'],include:['src/**/*.test.{ts,tsx}']}});
