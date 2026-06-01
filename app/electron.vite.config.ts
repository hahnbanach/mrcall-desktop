import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  main: {
    build: {
      outDir: 'out/main',
      rollupOptions: {
        input: { index: resolve(__dirname, 'src/main/index.ts') },
        // `ws` does an OPTIONAL `require('bufferutil')` / `require('utf-8-validate')`
        // (native speedups it works fine without — it try/catches their absence).
        // electron-vite's dev bundle tries to resolve them and dies with
        // "Could not resolve 'bufferutil' imported by 'ws'". Marking them external
        // leaves the requires as runtime calls; ws falls back to pure JS. (The prod
        // `build` already tolerated this; this makes `dev` match.)
        external: ['bufferutil', 'utf-8-validate']
      }
    }
  },
  preload: {
    build: {
      outDir: 'out/preload',
      rollupOptions: { input: { index: resolve(__dirname, 'src/preload/index.ts') } }
    }
  },
  renderer: {
    root: 'src/renderer',
    build: {
      outDir: 'out/renderer',
      rollupOptions: { input: { index: resolve(__dirname, 'src/renderer/index.html') } }
    },
    plugins: [react()],
    server: { port: 5173 }
  }
})
