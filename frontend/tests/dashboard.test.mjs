import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-dashboard-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { getAssessments } = await server.ssrLoadModule('/src/api/assessments.ts')
const { getAssessmentResults } = await server.ssrLoadModule('/src/dashboard/results.ts')
const { loadResults } = await server.ssrLoadModule('/src/dashboard/loadResults.ts')
const { scoreText } = await server.ssrLoadModule('/src/dashboard/format.ts')
const { DashboardSummary } = await server.ssrLoadModule('/src/dashboard/DashboardSummary.tsx')
const { ComponentScores } = await server.ssrLoadModule('/src/dashboard/ComponentScores.tsx')
const { CategoryComparison } = await server.ssrLoadModule('/src/dashboard/CategoryComparison.tsx')

const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data })
const tick = () => new Promise((resolve) => setImmediate(resolve))
const result = (id) => ({
  assessment: { id, name: `Cycle ${id}`, status: 'closed' },
  min_group_size: 5,
  responses_total: null,
  categories: [
    { category: 'staff', responses: 4, hidden: true },
    { category: 'cadets', responses: 10, hidden: false },
  ],
  components: [{
    code: 'C1', name: 'Component', weight: 1, score: null,
    by_category: [
      { category: 'staff', score: 73.1, hidden: true },
      { category: 'cadets', score: null, hidden: false },
    ],
    objective_indicators: [],
  }],
})

test('public assessment list omits cookies and parses assessment JSON', async () => {
  const oldFetch = globalThis.fetch
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(url, '/api/assessments')
      assert.equal(options.credentials, 'omit')
      assert.equal(new Headers(options.headers).has('X-Role'), false)
      return response([{ id: 1, name: 'Cycle 1', start_date: '2026-11-16', status: 'closed', min_group_size: 5 }])
    }
    assert.equal((await getAssessments())[0].id, 1)
  } finally { globalThis.fetch = oldFetch }
})

test('null scores and response totals do not render as zero', () => {
  assert.equal(scoreText(null), 'Немає даних')
  const data = result(1)
  const html = renderToStaticMarkup(createElement('div', null,
    createElement(DashboardSummary, { results: data }),
    createElement(ComponentScores, { components: data.components }),
    createElement(CategoryComparison, { categories: data.categories, components: data.components }),
  ))
  assert.match(html, /Приховано/)
  assert.match(html, /Немає даних/)
  assert.doesNotMatch(html, />0 зі 100</)
  assert.doesNotMatch(html, /width:0%/)
})

test('legacy hidden categories are dropped entirely (no name, no numbers) even if the API sends them', () => {
  const data = result(1)
  const html = renderToStaticMarkup(createElement(CategoryComparison, {
    categories: data.categories, components: data.components,
  }))
  assert.doesNotMatch(html, /73[,.]1/)
  assert.doesNotMatch(html, /4 відповідей/)
  assert.doesNotMatch(html, /Персонал/, 'the hidden category is not even named')
  assert.match(html, /Частину груп приховано для захисту анонімності \(менше k відповідей\)/)
})

test('409 for an open cycle has the approved message and API errors stay handled', async () => {
  const oldFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => response({}, 409)
    await assert.rejects(getAssessmentResults(3), (error) => error.status === 409 && /після закриття/.test(error.message))
    for (const status of [401, 403, 404]) {
      globalThis.fetch = async () => response({}, status)
      await assert.rejects(getAssessmentResults(1), (error) => error.status === status && error.message.length > 0)
    }
    globalThis.fetch = async () => { throw new TypeError('offline') }
    await assert.rejects(getAssessmentResults(1), (error) => error.status === 0 && /з’єднатися/.test(error.message))
    globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError('bad JSON') } })
    await assert.rejects(getAssessmentResults(1), (error) => /JSON/.test(error.message))
  } finally { globalThis.fetch = oldFetch }
})

test('rapid cycle switching aborts the old request and ignores its late response', async () => {
  const oldFetch = globalThis.fetch
  const pending = new Map()
  const seen = []
  const errors = []
  try {
    globalThis.fetch = (url, options) => new Promise((resolve) => pending.set(url, { resolve, signal: options.signal }))
    const cancelOld = loadResults(1, (data) => seen.push(data.assessment.id), (message) => errors.push(message), () => {})
    cancelOld()
    assert.equal(pending.get('/api/assessments/1/results').signal.aborted, true)
    loadResults(2, (data) => seen.push(data.assessment.id), (message) => errors.push(message), () => {})
    pending.get('/api/assessments/2/results').resolve(response(result(2)))
    await tick()
    pending.get('/api/assessments/1/results').resolve(response(result(1)))
    await tick()
    assert.deepEqual(seen, [2])
    assert.deepEqual(errors, [])
  } finally { globalThis.fetch = oldFetch }
})

test('Dashboard loader reports 409 and network failures without unhandled rejection', async () => {
  const oldFetch = globalThis.fetch
  const errors = []
  const completed = []
  try {
    globalThis.fetch = async () => response({}, 409)
    loadResults(3, () => assert.fail('unexpected results'), (message) => errors.push(message), () => completed.push(3))
    await tick()
    assert.match(errors[0], /після закриття/)
    assert.deepEqual(completed, [3])

    globalThis.fetch = async () => { throw new TypeError('offline') }
    loadResults(1, () => assert.fail('unexpected results'), (message) => errors.push(message), () => completed.push(1))
    await tick()
    assert.match(errors[1], /з’єднатися/)
    assert.deepEqual(completed, [3, 1])
  } finally { globalThis.fetch = oldFetch }
})
