import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { after, before, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

let api
let view
let server
const originalFetch = globalThis.fetch

before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-unit-results-test', appType: 'custom', logLevel: 'error' })
  api = await server.ssrLoadModule('/src/api/v2User.ts')
  view = await server.ssrLoadModule('/src/v2/UnitResults.tsx')
})
after(async () => { globalThis.fetch = originalFetch; await server?.close() })

const reply = (value, status = 200) => new Response(JSON.stringify(value), { status })
function mockFetch(handler) {
  const calls = []
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return handler(url, options) }
  return calls
}

// Синтетичні агрегати без персональних даних.
const components = [
  { code: 'C1', name: 'Прозорість', score: 72.5, status: 'available' },
  { code: 'C2', name: 'Підзвітність', score: null, status: 'insufficient_data' },
  { code: 'C3', name: 'Етика', score: 0, status: 'available' },
]
const available = {
  assessment: { id: 7, name: 'Цикл 2026', status: 'closed' }, unit: 'Факультет 1',
  methodology_version: 'unit-mean-0-100-v1', min_group_size: 5, privacy_status: 'available', responses: 12, components,
}
const suppressed = { ...available, privacy_status: 'suppressed', responses: null, components: components.map(c => ({ ...c, score: null, status: 'suppressed' })) }
const noUnit = { ...suppressed, unit: null, privacy_status: 'no_unit', components: [] }

test('getUnitResults calls the V2 user route with credentials, signal and no CSRF header', async () => {
  const controller = new AbortController()
  const calls = mockFetch(() => reply(available))
  const result = await api.getUnitResults(7, controller.signal)
  assert.deepEqual(result, available)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/v2/user/unit-results?assessment_id=7')
  assert.equal(calls[0].options.credentials, 'include')
  assert.equal(calls[0].options.signal, controller.signal)
  assert.equal((calls[0].options.method ?? 'GET').toUpperCase(), 'GET')
  assert.equal(new Headers(calls[0].options.headers).has('X-CSRF-Token'), false)
})

test('getUnitResults accepts suppressed and no_unit shapes', async () => {
  mockFetch(() => reply(suppressed))
  assert.equal((await api.getUnitResults(7)).privacy_status, 'suppressed')
  mockFetch(() => reply(noUnit))
  const result = await api.getUnitResults(7)
  assert.equal(result.unit, null)
  assert.equal(result.responses, null)
})

test('getUnitResults maps 404/409/403 to client messages and never shows server detail', async () => {
  const secret = 'internal-detail-Факультет 9 has 3 responses'
  for (const [status, pattern] of [[404, /Цикл не знайдено/], [409, /після закриття циклу/], [403, /лише користувачам/], [500, /Помилка API \(500\)/]]) {
    mockFetch(() => reply({ detail: secret }, status))
    await assert.rejects(api.getUnitResults(7), error => {
      assert.equal(error.name, 'ApiError')
      assert.equal(error.status, status)
      assert.match(error.message, pattern)
      assert.equal(error.message.includes(secret), false)
      return true
    })
  }
})

test('getUnitResults rejects invalid ids without a request', async () => {
  const calls = mockFetch(() => reply(available))
  for (const id of [0, -1, 1.5, Number.NaN]) await assert.rejects(api.getUnitResults(id), /Оберіть цикл/)
  assert.equal(calls.length, 0)
})

test('getUnitResults rejects malformed or privacy-inconsistent shapes', async () => {
  const cases = [
    [],
    { ...available, assessment: { ...available.assessment, status: 'open' } },
    { ...available, assessment: { ...available.assessment, id: 8 } },
    { ...available, assessment: { ...available.assessment, id: '7' } },
    { ...available, privacy_status: 'other' },
    { ...available, min_group_size: 0 },
    { ...available, methodology_version: 1 },
    { ...available, unit: null },
    { ...available, responses: null },
    { ...available, responses: -1 },
    { ...available, responses: 1.5 },
    { ...suppressed, responses: 3 },
    { ...noUnit, unit: 'Факультет 1' },
    { ...available, components: {} },
    { ...available, components: [{ ...components[0], score: 101 }] },
    { ...available, components: [{ ...components[0], score: '72' }] },
    { ...available, components: [{ ...components[0], score: null }] },
    { ...available, components: [{ ...components[1], score: 40 }] },
    { ...available, components: [{ ...components[0], status: 'unknown' }] },
    { ...available, components: [components[0], components[0]] },
    { ...suppressed, components: [components[0]] },
  ]
  for (const body of cases) {
    mockFetch(() => reply(body))
    await assert.rejects(api.getUnitResults(7), /API повернув некоректну відповідь/)
  }
  mockFetch(() => new Response('{', { status: 200 }))
  await assert.rejects(api.getUnitResults(7), /API повернув некоректну відповідь/)
})

test('closedCycles keeps only closed cycles ordered by start date', () => {
  const cycle = (id, start_date, status) => ({ id, name: `Цикл ${id}`, start_date, status, min_group_size: 5 })
  const list = view.closedCycles([cycle(1, '2026-03-01', 'closed'), cycle(2, '2026-09-01', 'open'), cycle(3, '2025-01-01', 'closed'), cycle(4, '2026-06-01', 'closed')])
  assert.deepEqual(list.map(c => c.id), [3, 1, 4])
})

const html = result => renderToStaticMarkup(createElement(view.UnitResultsView, { result }))

test('available state renders unit, count, table with scores and aggregate note', () => {
  const markup = html(available)
  assert.match(markup, /Факультет 1/)
  assert.match(markup, />≥ 12<small> відповідей<\/small>/)
  assert.match(markup, /округлено вниз до 5/)
  assert.match(markup, /<table class="v2-unit-table"/)
  assert.match(markup, /<caption[^>]*>Компоненти C1–C7/)
  assert.match(markup, /<th scope="row">C1<\/th><td>Прозорість<\/td><td class="v2-unit-score">72,5<\/td>/)
  assert.match(markup, /aria-hidden="true"><i style="width:72.5%"/)
  assert.match(markup, /Недостатньо даних/)
  assert.match(markup, /не оцінка окремих осіб/)
  assert.match(markup, /unit-mean-0-100-v1/)
})

test('suppressed state hides scores and any response count', () => {
  const markup = html(suppressed)
  assert.match(markup, /role="status"/)
  assert.match(markup, /приховано для захисту анонімності/i)
  assert.match(markup, /менше ніж 5 відповідей/)
  assert.doesNotMatch(markup, /<table/)
  assert.doesNotMatch(markup, /Кількість відповідей/)
})

test('no_unit state explains that only the server owner assigns units', () => {
  const markup = html(noUnit)
  assert.match(markup, /Підрозділ не призначено/)
  assert.match(markup, /лише власник сервера/)
  assert.match(markup, /адміністратора/)
  assert.doesNotMatch(markup, /<table/)
})

test('blocked placeholder is gone from the personal module', () => {
  const source = readFileSync(new URL('../src/v2/PersonalModule.tsx', import.meta.url), 'utf8')
  const css = readFileSync(new URL('../src/v2/v2.css', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /Очікує погодження|контракту №5|v2-blocked-banner/)
  assert.doesNotMatch(css, /v2-blocked-banner|v2-unit-results-blocked/)
  assert.match(source, /<UnitResultsScreen \/>/)
})
