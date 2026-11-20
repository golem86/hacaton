import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true },
  cacheDir: 'node_modules/.vite-overview-test',
  appType: 'custom',
  logLevel: 'error',
})
after(() => server.close())

const maturity = await server.ssrLoadModule('/src/dashboard/maturity.ts')
const {
  ExecutiveOverview, ExecutiveOverviewView, gapSignals, loadOverview, navigateTo, previousClosedCycle,
} = await server.ssrLoadModule('/src/dashboard/ExecutiveOverview.tsx')
const { ComponentDetail } = await server.ssrLoadModule('/src/dashboard/ComponentDetail.tsx')
const { ComponentScores } = await server.ssrLoadModule('/src/dashboard/ComponentScores.tsx')
const { DEMO_METHODOLOGY } = await server.ssrLoadModule('/src/api/analytics.ts')

const html = element => renderToStaticMarkup(element)
const tick = () => new Promise(resolve => setImmediate(resolve))
const settle = async () => { for (let i = 0; i < 10; i += 1) await tick() }
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data })
const between = (markup, start, end) => {
  const from = markup.indexOf(start)
  assert.notEqual(from, -1, `missing ${start}`)
  const to = end ? markup.indexOf(end, from) : -1
  return markup.slice(from, to === -1 ? undefined : to)
}

const WEIGHTS = { C1: 0.15, C2: 0.15, C3: 0.15, C4: 0.2, C5: 0.1, C6: 0.15, C7: 0.1 }
const SCORES = { C1: 82.5, C2: 76, C3: 61.2, C4: 44.1, C5: 25, C6: 58.3, C7: 50 }
const cycle = (id, name, start_date, status = 'closed') => ({ id, name, start_date, status, min_group_size: 5 })
const assessments = [
  cycle(1, 'Осінь 2025', '2025-11-01'),
  cycle(2, 'Весна 2026', '2026-03-01'),
  cycle(3, 'Осінь 2026', '2026-11-01', 'open'),
  cycle(4, 'Архів 2024', '2024-05-01'),
]
const ref = id => ({ id, name: assessments.find(item => item.id === id).name, status: 'closed' })

function results(id, overrides = {}) {
  const scores = { ...SCORES, ...overrides }
  return {
    assessment: ref(id),
    min_group_size: 5,
    responses_total: 40,
    categories: [
      { category: 'cadets', responses: 30, hidden: false },
      { category: 'staff', responses: null, hidden: true },
    ],
    components: Object.keys(WEIGHTS).reverse().map(code => ({
      code, name: `Компонент ${code}`, weight: WEIGHTS[code], score: scores[code],
      by_category: [
        { category: 'cadets', score: scores[code], hidden: false },
        { category: 'staff', score: 12.3, hidden: true },
      ],
      objective_indicators: [],
    })),
  }
}

function indexData(id, value, scores = SCORES) {
  return {
    assessment: ref(id), methodology_version: DEMO_METHODOLOGY, approval_status: 'proposed',
    synthetic_only: true, official: false, status: value === null ? 'insufficient_data' : 'ok', index: value, warnings: [],
    components: Object.keys(WEIGHTS).map(code => ({
      code, name: `Компонент ${code}`, score: scores[code], weight: WEIGHTS[code],
      contribution: scores[code] === null ? null : Math.round(scores[code] * WEIGHTS[code] * 100) / 100,
      status: scores[code] === null ? 'missing' : 'ok',
    })),
  }
}

const methodology = {
  version: DEMO_METHODOLOGY, approval_status: 'proposed', synthetic_only: true, official: false,
  formula: 'sum(component_score * component_weight)',
  weights: { C1: '0.15', C2: '0.15', C3: '0.15', C4: '0.20', C5: '0.10', C6: '0.15', C7: '0.10' },
  limitations: ['Synthetic components only'],
}
const proposal = (id, rule_id, component_code, text) => ({ id, rule_id, component_code, text, status: 'proposed', requires_human_decision: true })
const recommendations = id => ({
  assessment: ref(id), methodology_version: DEMO_METHODOLOGY, approval_status: 'proposed', persistence: 'none',
  proposals: [
    proposal('r1', 'LOW_SCORE_LT_50_V1', 'C4', 'Переглянути практики компонента C4.'),
    proposal('r2', 'LOW_SCORE_LT_50_V1', 'C5', 'Переглянути практики компонента C5.'),
    proposal('r3', 'CATEGORY_GAP_GE_25_V1', 'C5', 'Перевірити трактування питання C5.'),
  ],
})
const gap = (component_code, status, gap_points, flag) => ({
  component_code, left_category: 'cadets', right_category: 'mgmt', status, gap_points, flag, interpretation: 'Review signal',
})
const comparisons = id => ({
  assessment: ref(id), methodology_version: DEMO_METHODOLOGY, period_comparison: null,
  category_comparisons: [
    gap('C1', 'unavailable', null, null),
    gap('C2', 'ok', 5, false),
    gap('C3', 'unavailable', 91.7, true),
    gap('C4', 'ok', 30, true),
    gap('C5', 'ok', -26, true),
  ],
})

/** Routes analytics URLs; `status` forces an error code for the demo-gated endpoints. */
function analyticsFetch(seen, { status = 200 } = {}) {
  return async url => {
    seen.push(url)
    if (url === `/api/index-methodologies/${DEMO_METHODOLOGY}`) return response(methodology)
    if (status !== 200) return response({ detail: 'disabled' }, status)
    const id = Number(/assessments\/(\d+)\/|assessment_id=(\d+)/.exec(url).slice(1).find(Boolean))
    if (url.includes('/index?')) return response(indexData(id, id === 2 ? 48.37 : 45.12))
    if (url.includes('/recommendations?')) return response(recommendations(id))
    if (url.includes('/analytics/comparisons?')) return response(comparisons(id))
    return response({}, 404)
  }
}

async function loadState(id, previousId, fetchImpl) {
  const oldFetch = globalThis.fetch
  const state = {}
  try {
    globalThis.fetch = fetchImpl
    const stop = loadOverview(id, previousId, patch => Object.assign(state, patch))
    await settle()
    stop()
  } finally { globalThis.fetch = oldFetch }
  return state
}

test('zone thresholds: inclusive lower bound, exclusive upper bound, 50 matches LOW_SCORE_LT_50_V1', () => {
  const { scoreZone, ZONE_THRESHOLDS } = maturity
  assert.deepEqual(ZONE_THRESHOLDS, { critical: 30, problem: 50, strength: 75 })
  const cases = [
    [0, 'critical'], [29.9, 'critical'], [29.99, 'critical'], [30, 'problem'], [49.9, 'problem'], [49.99, 'problem'],
    [50, 'stable'], [74.9, 'stable'], [74.99, 'stable'], [75, 'strength'], [99.9, 'strength'], [100, 'strength'],
  ]
  for (const [score, zone] of cases) assert.equal(scoreZone(score), zone, `score ${score}`)
})

test('null, hidden-like and out-of-scale values are "no data", never zero', () => {
  const { describeScore, levelText, maturityLevel, scoreZone, zoneColor, ZONE_META } = maturity
  for (const value of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, -0.1, 100.1, '50']) {
    assert.equal(scoreZone(value), 'none', `zone of ${String(value)}`)
    assert.equal(maturityLevel(value), null, `level of ${String(value)}`)
    assert.equal(levelText(value), 'Немає даних')
    assert.equal(describeScore(value), 'Немає даних')
    assert.equal(zoneColor(value), ZONE_META.none.color)
  }
  assert.notEqual(scoreZone(0), 'none')
  assert.equal(maturityLevel(0).level, 1)
})

test('maturity levels use 20-point bands with labels', () => {
  const { maturityLevel, levelText, MATURITY_LEVELS } = maturity
  const cases = [
    [0, 1], [19.99, 1], [20, 2], [39.9, 2], [40, 3], [59.99, 3], [60, 4], [79.9, 4], [80, 5], [100, 5],
  ]
  for (const [score, level] of cases) assert.equal(maturityLevel(score).level, level, `score ${score}`)
  assert.deepEqual(MATURITY_LEVELS.map(item => item.label), ['Початковий', 'Базовий', 'Середній', 'Розвинений', 'Зразковий'])
  assert.equal(levelText(44.1), 'Рівень 3 · Середній')
})

test('delta formatting is signed, rounded to 0.01 and never shows −0', () => {
  const { formatDeltaPoints } = maturity
  assert.equal(formatDeltaPoints(48.37 - 45.12), '+3,25 п.п.')
  assert.equal(formatDeltaPoints(-1.2), '−1,2 п.п.')
  assert.equal(formatDeltaPoints(0), '0 п.п.')
  assert.equal(formatDeltaPoints(-0.001), '0 п.п.')
})

test('legend shows the thresholds that colour the data', () => {
  const markup = html(createElement(maturity.ZoneLegend))
  assert.match(markup, /не офіційна шкала/)
  assert.match(markup, /Критична &lt; 30/)
  assert.match(markup, /Проблемна 30 – &lt;50/)
  assert.match(markup, /Стабільна 50 – &lt;75/)
  assert.match(markup, /Сильна ≥ 75/)
  assert.match(markup, /Немає даних/)
})

test('previous closed cycle follows start_date, not id, and skips open cycles', () => {
  assert.equal(previousClosedCycle(assessments, 2).id, 1)
  assert.equal(previousClosedCycle(assessments, 1).id, 4)
  assert.equal(previousClosedCycle(assessments, 4), null)
  assert.equal(previousClosedCycle(assessments, 3), null)
  assert.equal(previousClosedCycle([], 2), null)
})

test('only visible flagged pairs count as category-gap signals', () => {
  assert.equal(gapSignals(comparisons(2)), 2)
})

test('ExecutiveOverview with the index: number, zone, level, delta, counters and drill-down lists', async () => {
  const seen = []
  const state = await loadState(2, 1, analyticsFetch(seen))
  assert.equal(state.index.status, 'success')
  assert.equal(state.previousIndex.status, 'success')
  assert.ok(seen.includes('/api/assessments/1/index?methodology=team-results-demo-0.1'))
  const markup = html(createElement(ExecutiveOverviewView, { results: results(2), previous: assessments[0], state }))

  const index = between(markup, 'exec-index-heading', 'exec-radar-heading')
  assert.match(index, /<strong>48,37<\/strong><span>зі 100<\/span>/)
  assert.match(index, /Проблемна зона/)
  assert.match(index, /Рівень зрілості 3 з 5 · Середній/)
  assert.match(index, /\+3,25 п\.п\.<\/strong> зростання порівняно з «Осінь 2025» \(45,12 → 48,37\)/)
  assert.match(index, /Методика team-results-demo-0\.1 · демонстраційна методика, статус: запропонована · лише синтетичні дані/)

  assert.match(markup, /Рекомендації за правилами<\/h3><p class="exec-signal-value">3<\/p>/)
  assert.match(markup, /Сигнали розривів між категоріями<\/h3><p class="exec-signal-value">2<\/p>/)
  assert.match(markup, /LOW_SCORE_LT_50_V1: 2/)
  assert.match(markup, /Переглянути рекомендації/)
  assert.match(markup, /Переглянути порівняння/)

  const strengths = between(markup, 'exec-strengths-heading', 'exec-weak-heading')
  assert.ok(strengths.indexOf('Компонент C1') < strengths.indexOf('Компонент C2'), 'strongest first')
  assert.doesNotMatch(strengths, /Компонент C3|Компонент C7/)
  const weak = between(markup, 'exec-weak-heading', 'exec-signal')
  assert.ok(weak.indexOf('Компонент C5') !== -1 && weak.indexOf('Компонент C5') < weak.indexOf('Компонент C4'), 'weakest first')
  assert.match(weak, /Критична/)
  assert.match(weak, /2 рекомендації/)
  assert.match(weak, /aria-expanded="false" aria-controls="overview-component-detail"/)
  assert.doesNotMatch(weak, /Компонент C7/, '50 is stable, not a problem')

  assert.match(markup, /Пунктиром показано попередній закритий цикл|пунктиром показано попередній закритий цикл/)
  assert.match(markup, /C4, Компонент C4: 44[,.]1 зі 100; Проблемна зона, рівень зрілості 3 з 5 «Середній»; попередній цикл: 44[,.]1 зі 100/)
  assert.match(markup, /Відповідей у циклі/)
  assert.match(markup, /Як визначено зони, рівні зрілості та індекс/)
  assert.doesNotMatch(markup, /12[,.]3/, 'hidden category scores never render')
  assert.doesNotMatch(markup, /Спробувати ще раз/)
})

test('ExecutiveOverview opens the drill-down card for the selected component', async () => {
  const state = await loadState(2, 1, analyticsFetch([]))
  const markup = html(createElement(ExecutiveOverviewView, {
    results: results(2), previous: assessments[0], state, selectedCode: 'C4',
  }))
  const detail = between(markup, 'id="overview-component-detail"', 'exec-signals')
  assert.match(detail, /Деталізація компонента/)
  assert.match(detail, /0,2 \(20 % індексу\)/)
  assert.match(detail, /8,82 бала індексу/)
  assert.match(detail, /Переглянути практики компонента C4\./)
  assert.doesNotMatch(detail, /компонента C5/)
  assert.match(detail, /Зміна до «Осінь 2025»/)
  assert.match(markup, /aria-expanded="true" aria-controls="overview-component-detail"/)
})

test('ExecutiveOverview with HTTP 503 keeps results-based parts and explains why analytics are missing', async () => {
  const seen = []
  const state = await loadState(2, 1, analyticsFetch(seen, { status: 503 }))
  assert.equal(state.index.status, 'error')
  assert.equal(state.index.httpStatus, 503)
  assert.equal(state.methodology.status, 'success')
  const markup = html(createElement(ExecutiveOverviewView, { results: results(2, { C6: null }), previous: assessments[0], state }))

  assert.match(markup, /role="status"><strong>Integrity Index, рекомендації та сигнали розривів зараз недоступні/)
  assert.match(markup, /Аналітичний модуль не ввімкнений у конфігурації сервера/)
  assert.match(markup, /Індекс не сформовано: аналітичний модуль вимкнено на сервері/)
  assert.match(markup, /Індекс попереднього циклу «Осінь 2025» недоступний/)
  assert.match(markup, /Методика team-results-demo-0\.1/)
  assert.match(markup, /exec-signal-unavailable">Недоступно/)
  assert.doesNotMatch(markup, /Спробувати ще раз/, '503 is not retryable')

  assert.match(markup, /C1, Компонент C1: 82[,.]5 зі 100; Сильна сторона/)
  assert.match(between(markup, 'exec-strengths-heading', 'exec-weak-heading'), /Компонент C1/)
  assert.match(between(markup, 'exec-weak-heading', 'exec-signal'), /Компонент C5/)
  assert.match(markup, /Без бала \(приховано або немає даних\), зону не визначено: <span><button[^>]*>C6 · Компонент C6/)
  assert.match(markup, /C6, Компонент C6: Немає даних; Немає даних/)
  assert.doesNotMatch(markup, />0 зі 100</)
  assert.match(markup, /Відповідей у циклі/)
})

test('ExecutiveOverview with HTTP 409 explains the methodology mismatch', async () => {
  const state = await loadState(2, null, analyticsFetch([], { status: 409 }))
  const markup = html(createElement(ExecutiveOverviewView, { results: results(2), previous: null, state }))
  assert.match(markup, /не відповідають демонстраційній методиці/)
  assert.doesNotMatch(markup, /Спробувати ще раз/)
})

test('ExecutiveOverview without a previous closed cycle says so and fetches no other index', async () => {
  const seen = []
  const previous = previousClosedCycle(assessments, 4)
  assert.equal(previous, null)
  const state = await loadState(4, null, analyticsFetch(seen))
  assert.equal(state.previousIndex.status, 'idle')
  assert.deepEqual(seen.filter(url => url.includes('/index?')), ['/api/assessments/4/index?methodology=team-results-demo-0.1'])
  const markup = html(createElement(ExecutiveOverviewView, { results: results(4), previous, state }))
  assert.match(markup, /Попереднього закритого циклу немає\./)
  assert.match(markup, /45,12/)
  assert.doesNotMatch(markup, /п\.п\.<\/strong>/)
})

test('a network error offers a retry, unlike 503 and 409', async () => {
  const state = await loadState(2, null, async () => { throw new TypeError('offline') })
  assert.equal(state.index.httpStatus, 0)
  const markup = html(createElement(ExecutiveOverviewView, { results: results(2), previous: null, state, onRetry: () => {} }))
  assert.match(markup, /з’єднатися/)
  assert.match(markup, /Спробувати ще раз/)
})

test('cycle change aborts overview requests and ignores late answers', async () => {
  const oldFetch = globalThis.fetch
  const pending = []
  const patches = []
  try {
    globalThis.fetch = (url, options) => new Promise(resolve => pending.push({ url, resolve, signal: options.signal }))
    const stop = loadOverview(2, 1, patch => patches.push(patch))
    assert.equal(pending.length, 5)
    stop()
    assert.ok(pending.every(item => item.signal.aborted))
    const route = analyticsFetch([])
    for (const item of pending) item.resolve(await route(item.url))
    await settle()
    assert.equal(patches.length, 1, 'only the initial loading state')
    assert.equal(patches[0].index.status, 'loading')
  } finally { globalThis.fetch = oldFetch }
})

test('navigation buttons use the same pushState + popstate route change as main.tsx', () => {
  const saved = { history: globalThis.history, window: globalThis.window, PopStateEvent: globalThis.PopStateEvent }
  const pushed = []
  const events = []
  try {
    globalThis.history = { pushState: (...args) => pushed.push(args) }
    globalThis.window = { dispatchEvent: event => events.push(event.type) }
    globalThis.PopStateEvent = class { constructor(type) { this.type = type } }
    navigateTo('/admin/analytics')
    assert.deepEqual(pushed, [[{}, '', '/admin/analytics']])
    assert.deepEqual(events, ['popstate'])
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[key]
      else globalThis[key] = value
    }
  }
})

test('stateful ExecutiveOverview renders loading states and accepts a KPI slot', () => {
  const markup = html(createElement(ExecutiveOverview, {
    results: results(2), assessments, kpis: createElement('p', null, 'KPI-SLOT'),
  }))
  assert.match(markup, /Завантажуємо індекс…/)
  assert.match(markup, /Завантажуємо індекс циклу «Осінь 2025»…/)
  assert.match(markup, /KPI-SLOT/)
  assert.doesNotMatch(markup, /Відповідей у циклі/)
})

test('ComponentDetail drops legacy hidden categories entirely and never colours them', () => {
  const component = {
    code: 'C2', name: 'Компонент C2', weight: 0.15, score: 80,
    by_category: [
      { category: 'cadets', score: 78.4, hidden: false },
      { category: 'staff', score: 12.3, hidden: true },
      { category: 'mgmt', score: 9.9, hidden: false },
      { category: 'npp', score: null, hidden: false },
    ],
    objective_indicators: [
      { name: 'Охоплення навчанням, %', value: 87.5, confirmed: true },
      { name: 'Виконані заходи', value: 4, confirmed: false },
    ],
  }
  const markup = html(createElement(ComponentDetail, {
    component,
    categories: [
      { category: 'cadets', responses: 30, hidden: false },
      { category: 'staff', responses: null, hidden: true },
      { category: 'mgmt', responses: null, hidden: true },
      { category: 'npp', responses: 6, hidden: false },
    ],
    indexComponent: { code: 'C2', name: 'Компонент C2', score: 80, weight: 0.15, contribution: 12, status: 'ok' },
    recommendations: [
      proposal('x1', 'CATEGORY_GAP_GE_25_V1', 'C2', 'Перевірити розрив C2.'),
      proposal('x2', 'LOW_SCORE_LT_50_V1', 'C4', 'Не для цього компонента.'),
    ],
    previous: { name: 'Осінь 2025', score: 81.2 },
    onClose: () => {},
  }))
  // V2 hardening: hidden groups are not listed at all — neither the name nor the score (cell flag and category flag both hide).
  const categoriesBlock = between(markup, 'id="component-detail-categories"', 'id="component-detail-indicators"')
  assert.doesNotMatch(categoriesBlock, /Персонал|Керівництво|Приховано/)
  assert.doesNotMatch(markup, /12[,.]3|9[,.]9/)
  assert.doesNotMatch(markup, /Критична/, 'a hidden low score must not leak through colour or label')
  assert.match(markup, /Курсанти<\/span><span class="component-detail-score">/)
  assert.match(markup, /78[,.]4 зі 100/)
  assert.match(markup, /Науково-педагогічні працівники<\/span><span>Немає даних<\/span>/)
  assert.match(markup, /Сильна сторона/)
  assert.match(markup, /5 з 5 · Зразковий/)
  assert.match(markup, /12 бала індексу/)
  assert.match(markup, /−1,2 п\.п\./)
  assert.match(markup, /87[,.]5%/)
  assert.match(markup, /Підтверджено/)
  assert.match(markup, /Не підтверджено/)
  assert.match(markup, /<code>CATEGORY_GAP_GE_25_V1<\/code><span>Перевірити розрив C2\.<\/span>/)
  assert.doesNotMatch(markup, /Не для цього компонента/)
  assert.match(markup, /Деталізація до окремих питань потребує розширення API/)
  assert.match(markup, /<h3 id="component-detail-heading" tabindex="-1">/)
  assert.match(markup, /aria-label="Закрити деталізацію C2"/)
  assert.match(markup, /Частину груп приховано для захисту анонімності \(менше k відповідей\)/)
})

test('ComponentDetail shows the suppression note from the new `suppressed` flag with the cycle threshold', () => {
  const markup = html(createElement(ComponentDetail, {
    component: {
      code: 'C1', name: 'Компонент C1', weight: 0.15, score: 70, suppressed: true,
      by_category: [{ category: 'cadets', score: 71.2 }], objective_indicators: [],
    },
    categories: [{ category: 'cadets', responses: 30 }],
    minGroupSize: 7,
    onClose: () => {},
  }))
  assert.match(markup, /Курсанти<\/span><span class="component-detail-score">/)
  assert.match(markup, /Частину груп приховано для захисту анонімності \(менше 7 відповідей\)/)
  const clean = html(createElement(ComponentDetail, {
    component: { code: 'C1', name: 'Компонент C1', weight: 0.15, score: 70, suppressed: false, by_category: [{ category: 'cadets', score: 71.2 }], objective_indicators: [] },
    categories: [{ category: 'cadets', responses: 30 }],
    onClose: () => {},
  }))
  assert.doesNotMatch(clean, /Частину груп приховано/)
})

test('ComponentDetail without analytics explains what is missing instead of inventing numbers', () => {
  const markup = html(createElement(ComponentDetail, {
    component: {
      code: 'C5', name: 'Компонент C5', weight: 0.1, score: null,
      by_category: [], objective_indicators: [],
    },
    analyticsNote: 'Внесок в індекс і рекомендації недоступні: аналітичний модуль вимкнено на сервері.',
    onClose: () => {},
  }))
  assert.match(markup, /Немає даних/)
  assert.match(markup, /Недоступно в цьому поданні/)
  assert.match(markup, /Рекомендації недоступні в цьому поданні\./)
  assert.match(markup, /аналітичний модуль вимкнено на сервері/)
  assert.doesNotMatch(markup, />0 зі 100</)
})

test('ComponentScores colours data by zone and shows the legend', () => {
  const data = results(2, { C6: null })
  const markup = html(createElement(ComponentScores, { components: data.components }))
  assert.match(markup, /C5, Компонент C5: 25 зі 100; Критична зона, рівень зрілості 2 з 5 «Базовий»/)
  assert.match(markup, /C6, Компонент C6: Немає даних; Немає даних/)
  assert.match(markup, /Зони \(демонстраційне правило команди, не офіційна шкала\)/)
})
