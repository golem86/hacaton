import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'

const server = await createServer({
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true },
  cacheDir: 'node_modules/.vite-public-routes-test',
  appType: 'custom',
  logLevel: 'error',
})
after(() => server.close())
const routes = await server.ssrLoadModule('/src/v2/publicRoutes.ts')

test('public auth routes restore the correct page, including 2FA and password reset', () => {
  for (const [page, path] of [
    ['login', '/login'],
    ['register', '/register'],
    ['two-factor', '/login/2fa'],
    ['reset-request', '/login/reset'],
    ['reset-confirm', '/login/reset/confirm'],
  ]) {
    assert.equal(routes.publicPageFromPath(path), page)
    assert.equal(routes.pathForPublicPage(page), path)
  }
  assert.equal(routes.publicPageFromPath('/unknown'), 'login')
})
