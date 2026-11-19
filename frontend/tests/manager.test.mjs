import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-manager-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const admin = await server.ssrLoadModule('/src/api/admin.ts')
const client = await server.ssrLoadModule('/src/api/client.ts')
const Manager = (await server.ssrLoadModule('/src/components/AssessmentManager.tsx')).default

test('admin cycle requests carry session CSRF and category but no role header', async () => {
  const previous = globalThis.fetch
  const calls = []
  client.setCsrfToken('test-csrf')
  try {
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options })
      return new Response(JSON.stringify(url.includes('/participation') ? { status: 'open', tokens_issued: 1, tokens_unused: null, responses_total: null, participation_percent: null } : url.includes('/tokens') ? { tokens: ['synthetic-code'] } : { id: 9, status: 'draft' }), { status: url.endsWith('/assessments') || url.includes('/tokens') ? 201 : 200 })
    }
    const payload = { name: 'Тест', start_date: '2026-11-19', categories: ['cadets'], min_group_size: 5, questionnaire_version: 'demo-v1' }
    await admin.createCycle(payload)
    await admin.activateCycle(9)
    await admin.issueAccessTokens(9, 1, 'cadets')
    await admin.getParticipation(9)
    await admin.closeCycle(9)
    assert.deepEqual(calls.map(x => x.url), ['/api/assessments', '/api/assessments/9/activate', '/api/assessments/9/tokens?count=1&category=cadets', '/api/assessments/9/participation', '/api/assessments/9/close'])
    assert.equal(JSON.parse(calls[0].options.body).questionnaire_version, 'demo-v1')
    assert.ok(calls.every(x => x.options.credentials === 'include' && !new Headers(x.options.headers).has('X-Role')))
    assert.ok(calls.filter(x => x.options.method === 'POST').every(x => new Headers(x.options.headers).get('X-CSRF-Token') === 'test-csrf'))
  } finally { globalThis.fetch = previous }
})

test('admin manager exposes cycle configuration fields', () => {
  const html = renderToStaticMarkup(React.createElement(Manager))
  for (const label of ['Назва', 'Опис', 'Обсяг', 'Початок', 'Кінець', 'Мінімальний розмір групи', 'Категорії', 'Створити чернетку']) {
    assert.ok(html.includes(label), label)
  }
})
