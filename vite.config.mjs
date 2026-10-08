import {fileURLToPath} from 'node:url';
import {defineConfig} from 'vite';

const webRoot = fileURLToPath(new URL('./knowledge/web', import.meta.url));
const backend = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

export default defineConfig({
  root: webRoot,
  publicDir: false,
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    fs: {allow: [webRoot]},
    proxy: {
      '/api': {
        target: backend,
        changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (upstream, request) => {
            // The backend checks Origin. Translate the frontend's own origin only;
            // preserve unrelated origins so the backend can still reject them.
            if (request.headers.origin === `http://${request.headers.host}`) {
              upstream.setHeader('Origin', new URL(backend).origin);
            }
          });
        },
        // Answers can stream for several minutes while evidence is checked.
        timeout: 310_000,
        proxyTimeout: 310_000,
      },
    },
  },
});
