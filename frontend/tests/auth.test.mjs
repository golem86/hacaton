import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-auth-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const auth = await server.ssrLoadModule('/src/api/auth.ts')
const reply = (data, status = 200) => new Response(JSON.stringify(data), { status })

test('pre-auth and verified requests use session cookies, CSRF and no X-Role', async () => {
  const oldFetch = globalThis.fetch
  const seen = []
  try {
    globalThis.fetch = async (url, options) => {
      const headers = new Headers(options.headers)
      seen.push({ url, credentials: options.credentials, csrf: headers.get('X-CSRF-Token'), role: headers.get('X-Role') })
      if (url.endsWith('/csrf')) return reply({ csrf_token: 'preauth-csrf' })
      if (url.endsWith('/login')) return reply({ requires_2fa: true, csrf_token: 'pending-csrf', user: { name: 'Admin', role: 'admin' } })
      if (url.endsWith('/2fa/verify')) return reply({ id: 1, name: 'Admin', email: 'admin@example.test', role: 'admin', two_factor_verified: true, csrf_token: 'session-csrf' })
      return reply({ status: 'logged_out' })
    }
    await auth.ensureCsrf()
    const pending = await auth.loginUser({ email: 'admin@example.test', password: 'not-a-real-password' })
    assert.equal(pending.requires_2fa, true)
    const user = await auth.verifyTwoFactor('123456')
    assert.equal(user.two_factor_verified, true)
    await auth.logoutUser()
    assert.deepEqual(seen.map(x => x.url), ['/v2/auth/csrf', '/v2/auth/login', '/v2/auth/2fa/verify', '/v2/auth/logout'])
    assert.ok(seen.slice(1).every(x => x.credentials === 'include' && x.role === null))
    assert.equal(seen[1].csrf, 'preauth-csrf')
    assert.equal(seen[2].csrf, 'pending-csrf')
    assert.equal(seen[3].csrf, 'session-csrf')
  } finally { globalThis.fetch = oldFetch }
})

test('anonymous Survey API helper omits cookies and CSRF headers', async () => {
  const oldFetch = globalThis.fetch
  try {
    globalThis.fetch = async (_url, options) => {
      assert.equal(options.credentials, 'omit')
      const headers = new Headers(options.headers)
      assert.equal(headers.has('X-CSRF-Token'), false)
      assert.equal(headers.has('X-Role'), false)
      return reply({ status: 'accepted' }, 201)
    }
    const result = await auth.postPublicV2Json('/api/assessments/1/submissions', { token: 'one-time' })
    assert.equal(result.status, 'accepted')
  } finally { globalThis.fetch = oldFetch }
})
