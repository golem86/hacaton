import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true },
  cacheDir: 'node_modules/.vite-analytics-test',
  appType: 'custom',
  logLevel: 'error',
})
after(() => server.close())

const api = await server.ssrLoadModule('/src/api/analytics.ts')
const {
  AnalyticsModules, ComparisonsContent, DemoNotice, IndexContent, ModuleState,
  RecommendationsContent, canShowAnalytics, loadAnalytics, visibleRemoteState,
} =
  await server.ssrLoadModule('/src/dashboard/AnalyticsModules.tsx')
const tick = () => new Promise(resolve => setImmediate(resolve))
const response = (data, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => data,
})
const assessment = id => ({
  id, name: `Cycle ${id}`, status: 'closed', start_date: '2026-11-01', min_group_size: 5,
})
const html = element => renderToStaticMarkup(element)
const indexData = (overrides = {}) => ({
  assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
  approval_status: 'proposed', synthetic_only: true, official: false,
  status: 'ok', index: 48.4, warnings: [],
  components: [{
    code: 'C1', name: 'Synthetic component', score: 48.4,
    weight: 0.15, contribution: 7.26, status: 'ok',
  }],
  ...overrides,
})
const methodologyData = {
  version: api.DEMO_METHODOLOGY, approval_status: 'proposed',
  synthetic_only: true, official: false, formula: 'sum(component_score * component_weight)',
  weights: { C1: '0.15' }, limitations: ['Synthetic components only'],
}

test('analytics clients use exact routes, methodology and manager demo role', async () => {
  const oldFetch = globalThis.fetch
  const seen = []
  try {
    globalThis.fetch = async (url, options) => {
      seen.push({ url, role: options.headers['X-Role'] })
      if (url.includes('index-methodologies')) return response({
        version: api.DEMO_METHODOLOGY, approval_status: 'proposed',
        synthetic_only: true, official: false, formula: 'sum(component_score * component_weight)',
        weights: { C1: '0.15' }, limitations: [],
      })
      if (url.includes('/index?')) return response({
        assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
        approval_status: 'proposed', synthetic_only: true, official: false,
        status: 'insufficient_data', index: null, components: [], warnings: [],
      })
      if (url.includes('/recommendations?')) return response({
        assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
        approval_status: 'proposed', proposals: [], persistence: 'none',
      })
      return response({
        assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
        category_comparisons: [], period_comparison: null,
      })
    }
    assert.equal((await api.getMethodology()).synthetic_only, true)
    assert.equal((await api.getIntegrityIndex(1)).index, null)
    assert.deepEqual((await api.getRecommendations(1)).proposals, [])
    assert.deepEqual((await api.getComparisons(1)).category_comparisons, [])
    assert.deepEqual(seen, [
      { url: '/api/index-methodologies/team-results-demo-0.1', role: 'manager' },
      { url: '/api/assessments/1/index?methodology=team-results-demo-0.1', role: 'manager' },
      { url: '/api/assessments/1/recommendations?methodology=team-results-demo-0.1', role: 'manager' },
      { url: '/api/analytics/comparisons?assessment_id=1&methodology=team-results-demo-0.1', role: 'manager' },
    ])
  } finally { globalThis.fetch = oldFetch }
})

test('comparison requests select a second cycle explicitly and reject missing period data', async () => {
  const oldFetch = globalThis.fetch
  try {
    globalThis.fetch = async url => {
      assert.equal(url, '/api/analytics/comparisons?assessment_id=1&methodology=team-results-demo-0.1&comparison_assessment_id=2')
      return response({
        assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
        category_comparisons: [], period_comparison: null,
      })
    }
    await assert.rejects(api.getComparisons(1, 2), /некоректну відповідь/)
  } finally { globalThis.fetch = oldFetch }
})

test('comparison accepts a real period response and retains comparability warnings', async () => {
  const oldFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => response({
      assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
      category_comparisons: [],
      period_comparison: {
        before_assessment: assessment(1), after_assessment: assessment(2),
        status: 'limited_comparability', change_points: 2.5,
        components: [], warnings: ['Population and questionnaire versions are not frozen'],
      },
    })
    const data = await api.getComparisons(1, 2)
    assert.equal(data.period_comparison.change_points, 2.5)
    assert.equal(data.period_comparison.warnings.length, 1)
  } finally { globalThis.fetch = oldFetch }
})

test('API errors, disabled demo and malformed data are handled', async () => {
  const oldFetch = globalThis.fetch
  try {
    for (const status of [401, 403, 404, 409, 422, 503]) {
      globalThis.fetch = async () => response({}, status)
      await assert.rejects(api.getIntegrityIndex(1), error => {
        const markup = html(createElement(ModuleState, {
          state: { status: 'error', message: error.message },
          retry: () => {},
          children: () => assert.fail('error must not render success'),
        }))
        assert.match(markup, /role="alert"/)
        assert.match(markup, /Спробувати ще раз/)
        return error.status === status && error.message.length > 0
      })
    }
    globalThis.fetch = async () => response({
      assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
      approval_status: 'proposed', synthetic_only: true, official: false,
      status: 'ok', index: 55, components: 'invalid', warnings: [],
    })
    await assert.rejects(api.getIntegrityIndex(1), /некоректну відповідь/)
    globalThis.fetch = async () => { throw new TypeError('network down') }
    await assert.rejects(api.getIntegrityIndex(1), error => {
      const markup = html(createElement(ModuleState, {
        state: { status: 'error', message: error.message },
        retry: () => {},
        children: () => assert.fail('network error must not render success'),
      }))
      assert.match(markup, /з’єднатися/)
      return error.status === 0
    })
  } finally { globalThis.fetch = oldFetch }
})

test('React Analytics states render loading, error, empty and success', () => {
  const renderState = (state, content) => html(createElement(ModuleState, {
    state, retry: () => {}, children: content,
  }))
  assert.match(renderState({ status: 'loading' }, () => null), /Завантажуємо аналітику/)
  assert.match(renderState({ status: 'error', message: 'Демоаналітика вимкнена' }, () => null),
    /Демоаналітика вимкнена/)

  const noIndex = html(createElement(IndexContent, {
    index: indexData({ status: 'insufficient_data', index: null, components: [] }),
    methodology: methodologyData,
  }))
  assert.match(noIndex, /Індекс недоступний/)
  assert.match(noIndex, /Складових поки немає/)
  const noRecommendations = html(createElement(RecommendationsContent, {
    data: {
      assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
      approval_status: 'proposed', proposals: [], persistence: 'none',
    },
  }))
  assert.match(noRecommendations, /Рекомендацій за поточними правилами немає/)
  const noComparisons = html(createElement(ComparisonsContent, {
    data: {
      assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
      category_comparisons: [], period_comparison: null,
    },
  }))
  assert.match(noComparisons, /Порівнянь категорій поки немає/)

  const success = renderState(
    { status: 'success', data: indexData() },
    data => createElement(IndexContent, { index: data, methodology: methodologyData }),
  )
  assert.match(success, /48[,.]4 зі 100/)
  assert.match(success, /запропонована/)
  assert.match(success, /Лише для синтетичних даних/)
  assert.match(success, /Synthetic component/)
})

test('React comparison content respects suppression and limited comparability', () => {
  const markup = html(createElement(ComparisonsContent, {
    data: {
      assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
      category_comparisons: [
        { component_code: 'C1', left_category: 'cadets', right_category: 'staff',
          status: 'unavailable', gap_points: 91.7, flag: true, interpretation: 'unavailable' },
        { component_code: 'C2', left_category: 'cadets', right_category: 'mgmt',
          status: 'ok', gap_points: 25.2, flag: true, interpretation: 'Review signal' },
      ],
      period_comparison: {
        before_assessment: assessment(1), after_assessment: assessment(2),
        status: 'limited_comparability', change_points: 2.5, components: [],
        warnings: ['Population and questionnaire versions are not frozen'],
      },
      respondent_email: 'private@example.invalid',
      answers: 'SECRET_REPLY',
    },
  }))
  assert.match(markup, /Обмежена зіставність/)
  assert.match(markup, /Population and questionnaire versions are not frozen/)
  assert.match(markup, /25[,.]2 п\.п\./)
  assert.match(markup, /недоступно через приховування/)
  assert.doesNotMatch(markup, /91[,.]7|private@example|SECRET_REPLY/)
})

test('React recommendations render proposals without unrelated respondent fields', () => {
  const markup = html(createElement(RecommendationsContent, {
    data: {
      assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
      approval_status: 'proposed', persistence: 'none',
      proposals: [{
        id: 'r1', rule_id: 'LOW_SCORE_LT_50_V1', component_code: 'C1',
        text: 'Переглянути практики компонента', status: 'proposed',
        requires_human_decision: true, answer_text: 'SECRET_REPLY',
      }],
    },
  }))
  assert.match(markup, /Переглянути практики компонента/)
  assert.match(markup, /синтетичною демометодикою/)
  assert.doesNotMatch(markup, /SECRET_REPLY/)
})

test('changed comparison selection hides old success on the same render, including A-B-A', () => {
  const oldData = {
    assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY,
    category_comparisons: [], period_comparison: {
      before_assessment: assessment(1), after_assessment: assessment(2),
      status: 'limited_comparability', change_points: 99.9,
      components: [], warnings: ['OLD_RESULT'],
    },
  }
  const stored = { key: 'comparisons:1:1:0', state: { status: 'success', data: oldData } }
  const renderFor = key => html(createElement(ModuleState, {
    state: visibleRemoteState(stored, key), retry: () => {},
    children: data => createElement(ComparisonsContent, { data }),
  }))
  assert.match(renderFor('comparisons:1:1:0'), /OLD_RESULT/)
  assert.doesNotMatch(renderFor('comparisons:1:2:0'), /OLD_RESULT|99[,.]9/)
  assert.doesNotMatch(renderFor('comparisons:1:3:0'), /OLD_RESULT|99[,.]9/)
  assert.doesNotMatch(renderFor('comparisons:2:1:0'), /OLD_RESULT|99[,.]9/)
  assert.match(renderFor('comparisons:1:3:0'), /Завантажуємо аналітику/)
})

test('open, stale, loading and failed cycle details never expose analytics', () => {
  const closed = assessment(1)
  assert.equal(canShowAnalytics(closed, 1, false, ''), true)
  assert.equal(canShowAnalytics({ ...closed, status: 'open' }, 1, false, ''), false)
  assert.equal(canShowAnalytics(closed, 2, false, ''), false)
  assert.equal(canShowAnalytics(closed, 1, true, ''), false)
  assert.equal(canShowAnalytics(closed, 1, false, 'failed'), false)
  const html = renderToStaticMarkup(createElement(AnalyticsModules, {
    id: 1, assessments: [closed, { ...assessment(2), status: 'open' }],
  }))
  assert.match(html, /Integrity Index/)
  assert.match(html, /Recommendations/)
  assert.match(html, /Comparative Analytics/)
  assert.doesNotMatch(html, /Cycle 2/)
  const notice = renderToStaticMarkup(createElement(DemoNotice, {
    approvalStatus: 'proposed', syntheticOnly: true, official: false,
  }))
  assert.match(notice, /запропонована/)
  assert.match(notice, /синтетичних даних/)
  assert.match(notice, /Неофіційна/)
})

test('cycle switch aborts requests and ignores late data and errors', async () => {
  const pending = new Map()
  const states = []
  const old = loadAnalytics(signal => new Promise((resolve, reject) =>
    pending.set(1, { resolve, reject, signal })), state => states.push(['old', state.status]))
  old()
  assert.equal(pending.get(1).signal.aborted, true)
  loadAnalytics(signal => new Promise((resolve, reject) =>
    pending.set(2, { resolve, reject, signal })), state => states.push(['new', state.status]))
  pending.get(2).resolve({ assessment: assessment(2) })
  await tick()
  pending.get(1).resolve({ assessment: assessment(1) })
  await tick()
  assert.deepEqual(states, [
    ['old', 'loading'], ['new', 'loading'], ['new', 'success'],
  ])
})

test('loader surfaces error and empty success as separate states', async () => {
  const states = []
  loadAnalytics(async () => { throw new Error('API unavailable') }, state => states.push(state))
  await tick()
  assert.equal(states.at(-1).status, 'error')
  assert.match(states.at(-1).message, /API unavailable/)
  loadAnalytics(async () => ({ proposals: [] }), state => states.push(state))
  await tick()
  assert.deepEqual(states.at(-1), { status: 'success', data: { proposals: [] } })
})
