import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const { VITE_API_PROXY_TARGET, VITE_QUESTIONNAIRE_TEST_API_TARGET } = loadEnv(mode, '.', 'VITE_')
  const proxy = {
    ...(VITE_API_PROXY_TARGET ? {
      '/api': { target: VITE_API_PROXY_TARGET, changeOrigin: true },
      '/v2': { target: VITE_API_PROXY_TARGET, changeOrigin: true },
    } : {}),
    // Лише dev-сервер E2E: синтетичний API прототипу офіційних анкет. У production-збірку не потрапляє.
    ...(VITE_QUESTIONNAIRE_TEST_API_TARGET ? {
      '/prototype-test-api': {
        target: VITE_QUESTIONNAIRE_TEST_API_TARGET,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/prototype-test-api/, '/prototype/integration'),
      },
    } : {}),
  }
  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: Object.keys(proxy).length ? proxy : undefined,
    },
  }
})
