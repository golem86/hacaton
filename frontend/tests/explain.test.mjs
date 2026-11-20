import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true },
  cacheDir: 'node_modules/.vite-explain-test',
  appType: 'custom',
  logLevel: 'error',
})
after(() => server.close())

const api = await server.ssrLoadModule('/src/api/analytics.ts')
const explain = await server.ssrLoadModule('/src/dashboard/explain.ts')
const { ObjectiveComparison } = await server.ssrLoadModule('/src/dashboard/ObjectiveComparison.tsx')
const { ComparisonsContent, IndexContent, RecommendationsContent } =
  await server.ssrLoadModule('/src/dashboard/AnalyticsModules.tsx')

const html = element => renderToStaticMarkup(element)
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data })
const assessment = id => ({ id, name: `Cycle ${id}`, status: 'closed' })
const audit = { config_sha256: '0123456789abcdef'.repeat(4), input_sha256: 'f'.repeat(64) }
const count = (text, pattern) => (text.match(pattern) ?? []).length

// Shapes mirror backend/app/services/recommendations.py and analytics.py.
const gapBasis = (code, left, right, gap) => ({
  component_code: code, left_category: left, right_category: right, status: 'ok',
  gap_points: gap, gap_exact: String(gap), flag: true, threshold_points: 25,
  interpretation: 'Review signal, not proof of dishonesty',
})
const proposal = overrides => ({
  id: 'p', assessment_id: 1, rule_id: 'LOW_SCORE_LT_50_V1', component_code: 'C1',
  basis: { score: 42, threshold: 50 }, audit,
  text: 'Переглянути практики компонента та погодити план покращення.',
  status: 'proposed', owner_role: null, due_date: null, requires_human_decision: true,
  ...overrides,
})
const proposals = [
  proposal({ id: 'dq-c2', rule_id: 'DATA_QUALITY_V1', component_code: 'C2', basis: { status: 'suppressed' },
    text: 'Перевірити допустимість агрегованих даних; не розкривати приховані групи.' }),
  proposal({ id: 'gap-c3', rule_id: 'CATEGORY_GAP_GE_25_V1', component_code: 'C3',
    basis: gapBasis('C3', 'cadets', 'npp', -26), text: 'Перевірити трактування питання C3.' }),
  proposal({ id: 'low-c6', component_code: 'C6', basis: { score: 38.5, threshold: 50 }, text: 'Переглянути практики C6.' }),
  proposal({ id: 'gap-c6', rule_id: 'CATEGORY_GAP_GE_25_V1', component_code: 'C6',
    basis: gapBasis('C6', 'cadets', 'mgmt', -31), text: 'Перевірити трактування питання C6.' }),
  proposal({ id: 'low-c3', component_code: 'C3', basis: { score: 42, threshold: 50 }, text: 'Переглянути практики C3.' }),
  proposal({ id: 'custom', rule_id: 'CUSTOM_RULE_V9', component_code: 'C1',
    basis: { metric: 'synthetic', value: 3, flag: true, nested: { a: 1 }, none: null }, text: 'Інша пропозиція.' }),
]
const objective = (overrides = {}) => ({
  component_code: 'C1', name: 'Виконання заходів, закріплених за керівництвом, %',
  survey_score: 49.2, objective_value: 52, status: 'ok', comparison_type: 'context_only', gap_points: null,
  reason: 'Metric IDs, units and evidence links are not supplied by /results',
  ...overrides,
})
const objectiveContext = [
  objective(),
  objective({ component_code: 'C2', name: 'Актуальність антикорупційної програми, %',
    survey_score: null, objective_value: null, status: 'unverified' }),
  objective({ component_code: 'C5', name: 'Персонал, що пройшов навчання, %',
    survey_score: 80, objective_value: null, status: 'unverified' }),
  objective({ component_code: 'C7', name: 'Виконання плану заходів, %', survey_score: 78, objective_value: 63 }),
]
const recommendations = (overrides = {}) => ({
  assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY, approval_status: 'proposed',
  proposals, objective_context: objectiveContext, audit,
  persistence: 'none; human acceptance and Tracker storage are a separate command',
  ...overrides,
})
const withFetch = async (data, run) => {
  const oldFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => response(data)
    return await run()
  } finally { globalThis.fetch = oldFetch }
}

test('each rule has a Ukrainian explanation built only from its basis', () => {
  const low = explain.explainRecommendation(proposal({ component_code: 'C3' }))
  assert.equal(low.known, true)
  assert.equal(low.text, 'Бал компонента C3 — 42 зі 100, нижче порогу 50 (правило LOW_SCORE_LT_50_V1).')
  assert.match(explain.explainRecommendation(proposal({ basis: { score: 38.5, threshold: 50 } })).text, /38[,.]5 зі 100/)

  const gap = explain.explainRecommendation(proposals[3])
  assert.equal(gap.known, true)
  assert.match(gap.text, /^Розрив між категоріями «Керівництво» і «Курсанти» — 31 п\.п\., поріг сигналу 25 п\.п\./)
  assert.match(gap.text, /вищий бал у категорії «Керівництво»/)
  assert.match(gap.text, /правило CATEGORY_GAP_GE_25_V1/)
  assert.match(gap.text, /не доказ порушення/)
  const positive = explain.explainRecommendation(proposal({
    rule_id: 'CATEGORY_GAP_GE_25_V1', basis: gapBasis('C4', 'cadets', 'npp', 27.25),
  }))
  assert.match(positive.text, /«Курсанти» і «Науково-педагогічні працівники» — 27[,.]25 п\.п\./)
  assert.match(positive.text, /вищий бал у категорії «Курсанти»/)

  const hidden = explain.explainRecommendation(proposals[0])
  assert.equal(hidden.known, true)
  assert.match(hidden.text, /^Дані компонента C2 приховано або відсутні \(стан: приховано для захисту малих груп\) — перевірте допустимість агрегатів/)
  assert.match(explain.explainRecommendation(proposal({ rule_id: 'DATA_QUALITY_V1', basis: { status: 'missing' } })).text,
    /немає даних для розрахунку/)
})

test('unknown rules and bases that do not fit fall back to raw key/values', () => {
  const custom = explain.explainRecommendation(proposals[5])
  assert.equal(custom.known, false)
  assert.match(custom.text, /CUSTOM_RULE_V9 не має опису/)
  assert.deepEqual(custom.facts, [
    ['metric', 'synthetic'], ['value', '3'], ['flag', 'так'], ['nested', '{"a":1}'], ['none', 'немає'],
  ])
  // A score at the threshold must not be described as "below the threshold".
  const notLow = explain.explainRecommendation(proposal({ basis: { score: 50, threshold: 50 } }))
  assert.equal(notLow.known, false)
  assert.match(notLow.text, /не відповідає опису правила LOW_SCORE_LT_50_V1/)
  assert.deepEqual(notLow.facts, [['score', '50'], ['threshold', '50']])
  const smallGap = explain.explainRecommendation(proposal({
    rule_id: 'CATEGORY_GAP_GE_25_V1', basis: gapBasis('C1', 'cadets', 'npp', 24.9),
  }))
  assert.equal(smallGap.known, false)
  const noBasis = explain.explainRecommendation(proposal({ basis: undefined }))
  assert.equal(noBasis.known, false)
  assert.match(noBasis.text, /API не передав обґрунтування/)
  assert.deepEqual(noBasis.facts, [])
})

test('priority order is explicit: low score asc, then gap desc, then data quality, then other rules', () => {
  assert.deepEqual(explain.sortRecommendations(proposals).map(item => item.id),
    ['low-c6', 'low-c3', 'gap-c6', 'gap-c3', 'dq-c2', 'custom'])
  assert.deepEqual(proposals.map(item => item.id), ['dq-c2', 'gap-c3', 'low-c6', 'gap-c6', 'low-c3', 'custom'],
    'sorting must not mutate the API data')
  const groups = explain.groupRecommendations(proposals)
  assert.deepEqual(groups.map(group => [group.componentCode, group.items.map(({ item, rank }) => `${rank}:${item.id}`)]), [
    ['C6', ['1:low-c6', '3:gap-c6']],
    ['C3', ['2:low-c3', '4:gap-c3']],
    ['C2', ['5:dq-c2']],
    ['C1', ['6:custom']],
  ])
  // Missing numbers sort last within their rule; ties fall back to component code (C2 before C10).
  const ties = [
    proposal({ id: 'no-score', component_code: 'C1', basis: { status: 'weird' } }),
    proposal({ id: 'c10', component_code: 'C10', basis: { score: 10, threshold: 50 } }),
    proposal({ id: 'c2', component_code: 'C2', basis: { score: 10, threshold: 50 } }),
  ]
  assert.deepEqual(explain.sortRecommendations(ties).map(item => item.id), ['c2', 'c10', 'no-score'])
  assert.match(explain.PRIORITY_RULE, /низькі бали \(від найнижчого\).*розриви між категоріями \(від найбільшого\).*якість даних/)
  assert.deepEqual(explain.RULE_SET.map(rule => rule.id), ['LOW_SCORE_LT_50_V1', 'CATEGORY_GAP_GE_25_V1', 'DATA_QUALITY_V1'])
})

test('"Потребує перевірки" rule: unverified indicator, or self-assessment ≥ 75 without a confirmed value', () => {
  const review = item => explain.objectiveReview(objective(item))
  assert.deepEqual(review({}), { needsReview: false, reasons: [] })
  assert.deepEqual(review({ status: 'unverified', objective_value: null, survey_score: 60 }),
    { needsReview: true, reasons: ['показник не підтверджено'] })
  assert.equal(review({ status: 'unverified', objective_value: null, survey_score: 74.9 }).reasons.length, 1)
  assert.equal(review({ status: 'unverified', objective_value: null, survey_score: 75 }).reasons.length, 2)
  assert.equal(review({ status: 'unverified', objective_value: null, survey_score: null }).needsReview, true)
  // Confirmed value: a high self-assessment alone is not flagged; no cross-unit numeric comparison.
  assert.equal(review({ survey_score: 95, objective_value: 10 }).needsReview, false)
  // Missing value while marked ok: flagged only for a high self-assessment.
  assert.deepEqual(review({ objective_value: null, survey_score: 80 }).reasons,
    ['висока самооцінка (≥ 75 зі 100) без підтвердженого значення показника'])
  assert.equal(review({ objective_value: null, survey_score: 60 }).needsReview, false)
  assert.match(explain.REVIEW_RULE, /не підтверджено.*75 зі 100/)
})

test('recommendations validator accepts backend fields, unknown extras and older payloads', async () => {
  const full = recommendations({
    proposals: proposals.map(item => ({ ...item, basis: { ...item.basis, future_field: 'kept' } })),
    unknown_top_level: true,
  })
  const data = await withFetch(full, () => api.getRecommendations(1))
  assert.equal(data.proposals.length, 6)
  assert.equal(data.proposals[1].basis.left_category, 'cadets')
  assert.equal(data.proposals[0].owner_role, null)
  assert.equal(data.objective_context.length, 4)

  const legacy = {
    assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY, approval_status: 'proposed',
    persistence: 'none',
    proposals: [{ id: 'r1', rule_id: 'LOW_SCORE_LT_50_V1', component_code: 'C1', text: 'T', status: 'proposed', requires_human_decision: true }],
  }
  const old = await withFetch(legacy, () => api.getRecommendations(1))
  assert.equal(old.objective_context, undefined)
  assert.equal(old.proposals[0].basis, undefined)

  const assigned = recommendations({ proposals: [proposal({ owner_role: 'Уповноважений', due_date: '2026-12-01' })] })
  assert.equal((await withFetch(assigned, () => api.getRecommendations(1))).proposals[0].due_date, '2026-12-01')
  const anyObjectForUnknownRule = recommendations({ proposals: [proposal({ rule_id: 'X_V1', basis: {} })] })
  assert.equal((await withFetch(anyObjectForUnknownRule, () => api.getRecommendations(1))).proposals.length, 1)
})

test('recommendations validator rejects malformed fields the UI relies on', async () => {
  const bad = [
    recommendations({ proposals: [proposal({ basis: { score: '42', threshold: 50 } })] }),
    recommendations({ proposals: [proposal({ basis: [42, 50] })] }),
    recommendations({ proposals: [proposal({ rule_id: 'CATEGORY_GAP_GE_25_V1', basis: { gap_points: 30 } })] }),
    recommendations({ proposals: [proposal({ rule_id: 'DATA_QUALITY_V1', basis: {} })] }),
    recommendations({ proposals: [proposal({ basis: null })] }),
    recommendations({ proposals: [proposal({ owner_role: 7 })] }),
    recommendations({ proposals: [proposal({ due_date: 20261201 })] }),
    recommendations({ proposals: [proposal({ assessment_id: 2 })] }),
    recommendations({ objective_context: {} }),
    recommendations({ objective_context: [objective({ status: 'maybe' })] }),
    recommendations({ objective_context: [objective({ survey_score: '80' })] }),
    recommendations({ objective_context: [objective({ objective_value: Number.NaN })] }),
  ]
  for (const payload of bad) {
    await withFetch(payload, () => assert.rejects(api.getRecommendations(1), /некоректну відповідь/))
  }
})

test('comparison validator checks per-component period changes', async () => {
  const period = components => ({
    assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY, category_comparisons: [],
    period_comparison: {
      before_assessment: assessment(1), after_assessment: assessment(2), status: 'limited_comparability',
      change_points: 1.5, change_exact: '3/2', components, warnings: [], audit: {},
    },
  })
  const ok = await withFetch(period([
    { component_code: 'C1', change_points: 2.5, change_exact: '5/2' },
    { component_code: 'C2', change_points: null, change_exact: null },
  ]), () => api.getComparisons(1, 2))
  assert.equal(ok.period_comparison.components[1].change_points, null)
  for (const components of [undefined, [{ component_code: 'C1', change_points: '2.5' }], [{ change_points: 1 }]]) {
    await withFetch(period(components), () => assert.rejects(api.getComparisons(1, 2), /некоректну відповідь/))
  }
})

test('recommendations render the reason, priority, grouping, rule set and human-decision badge', () => {
  const markup = html(createElement(RecommendationsContent, {
    data: recommendations({
      proposals: [...proposals, proposal({ id: 'xss', rule_id: 'RAW_V1', component_code: 'C9',
        basis: { note: '<img src=x onerror=alert(1)>' }, respondent_email: 'private@example.invalid' })],
    }),
  }))
  assert.equal(count(markup, /Чому запропоновано/g), 7)
  assert.equal(count(markup, /Потребує рішення посадової особи/g), 7)
  for (const id of ['LOW_SCORE_LT_50_V1', 'CATEGORY_GAP_GE_25_V1', 'DATA_QUALITY_V1']) assert.match(markup, new RegExp(id))
  assert.match(markup, /нижче 50 зі 100/)
  assert.match(markup, /25 п\.п\. або більше/)
  assert.match(markup, /Порядок: спершу низькі бали/)
  assert.match(markup, /Бал компонента C6 — 38[,.]5 зі 100, нижче порогу 50/)
  assert.match(markup, /Розрив між категоріями «Керівництво» і «Курсанти» — 31 п\.п\., поріг сигналу 25 п\.п\./)
  assert.match(markup, /Дані компонента C2 приховано або відсутні/)
  // Groups follow priority: C6 (rank 1), C3 (rank 2), C2, C1, C9.
  const positions = ['компонента C6', 'компонента C3', 'компонента C2', 'компонента C1', 'компонента C9']
    .map(label => markup.indexOf(`aria-label="Пропозиції для ${label}"`))
  assert.ok(positions.every(position => position >= 0), 'every component has a group')
  assert.deepEqual([...positions].sort((a, b) => a - b), positions)
  assert.ok(markup.indexOf('Пріоритет 1') < markup.indexOf('Пріоритет 3'))
  assert.ok(markup.indexOf('Пріоритет 3') < markup.indexOf('Пріоритет 2'), 'rank 3 (C6 gap) stays inside the C6 group')
  // Raw basis for the unknown rule is visible and escaped; unrelated proposal fields are not shown.
  assert.match(markup, /<dt>metric<\/dt><dd>synthetic<\/dd>/)
  assert.match(markup, /&lt;img src=x onerror=alert\(1\)&gt;/)
  assert.doesNotMatch(markup, /<img|private@example/)
  assert.match(markup, /Відповідальна роль: не призначено · Строк: не встановлено/)
  assert.match(markup, /не зберігаються й не призначаються автоматично/)
  assert.match(markup, /<code title="0123456789abcdef[0-9a-f]{48}">0123456789abcdef…<\/code>/)
  assert.doesNotMatch(markup, /Recommendations|proposed\)/)

  const assigned = html(createElement(RecommendationsContent, {
    data: recommendations({ proposals: [proposal({ owner_role: 'Уповноважений', due_date: '2026-12-01' })] }),
  }))
  assert.match(assigned, /Відповідальна роль: Уповноважений · Строк: 2026-12-01/)
})

test('self-assessment vs objective panel renders hidden values, statuses and the review flag', () => {
  const markup = html(createElement(ObjectiveComparison, { items: objectiveContext }))
  assert.match(markup, /Порівняння контекстне \(тип: context_only\)/)
  assert.match(markup, /числовий розрив автоматично\s+не обчислюється/)
  assert.match(markup, /сигнал для перегляду посадовою особою, а не доказ порушень/)
  assert.match(markup, /Правило позначки/)
  assert.match(markup, /Приховано\/немає даних/)
  assert.match(markup, /49[,.]2 зі 100/)
  assert.match(markup, /52%/)
  assert.match(markup, /Немає підтвердженого значення/)
  assert.equal(count(markup, />Підтверджено</g), 2)
  assert.equal(count(markup, />Не підтверджено</g), 2)
  assert.equal(count(markup, /class="ax-flag">Потребує перевірки</g), 2)
  assert.match(markup, /Позначено «Потребує перевірки»: 2 з 4/)
  assert.match(markup, /показник не підтверджено; висока самооцінка/)
  assert.match(markup, /одиниці виміру й посилання на докази не передаються/)
  assert.doesNotMatch(markup, /п\.п\.|Metric IDs/, 'no numeric gap and no untranslated reason')

  assert.match(html(createElement(ObjectiveComparison, { items: [] })), /Об’єктивних показників для зіставлення немає/)
  assert.match(html(createElement(ObjectiveComparison, { items: undefined })), /API не передав об’єктивного контексту/)
})

test('comparison panel shows per-component period changes and keeps comparability warnings', () => {
  const markup = html(createElement(ComparisonsContent, {
    data: {
      assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY, category_comparisons: [],
      period_comparison: {
        before_assessment: assessment(1), after_assessment: assessment(2), status: 'limited_comparability',
        change_points: 2.5,
        components: [
          { component_code: 'C1', change_points: 2.5 },
          { component_code: 'C2', change_points: -3 },
          { component_code: 'C3', change_points: null },
          { component_code: 'C4', change_points: 0 },
        ],
        warnings: ['Numerical change does not establish causal improvement', 'Custom warning'],
      },
    },
  }))
  assert.match(markup, /\+2[,.]5 п\.п\. для індексу/)
  assert.match(markup, /C1<\/span><\/th><td class="ax-num">\+2[,.]5 п\.п\./)
  assert.match(markup, /C2<\/span><\/th><td class="ax-num">-3 п\.п\./)
  assert.match(markup, /C3<\/span><\/th><td class="ax-muted">недоступно/)
  assert.match(markup, /C4<\/span><\/th><td class="ax-num">0 п\.п\./)
  assert.match(markup, /Обмежена зіставність/)
  assert.match(markup, /Числова зміна не доводить причинно-наслідкового покращення/)
  assert.match(markup, /Custom warning/)
})

test('index panel shows weights, contributions, formula and visible limitations', () => {
  const markup = html(createElement(IndexContent, {
    index: {
      assessment: assessment(1), methodology_version: api.DEMO_METHODOLOGY, approval_status: 'proposed',
      synthetic_only: true, official: false, status: 'suppressed', index: null,
      warnings: ['Database does not yet freeze questionnaire versions per cycle'],
      components: [
        { code: 'C1', name: 'Лідерство', score: 48.4, weight: 0.15, contribution: 7.26, status: 'ok' },
        { code: 'C2', name: 'Політика', score: null, weight: 0.85, contribution: null, status: 'suppressed' },
      ],
    },
    methodology: {
      version: api.DEMO_METHODOLOGY, approval_status: 'proposed', synthetic_only: true, official: false,
      formula: 'sum(component_score * component_weight)', weights: { C1: '0.15', C2: '0.85' },
      limitations: ['Database does not yet freeze questionnaire versions per cycle'],
      missing: 'no_index_no_reweighting', config_sha256: audit.config_sha256,
    },
  }))
  assert.match(markup, /Індекс недоступний: дані приховано/)
  assert.match(markup, /Σ \(бал компонента × вага компонента\)/)
  assert.match(markup, /<code>sum\(component_score \* component_weight\)<\/code>/)
  assert.match(markup, /ваги інших компонентів не перерозподіляються/)
  assert.match(markup, /0[,.]15/)
  assert.match(markup, /7[,.]26 <small class="ax-muted">= 48[,.]4 × 0[,.]15<\/small>/)
  assert.match(markup, /Приховано для захисту групи/)
  assert.match(markup, /не враховано/)
  assert.match(markup, /Сума ваг" class="ax-num">1[,.]00/)
  assert.match(markup, /не розраховано/)
  assert.equal(count(markup, /База даних поки не фіксує версію анкети/g), 1, 'limitations are shown once and translated')
  assert.doesNotMatch(markup, /<details/, 'limitations are visible, not collapsed')
})
