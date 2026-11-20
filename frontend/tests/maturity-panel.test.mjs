import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true },
  cacheDir: 'node_modules/.vite-maturity-test',
  appType: 'custom',
  logLevel: 'error',
})
after(() => server.close())

const api = await server.ssrLoadModule('/src/api/maturity.ts')
const panel = await server.ssrLoadModule('/src/dashboard/MaturityPanel.tsx')
const { MaturityContent, MaturityStatus, gapSentence, levelBand, localBlock } = panel
const MaturityPanel = panel.default

const html = element => renderToStaticMarkup(element)
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data })
const text = markup => markup.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

const criterion = (key, name, overrides = {}) => ({
  key, name_uk: name, component_code: 'C1',
  self: { level: 3.0, responses: 40, status: 'ok' },
  self_by_category: [{ category: 'staff', level: 3.0, hidden: false }],
  expert: { level: 3.0, experts: 1, status: 'ok' },
  checklist: { level: 3.0, items_total: 4, items_confirmed: 4, status: 'ok' },
  objective: [],
  gaps: [
    { rule_id: 'MAT_SELF_EXPERT_GAP_GE_1', left: 'self', right: 'expert', diff: 0, flag: false },
    { rule_id: 'MAT_SELF_CHECKLIST_GAP_GE_1', left: 'self', right: 'checklist', diff: 0, flag: false },
  ],
  ...overrides,
})

const report = (overrides = {}) => ({
  assessment: { id: 7, name: 'Синтетичний цикл', status: 'closed' },
  methodology_version: api.MATURITY_METHODOLOGY,
  level_rule: 'a=1…e=5; f excluded',
  min_group_size: 5,
  criteria: [
    criterion('leadership', 'Лідерство', {
      self: { level: 4.2, responses: 38, status: 'ok' },
      self_by_category: [
        { category: 'staff', level: 4.4, hidden: false },
        { category: 'cadets', level: null, hidden: true },
      ],
      expert: { level: 2.8, experts: 2, status: 'ok' },
      checklist: { level: 2.0, items_total: 5, items_confirmed: 3, status: 'ok' },
      objective: [{ name: 'Частка пройденого навчання', value: 61, target: 80, confirmed: true }],
      gaps: [
        { rule_id: 'MAT_SELF_EXPERT_GAP_GE_1', left: 'self', right: 'expert', diff: 1.4, flag: true },
        { rule_id: 'MAT_SELF_CHECKLIST_GAP_GE_1', left: 'self', right: 'checklist', diff: 2.2, flag: true },
      ],
    }),
    criterion('ethics', 'Етичні стандарти', {
      component_code: null,
      self: { level: null, responses: null, status: 'suppressed' },
      expert: { level: null, experts: 0, status: 'missing' },
      gaps: [{ rule_id: 'MAT_SELF_EXPERT_GAP_GE_1', left: 'self', right: 'expert', diff: null, flag: false }],
    }),
  ],
  overall_self_declared: { level: 3.6, status: 'ok' },
  indices: { self: 62.5, expert: 45, checklist: null },
  recommendations: [{
    id: 'r1', rule_id: 'MAT_SELF_EXPERT_GAP_GE_1', criterion: 'leadership',
    basis: { self: 4.2, expert: 2.8, diff: 1.4, threshold: 1 },
    text: 'Обговорити розбіжність із робочою групою.', requires_human_decision: true,
  }],
  ...overrides,
})

test('validator accepts a contract payload and the client uses the exact route with session cookies', async () => {
  assert.equal(api.isMaturityReport(report(), 7), true)
  const oldFetch = globalThis.fetch
  const seen = []
  try {
    globalThis.fetch = async (url, options) => {
      seen.push({ url, credentials: options.credentials })
      return response(report())
    }
    const data = await api.getMaturity(7)
    assert.equal(data.indices.self, 62.5)
    assert.deepEqual(seen, [{ url: '/api/assessments/7/maturity', credentials: 'include' }])
  } finally { globalThis.fetch = oldFetch }
})

test('validator rejects wrong methodology, ids, out-of-range values and leaked suppressed levels', () => {
  const bad = [
    report({ methodology_version: 'team-results-demo-0.1' }),
    report({ indices: { self: 120, expert: null, checklist: null } }),
    report({ indices: { self: '50', expert: null, checklist: null } }),
    report({ overall_self_declared: { level: 3, status: 'suppressed' } }),
    report({ criteria: [criterion('x', 'X', { self: { level: 0, responses: 3, status: 'ok' } })] }),
    report({ criteria: [criterion('x', 'X', { self: { level: 3.3, responses: 3, status: 'suppressed' } })] }),
    report({ criteria: [criterion('x', 'X', { self_by_category: [{ category: 'staff', level: 2, hidden: true }] })] }),
    report({ criteria: [criterion('x', 'X', { checklist: { level: 3, items_total: 2, items_confirmed: 3, status: 'ok' } })] }),
    report({ criteria: [criterion('x', 'X', { gaps: [{ rule_id: 'R', left: 'self', right: 'peer', diff: 1, flag: true }] })] }),
    report({ recommendations: [{ id: 'r', rule_id: 'R', criterion: 'x', basis: {}, text: 't', requires_human_decision: false }] }),
    report({ criteria: 'none' }),
    null,
  ]
  for (const payload of bad) assert.equal(api.isMaturityReport(payload, 7), false, JSON.stringify(payload)?.slice(0, 120))
  assert.equal(api.isMaturityReport(report(), 8), false, 'assessment id must match the request')
})

test('client turns a malformed body into an error and maps 401/403/404/409/503 messages', async () => {
  const oldFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => response(report({ indices: {} }))
    await assert.rejects(api.getMaturity(7), /некоректну відповідь/)
    for (const status of [401, 403, 404, 409, 503]) {
      globalThis.fetch = async () => response({}, status)
      await assert.rejects(api.getMaturity(7), error => error.status === status && error.message === api.MATURITY_MESSAGES[status])
    }
  } finally { globalThis.fetch = oldFetch }
})

test('header renders the three indices, overall level, methodology, rule, formula and demo notice', () => {
  const markup = html(createElement(MaturityContent, { report: report() }))
  const plain = text(markup)
  assert.match(plain, /Індекс самооцінювання 62,5 \/ 100/)
  assert.match(plain, /Експертний індекс 45,0 \/ 100/)
  assert.match(plain, /Індекс чеклиста Додатка Б Немає даних/)
  assert.match(plain, /Не обчислено: хоча б один критерій прихований/)
  assert.match(plain, /Загальний рівень \(самооцінка\) 3,6 \/ 5/)
  assert.match(plain, /annex-v-maturity-0\.1/)
  assert.match(plain, /варіант a = рівень 1.*e = рівень 5/)
  assert.match(plain, /рівні ваги \(1\/10\) для 10 критеріїв/)
  assert.match(plain, /синтетичних даних/)
  assert.match(plain, /пропозиція команди/)
  assert.match(markup, /k = <!-- -->5|k = 5/)
})

test('table shows null and hidden cells as text, never as 0, with caption, legend and scroll region', () => {
  const markup = html(createElement(MaturityContent, { report: report() }))
  assert.match(markup, /<caption>/)
  assert.match(markup, /role="region"[^>]*aria-label="Таблиця критеріїв/)
  assert.match(markup, /aria-label="Легенда кольорів рівнів"/)
  assert.match(text(markup), /Низький 1–2.*Середній 3.*Високий 4–5/)
  assert.match(markup, /mp-level-high[^>]*><strong>4,2<\/strong>/)
  assert.match(markup, /mp-level-low[^>]*><strong>2,0<\/strong>/)
  assert.match(markup, /mp-level-medium[^>]*><strong>2,8<\/strong>/)
  assert.match(markup, /mp-level-none mp-level-hidden[^>]*>Приховано</)
  assert.match(markup, /mp-level-none"[^>]*>Немає даних</)
  assert.match(text(markup), /3\/5 підтв\./)
  assert.match(text(markup), /Частка пройденого навчання 61 \/ ціль 80 Підтверджено/)
  // expandable category detail: hidden category shows «Приховано»
  assert.match(markup, /aria-expanded="false"/)
  assert.match(text(markup), /Курсанти Приховано/)
  assert.match(text(markup), /Працівники 4,4/)
  // canvas text alternative
  assert.match(markup, /<canvas[^>]*role="img"[^>]*aria-label="Згрупована діаграма/)
  assert.match(text(markup), /Етичні стандарти: самооцінювання Приховано, експерт Немає даних/)
  assert.doesNotMatch(text(markup), /Етичні стандарти: самооцінювання 0/)
})

test('flagged gaps are listed with values, threshold and rule id; recommendations require a decision', () => {
  const data = report()
  assert.equal(gapSentence(data.criteria[0], data.criteria[0].gaps[0]),
    'Самооцінка 4,2 vs експерт 2,8: розрив 1,4 ≥ 1,0, правило MAT_SELF_EXPERT_GAP_GE_1')
  const plain = text(html(createElement(MaturityContent, { report: data })))
  assert.match(plain, /Розбіжності джерел/)
  assert.match(plain, /сигнал для перевірки, а не доказ/)
  assert.match(plain, /Самооцінка 4,2 vs експерт 2,8: розрив 1,4 ≥ 1,0, правило MAT_SELF_EXPERT_GAP_GE_1/)
  assert.match(plain, /Самооцінка 4,2 vs чеклист 2,0: розрив 2,2 ≥ 1,0, правило MAT_SELF_CHECKLIST_GAP_GE_1/)
  assert.doesNotMatch(plain, /Етичні стандарти\. Самооцінка/, 'unflagged gaps are not listed')
  assert.match(plain, /Рекомендації за Додатком В/)
  assert.match(plain, /Потребує рішення посадової особи MAT_SELF_EXPERT_GAP_GE_1/)
  assert.match(plain, /Лідерство: Обговорити розбіжність/)
  assert.match(plain, /розрив 1,4/)
})

test('level bands follow the documented rule', () => {
  assert.deepEqual([1, 2, 2.4, 2.5, 3, 3.4, 3.5, 4, 5, null].map(levelBand),
    ['low', 'low', 'low', 'medium', 'medium', 'medium', 'high', 'high', 'high', 'none'])
})

test('states: loading, 409, 503 without retry, network error with retry, empty data', () => {
  assert.match(html(createElement(MaturityStatus, { state: { status: 'loading' }, retry: () => {} })), /role="status".*Завантажуємо/)
  for (const code of [409, 503]) {
    const markup = html(createElement(MaturityStatus, { state: { status: 'error', code, message: api.MATURITY_MESSAGES[code] }, retry: () => {} }))
    assert.match(markup, /role="alert"/)
    assert.ok(markup.includes(api.MATURITY_MESSAGES[code]))
    assert.doesNotMatch(markup, /Спробувати ще раз/)
  }
  assert.match(html(createElement(MaturityStatus, { state: { status: 'error', code: 0, message: 'x' }, retry: () => {} })), /Спробувати ще раз/)
  const empty = text(html(createElement(MaturityContent, { report: report({ criteria: [], recommendations: [] }) })))
  assert.match(empty, /ще немає даних за Додатком В/)
  assert.match(empty, /Немає даних/)
  const suppressedOverall = text(html(createElement(MaturityContent, { report: report({ overall_self_declared: { level: null, status: 'suppressed' } }) })))
  assert.match(suppressedOverall, /Загальний рівень \(самооцінка\) Приховано/)
})

test('panel blocks open cycles locally and renders a cycle select', () => {
  const cycles = [
    { id: 7, name: 'Закритий', status: 'closed', start_date: '2026-11-01', min_group_size: 5 },
    { id: 8, name: 'Відкритий', status: 'open', start_date: '2026-11-10', min_group_size: 5 },
  ]
  assert.equal(localBlock(cycles[0]), null)
  assert.equal(localBlock(cycles[1]), api.MATURITY_MESSAGES[409])
  const open = html(createElement(MaturityPanel, { assessments: cycles, selectedId: 8 }))
  assert.match(open, /<label[^>]*>Цикл оцінювання<\/label>/)
  assert.match(open, /Відкритий \(не закрито\)/)
  assert.ok(open.includes(api.MATURITY_MESSAGES[409]))
  const closed = html(createElement(MaturityPanel, { assessments: cycles, selectedId: 7 }))
  assert.match(closed, /Завантажуємо аналітику зрілості/)
  assert.match(html(createElement(MaturityPanel, { assessments: [], selectedId: null })), /Немає циклів оцінювання/)
})
