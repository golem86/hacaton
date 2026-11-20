import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** «Результати підрозділу» (GET /v2/user/unit-results): підрозділ визначає сервер, приховані агрегати не мають балу. */
const server = await createServer({
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true },
  cacheDir: 'node_modules/.vite-unit-results-test',
  appType: 'custom',
  logLevel: 'error',
})
after(() => server.close())

const client = await server.ssrLoadModule('/src/api/client.ts')
const api = await server.ssrLoadModule('/src/api/v2User.ts')
const panel = await server.ssrLoadModule('/src/v2/UnitResultsPanel.tsx')
const personal = await server.ssrLoadModule('/src/v2/PersonalModule.tsx')

const html = (type, props) => renderToStaticMarkup(createElement(type, props))
const reply = (data, status = 200) => new Response(JSON.stringify(data), { status })
const noop = () => {}

async function withFetch(handler, run) {
  const previous = globalThis.fetch
  globalThis.fetch = handler
  try { await run() } finally { globalThis.fetch = previous }
}

// Синтетичні агрегати без персональних даних.
const components = [
  { code: 'C1', name: 'Прозорість', score: 72.5, status: 'available' },
  { code: 'C2', name: 'Підзвітність', score: null, status: 'suppressed' },
  { code: 'C3', name: 'Етика', score: 64, status: 'available' },
]
const cycles = [{ id: 7, name: 'Цикл 2026' }, { id: 4, name: 'Цикл 2025' }]
const payload = (overrides = {}) => ({
  status: 'available',
  assessment: { id: 7, name: 'Цикл 2026', status: 'closed' },
  unit: { id: 3, name: 'Кафедра 1' },
  min_group_size: 5,
  respondents: 12,
  components,
  available_assessments: cycles,
  methodology_version: 'team-results-demo-0.1',
  ...overrides,
})

test('client requests /v2/user/unit-results with session credentials and never sends unit_id', async () => {
  const calls = []
  await withFetch(async (url, init) => { calls.push({ url, init }); return reply(payload()) }, async () => {
    await api.getUnitResults()
    await api.getUnitResults(7)
    await api.getUnitResults(null)
    await api.getUnitResults(0)
    await api.getUnitResults(1.5)
  })
  assert.deepEqual(calls.map(call => call.url), [
    '/v2/user/unit-results',
    '/v2/user/unit-results?assessment_id=7',
    '/v2/user/unit-results',
    '/v2/user/unit-results',
    '/v2/user/unit-results',
  ])
  for (const call of calls) {
    assert.equal(call.init.credentials, 'include')
    assert.equal(call.init.method ?? 'GET', 'GET')
    assert.doesNotMatch(call.url, /unit_id/)
  }
})

test('client maps HTTP errors to clear Ukrainian messages', async () => {
  const cases = [
    [401, client.SESSION_EXPIRED_MESSAGE],
    [403, 'Немає доступу до результатів підрозділу.'],
    [404, 'Цикл оцінювання не знайдено.'],
    [409, 'Результати доступні лише для закритих циклів оцінювання.'],
    [503, 'Сервіс результатів тимчасово недоступний. Спробуйте пізніше.'],
    [500, 'Помилка API (500).'],
  ]
  for (const [status, message] of cases) {
    await withFetch(async () => reply({ detail: 'internal detail must not leak' }, status), async () => {
      await assert.rejects(api.getUnitResults(4), error => error instanceof client.ApiError && error.status === status && error.message === message)
    })
  }
  await withFetch(async () => { throw new TypeError('offline') }, async () => {
    await assert.rejects(api.getUnitResults(), error => error.status === 0 && /Не вдалося з’єднатися з API/.test(error.message))
  })
  await withFetch(async () => reply({ status: 'leaked' }), async () => {
    await assert.rejects(api.getUnitResults(), { message: 'API повернув некоректні результати підрозділу.' })
  })
})

test('parse: available keeps respondents and C1–C7; suppressed component never carries a score', () => {
  const parsed = api.parseUnitResults(payload({ components: [...components, { code: 'C4', name: 'Довіра', score: 55.5, status: 'suppressed' }, { code: 'C5', name: 'Без балу', score: null, status: 'available' }] }))
  assert.equal(parsed.status, 'available')
  assert.deepEqual(parsed.unit, { id: 3, name: 'Кафедра 1' })
  assert.deepEqual(parsed.assessment, { id: 7, name: 'Цикл 2026', status: 'closed' })
  assert.equal(parsed.respondents, 12)
  assert.equal(parsed.min_group_size, 5)
  assert.deepEqual(parsed.available_assessments, cycles)
  assert.deepEqual(parsed.components.map(item => [item.code, item.score, item.status]), [
    ['C1', 72.5, 'available'],
    ['C2', null, 'suppressed'],
    ['C3', 64, 'available'],
    ['C4', null, 'suppressed'],
    ['C5', null, 'suppressed'],
  ])
})

test('parse: no_unit, no_closed_cycle and insufficient_data drop respondents and components', () => {
  const noUnit = api.parseUnitResults(payload({ status: 'no_unit', unit: { id: 3, name: 'Кафедра 1' }, respondents: 9, components }))
  assert.equal(noUnit.status, 'no_unit')
  assert.equal(noUnit.unit, null)
  assert.equal(noUnit.respondents, null)
  assert.deepEqual(noUnit.components, [])

  const noCycle = api.parseUnitResults(payload({ status: 'no_closed_cycle', assessment: null, respondents: null, components: [], available_assessments: [] }))
  assert.equal(noCycle.status, 'no_closed_cycle')
  assert.equal(noCycle.assessment, null)
  assert.deepEqual(noCycle.available_assessments, [])

  const insufficient = api.parseUnitResults(payload({ status: 'insufficient_data', respondents: 3, components }))
  assert.equal(insufficient.status, 'insufficient_data')
  assert.equal(insufficient.respondents, null)
  assert.deepEqual(insufficient.components, [])
  assert.deepEqual(insufficient.unit, { id: 3, name: 'Кафедра 1' })

  assert.throws(() => api.parseUnitResults(null), client.ApiError)
  assert.throws(() => api.parseUnitResults({ ...payload(), status: 'open' }), client.ApiError)
})

test('render available: unit, cycle select, k, respondents and scores in Ukrainian format', () => {
  const markup = html(panel.UnitResultsView, { data: api.parseUnitResults(payload()), selectedId: null, onSelect: noop })
  assert.match(markup, /Результати підрозділу/)
  assert.match(markup, /Кафедра 1/)
  assert.match(markup, /<select[^>]*>.*<option value="7" selected="">Цикл 2026<\/option><option value="4">Цикл 2025<\/option>/)
  assert.match(markup, /Мінімальний розмір групи \(k\)<\/dt><dd>5<\/dd>/)
  assert.match(markup, /Респондентів<\/dt><dd>12<\/dd>/)
  assert.match(markup, /72,5<small> \/ 100<\/small>/)
  assert.match(markup, /64,0<small> \/ 100<\/small>/)
  assert.match(markup, /версія team-results-demo-0\.1/)
  assert.doesNotMatch(markup, /заблокована|Очікує погодження|контракт №5/)
})

test('render suppressed component: «Приховано (менше k)» without a score', () => {
  const markup = html(panel.UnitResultsView, { data: api.parseUnitResults(payload({ components: [{ code: 'C2', name: 'Підзвітність', score: 48.2, status: 'suppressed' }] })) })
  assert.match(markup, /data-status="suppressed"/)
  assert.match(markup, /title="Менше ніж k = 5 відповідей">Приховано \(менше k\)<\/span>/)
  assert.doesNotMatch(markup, /48,2|48\.2/)
  assert.doesNotMatch(markup, /\/ 100/)
})

test('render statuses: no_unit, no_closed_cycle, insufficient_data show explanations and no scores', () => {
  const noUnit = html(panel.UnitResultsView, { data: api.parseUnitResults(payload({ status: 'no_unit', unit: null, respondents: null, components: [] })) })
  assert.match(noUnit, /data-status="no_unit"/)
  assert.match(noUnit, /Підрозділ ще не призначено\. Його призначає власник сервера/)
  assert.doesNotMatch(noUnit, /<select/)

  const noCycle = html(panel.UnitResultsView, { data: api.parseUnitResults(payload({ status: 'no_closed_cycle', assessment: null, respondents: null, components: [], available_assessments: [] })) })
  assert.match(noCycle, /Ще немає закритих циклів/)
  assert.doesNotMatch(noCycle, /<select/)

  const insufficient = html(panel.UnitResultsView, { data: api.parseUnitResults(payload({ status: 'insufficient_data', respondents: 2, components })) })
  assert.match(insufficient, /Недостатньо анкет для показу \(менше k\)/)
  assert.match(insufficient, /менше ніж k = 5/)
  assert.match(insufficient, /Респондентів<\/dt><dd>—<\/dd>/)

  for (const markup of [noUnit, noCycle, insufficient]) {
    assert.doesNotMatch(markup, /\/ 100<\/small>/)
    assert.doesNotMatch(markup, /72,5|Прозорість/)
  }
  assert.equal(panel.unitResultsNotice({ status: 'available', min_group_size: 5 }), null)
  assert.equal(panel.formatUnitScore(72.46), '72,5')
  assert.equal(panel.formatUnitScore(null), '—')
})

test('personal module renders the unit results screen instead of the old blocked stub', async () => {
  let fetched = 0
  await withFetch(async () => { fetched += 1; return reply(payload()) }, async () => {
    const markup = html(personal.PersonalModule, { view: 'unit-results', userId: 1, userName: 'Тест', onStart: noop, onFinish: noop })
    assert.match(markup, /Завантажуємо результати підрозділу…/)
    assert.doesNotMatch(markup, /Завантажуємо персональні дані/)
  })
  // SSR не виконує ефектів: запит іде лише в браузері після монтування.
  assert.equal(fetched, 0)
  const source = await readFile(new URL('../src/v2/PersonalModule.tsx', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /Функція наразі заблокована|Очікує погодження|контракт №5/)
  const css = await readFile(new URL('../src/v2/v2.css', import.meta.url), 'utf8')
  assert.doesNotMatch(css, /v2-unit-results-blocked|v2-blocked-banner/)
  const panelSource = await readFile(new URL('../src/v2/UnitResultsPanel.tsx', import.meta.url), 'utf8')
  assert.match(panelSource, /getUnitResults\(selectedId, controller\.signal\)/)
  assert.doesNotMatch(panelSource, /unit_id/)
})

test('backend shape (routes/v2_unit_results.py): exact keys, no_unit with cycles, component insufficient_data, 422', async () => {
  const KEYS = ['assessment', 'available_assessments', 'components', 'methodology_version', 'min_group_size', 'respondents', 'status', 'unit']
  const available = api.parseUnitResults(payload({ components: [
    { code: 'C1', name: 'Прозорість', score: 64.0, status: 'available' },
    { code: 'C6', name: 'Без відповідей', score: null, status: 'insufficient_data' },
    { code: 'C7', name: 'Мало анкет', score: null, status: 'suppressed' },
  ] }))
  assert.deepEqual(Object.keys(available).sort(), KEYS)
  assert.deepEqual(available.components.map(item => [item.code, item.score, item.status]), [['C1', 64, 'available'], ['C6', null, 'insufficient_data'], ['C7', null, 'suppressed']])
  const markup = html(panel.UnitResultsView, { data: available })
  assert.match(markup, /64,0<small> \/ 100<\/small>/)
  assert.match(markup, /data-status="insufficient_data"><span class="v2-unit-results__code">C6<\/span><span class="v2-unit-results__name">Без відповідей<\/span><span class="v2-unit-results__hidden">Недостатньо даних<\/span>/)

  // Сервер для no_unit усе одно повертає найновіший закритий цикл і список циклів.
  const noUnit = api.parseUnitResults(payload({ status: 'no_unit', unit: null, respondents: null, components: [] }))
  assert.deepEqual(Object.keys(noUnit).sort(), KEYS)
  assert.deepEqual(noUnit.assessment, { id: 7, name: 'Цикл 2026', status: 'closed' })
  assert.deepEqual(noUnit.available_assessments, cycles)

  await withFetch(async () => reply({ detail: [{ loc: ['query', 'assessment_id'] }] }, 422), async () => {
    await assert.rejects(api.getUnitResults(5), error => error.status === 422 && error.message === client.DEFAULT_STATUS_MESSAGES[422])
  })
})
