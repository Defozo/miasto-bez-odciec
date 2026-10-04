import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react(), {name:'offline-asset-manifest',generateBundle(_options,bundle) {this.emitFile({type:'asset',fileName:'precache-manifest.json',source:JSON.stringify(Object.keys(bundle).filter(name=>!name.endsWith('.map')).map(name=>`/${name}`))});}}],
  server: {
    host: '127.0.0.1',
    port: 5178,
    proxy: {
      '/api': { target: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: false, headers: {Origin: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000'} },
      '/health': { target: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  build: { sourcemap: true, rollupOptions: { output: { manualChunks: { map: ['maplibre-gl'] } } } },
});
