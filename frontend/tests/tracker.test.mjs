import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true },
  cacheDir: 'node_modules/.vite-tracker-test',
  appType: 'custom',
  logLevel: 'error',
})
after(() => server.close())

const api = await server.ssrLoadModule('/src/api/tracker.ts')
const client = await server.ssrLoadModule('/src/api/client.ts')
const panel = await server.ssrLoadModule('/src/v2/TrackerPanel.tsx')
const html = element => renderToStaticMarkup(element)
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
const noop = async () => {}

const TODAY = '2026-11-20'
const action = (overrides = {}) => ({
  id: 7, assessment_id: 1, recommendation_id: 'abc123', rule_id: 'LOW_SCORE_LT_50_V1', component_code: 'C4',
  text: 'Переглянути практики компонента', methodology_version: 'team-results-demo-0.1', status: 'accepted',
  owner: 'Навчальний відділ', due_date: '2026-12-01', decision_reason: 'Погоджено', evidence_refs: [],
  verified_in_assessment_id: null, overdue: false, allowed_transitions: ['in_progress'],
  history: [{
    from_status: 'proposed', to_status: 'accepted', on_date: TODAY, at: '2026-11-20T10:00:00Z',
    actor_role: 'admin', reason: 'Погоджено', evidence_refs: [], owner: 'Навчальний відділ', due_date: '2026-12-01',
  }],
  created_at: '2026-11-20T10:00:00Z', updated_at: '2026-11-20T10:00:00Z',
  ...overrides,
})
const trackerData = (actions = [action()]) => ({
  assessment: { id: 1, name: '2025-II', status: 'closed' }, as_of: TODAY, actions,
  summary: { accepted_total: 1, accepted: 1, in_progress: 0, completed: 0, verified: 0, rejected: 0, overdue: 0 },
})
const cycle = (id, start_date, extra = {}) => ({
  id, name: `Cycle ${id}`, start_date, status: 'closed', min_group_size: 5, questionnaire_version: 'demo-v1', ...extra,
})
const proposal = (id, extra = {}) => ({
  id, rule_id: 'LOW_SCORE_LT_50_V1', component_code: 'C3', text: `Пропозиція ${id}`,
  status: 'proposed', requires_human_decision: true, ...extra,
})
const recommendations = proposals => ({
  status: 'ready',
  data: { assessment: { id: 1, name: '2025-II', status: 'closed' }, methodology_version: 'team-results-demo-0.1',
          approval_status: 'proposed', proposals, persistence: 'none' },
})

async function withFetch(handler, run) {
  const previous = globalThis.fetch
  globalThis.fetch = handler
  try { await run() } finally { globalThis.fetch = previous }
}

test('tracker API uses exact paths, methods, session CSRF and never sends recommendation text', async () => {
  const calls = []
  client.setCsrfToken('test-csrf')
  await withFetch(async (url, options) => {
    const headers = new Headers(options.headers)
    calls.push({ url, method: options.method ?? 'GET', credentials: options.credentials,
                 csrf: headers.get('X-CSRF-Token'), role: headers.has('X-Role'),
                 type: headers.get('Content-Type'), body: options.body === undefined ? undefined : JSON.parse(options.body) })
    return url.endsWith('/tracker') ? json(trackerData()) : json(action(), url.includes('/decisions') ? 201 : 200)
  }, async () => {
    assert.equal((await api.getTracker(1)).actions[0].owner, 'Навчальний відділ')
    await api.decideRecommendation(1, { recommendation_id: 'abc123', decision: 'accepted', owner: ' Навчальний відділ ',
                                        due_date: '2026-12-01', reason: ' Погоджено ' })
    await api.decideRecommendation(1, { recommendation_id: 'abc123', decision: 'rejected', reason: 'Не стосується',
                                        text: 'SPOOFED', owner: 'Хтось', due_date: '2026-12-01' })
    await api.transitionAction(7, { status: 'in_progress', reason: 'Почато', evidence_refs: [], verified_in_assessment_id: 2 })
    await api.transitionAction(7, { status: 'verified', reason: 'Перевірено', evidence_refs: ['Звіт циклу'], verified_in_assessment_id: 2 })
  })
  assert.deepEqual(calls.map(call => [call.method, call.url]), [
    ['GET', '/api/assessments/1/tracker'],
    ['POST', '/api/assessments/1/tracker/decisions'],
    ['POST', '/api/assessments/1/tracker/decisions'],
    ['POST', '/api/tracker/7/transition'],
    ['POST', '/api/tracker/7/transition'],
  ])
  assert.deepEqual(calls.map(call => call.body), [
    undefined,
    { recommendation_id: 'abc123', decision: 'accepted', owner: 'Навчальний відділ', due_date: '2026-12-01', reason: 'Погоджено' },
    { recommendation_id: 'abc123', decision: 'rejected', reason: 'Не стосується' },
    { status: 'in_progress', reason: 'Почато' },
    { status: 'verified', reason: 'Перевірено', evidence_refs: ['Звіт циклу'], verified_in_assessment_id: 2 },
  ])
  assert.ok(calls.every(call => call.credentials === 'include' && !call.role))
  assert.equal(calls[0].csrf, null)
  assert.ok(calls.slice(1).every(call => call.csrf === 'test-csrf' && call.type === 'application/json'))
})

test('tracker API turns HTTP failures into clear Ukrainian messages', async () => {
  client.setCsrfToken('test-csrf')
  const decide = () => api.decideRecommendation(1, { recommendation_id: 'abc123', decision: 'rejected', reason: 'Ні' })
  const cases = [
    [json({ detail: 'Set INTEGRITY_ANALYTICS_DEMO=1 only for a synthetic database' }, 503), 503, /не ввімкнений/],
    [json({ detail: 'Строк не може бути раніше за сьогодні' }, 422), 422, /^Строк не може бути раніше за сьогодні$/],
    [json({ detail: [{ loc: ['body', 'reason'], msg: 'too short' }] }, 422), 422, /Перевірте поля форми/],
    [json({ detail: 'Рішення щодо цієї пропозиції вже ухвалено' }, 409), 409, /вже ухвалено/],
    [json({ detail: 'Потрібен вхід до системи' }, 401), 401, /Увійдіть знову/],
    [json({ detail: 'Некоректний CSRF-токен' }, 403), 403, /CSRF/],
    [new Response('not json', { status: 500 }), 500, /Помилка API \(500\)/],
  ]
  for (const [response, status, message] of cases) {
    await withFetch(async () => response, async () => {
      await assert.rejects(decide(), error => error.status === status && message.test(error.message))
    })
  }
  for (const [status, message] of [[401, /Увійдіть знову/], [403, /недоступний/], [404, /не знайдено/]]) {
    await withFetch(async () => json({}, status), async () => {
      await assert.rejects(api.getTracker(1), error => error.status === status && message.test(error.message))
    })
  }
  await withFetch(async () => json({ ...trackerData(), actions: 'broken' }), async () => {
    await assert.rejects(api.getTracker(1), /некоректну відповідь/)
  })
  await withFetch(async () => json(trackerData()), async () => {
    await assert.rejects(api.getTracker(2), /некоректну відповідь/)           // відповідь іншого циклу
  })
  let fetched = false
  client.setCsrfToken('')
  await withFetch(async () => { fetched = true; return json(action()) }, async () => {
    await assert.rejects(decide(), error => error.status === 403)
  })
  assert.equal(fetched, false)
  client.setCsrfToken('test-csrf')
})

test('overdue rule: deadline passed and status is neither completed nor verified', () => {
  const overdue = (status, due_date) => api.isOverdue({ status, due_date }, TODAY)
  assert.equal(overdue('accepted', '2026-11-19'), true)
  assert.equal(overdue('in_progress', '2026-01-01'), true)
  assert.equal(overdue('accepted', TODAY), false)                     // день строку — ще не прострочення
  assert.equal(overdue('accepted', '2026-12-31'), false)
  assert.equal(overdue('completed', '2026-11-19'), false)
  assert.equal(overdue('verified', '2026-11-19'), false)
  assert.equal(overdue('rejected', null), false)
  assert.equal(overdue('accepted', null), false)
  assert.match(api.OVERDUE_RULE, /строк минув/)
  assert.match(api.OVERDUE_RULE, /«Виконано» чи «Перевірено»/)
  assert.equal(api.localDateIso(new Date(2026, 0, 5, 23, 30)), '2026-01-05')
  const counts = api.countActions([
    action({ id: 1, due_date: '2026-11-01' }), action({ id: 2, status: 'in_progress', due_date: '2027-01-01' }),
    action({ id: 3, status: 'completed', due_date: '2026-11-01' }), action({ id: 4, status: 'verified' }),
    action({ id: 5, status: 'rejected', owner: null, due_date: null }),
  ], TODAY)
  assert.deepEqual(counts, { accepted: 4, inProgress: 1, completed: 1, verified: 1, overdue: 1, rejected: 1 })
})

test('owner must be a position or unit, evidence is one reference per line, verification needs a later cycle', () => {
  for (const owner of ['Навчальний відділ', 'Головна інспекція', 'Заступник начальника з навчальної роботи', 'Кафедра №3']) {
    assert.equal(api.ownerProblem(owner), null, owner)
  }
  assert.match(api.ownerProblem('аб'), /від 3 до 120/)
  assert.match(api.ownerProblem('в'.repeat(121)), /від 3 до 120/)
  for (const owner of ['Іваненко Іван Іванович', 'Олена Петрівна', 'І. І. Іваненко', 'owner@example.test', '+380 50 123 45 67']) {
    assert.match(api.ownerProblem(owner), /не ПІБ/, owner)
  }
  assert.deepEqual(api.parseEvidence(' Наказ 1 \n\nНаказ 1\r\nПротокол   2 '), ['Наказ 1', 'Протокол 2'])
  const first = cycle(1, '2025-10-01')
  const later = api.laterClosedAssessments([
    first, cycle(2, '2026-04-01'), cycle(3, '2026-11-01', { status: 'open' }),
    cycle(4, '2026-05-01', { questionnaire_version: 'other' }), cycle(5, '2025-01-01'),
  ], first)
  assert.deepEqual(later.map(item => item.id), [2])
  assert.equal(api.transitionLabel('completed', 'in_progress'), 'Повернути в роботу')
  assert.equal(api.transitionLabel('accepted', 'in_progress'), 'Взяти в роботу')
})

test('panel explains that an official decides and starts in a loading state', () => {
  const markup = html(createElement(panel.default))
  assert.match(markup, /Трекер рекомендацій/)
  assert.match(markup, /Рішення ухвалює посадова особа, а не система/)
  assert.match(markup, /Завантажуємо цикли оцінювання/)
})

test('proposal list handles disabled demo, errors, empty and decided states', () => {
  const section = (state, decided = new Set()) => html(createElement(panel.ProposalsSection, {
    state, decided, today: TODAY, onDecide: noop, onRetry: () => {},
  }))
  const off = section({ status: 'error', message: 'Модуль не ввімкнений', code: 503 })
  assert.match(off, /role="alert"/)
  assert.match(off, /Модуль не ввімкнений/)
  assert.doesNotMatch(off, /Спробувати ще раз/)
  assert.doesNotMatch(section({ status: 'error', message: 'Немає прав', code: 403 }), /Спробувати ще раз/)
  assert.match(section({ status: 'error', message: 'Збій', code: 500 }), /Спробувати ще раз/)
  assert.match(section({ status: 'loading' }), /Завантажуємо пропозиції/)
  assert.match(section(recommendations([proposal('p1')]), null), /Завантажуємо пропозиції/)   // рішення ще не відомі
  assert.match(section(recommendations([])), /пропозицій немає/)
  assert.match(section(recommendations([proposal('p1')]), new Set(['p1'])), /вже розглянуто/)
  const pending = section(recommendations([proposal('p1'), proposal('p2', { text: 'Друга пропозиція' })]), new Set(['p1']))
  assert.doesNotMatch(pending, /Пропозиція p1/)
  assert.match(pending, /Друга пропозиція/)
  assert.match(pending, /Бал компонента нижче 50/)
  assert.match(pending, />Прийняти</)
  assert.match(pending, />Відхилити</)
})

test('decision forms: acceptance needs owner, deadline and reason; rejection needs only a reason', () => {
  const form = decision => html(createElement(panel.DecisionForm, {
    proposal: proposal('p1'), decision, today: TODAY, onSubmit: noop, onCancel: () => {},
  }))
  const accept = form('accepted')
  assert.match(accept, /Відповідальний \(посада або підрозділ, не ПІБ\)/)
  assert.match(accept, /maxLength="120"|maxlength="120"/)
  assert.match(accept, new RegExp(`type="date"[^>]*min="${TODAY}"`))
  assert.match(accept, /Обґрунтування рішення/)
  assert.match(accept, /Підтвердити прийняття/)
  const reject = form('rejected')
  assert.doesNotMatch(reject, /Відповідальний|type="date"/)
  assert.match(reject, /Обґрунтування відхилення/)
  assert.match(reject, /Підтвердити відхилення/)
})

test('measures table shows Ukrainian statuses, overdue highlighting, allowed transitions and verifying cycle', () => {
  const closed = [cycle(1, '2025-10-01'), cycle(2, '2026-04-01')]
  const actions = [
    action({ id: 1, due_date: '2026-11-01' }),
    action({ id: 2, status: 'in_progress', due_date: '2027-01-01', allowed_transitions: ['completed'] }),
    action({ id: 3, status: 'completed', allowed_transitions: ['in_progress', 'verified'], evidence_refs: ['Наказ 1'] }),
    action({ id: 4, status: 'verified', allowed_transitions: [], verified_in_assessment_id: 2 }),
    action({ id: 5, status: 'rejected', owner: null, due_date: null, allowed_transitions: [], text: 'Відхилена ідея', decision_reason: 'Дублює наявний план' }),
  ]
  const table = html(createElement(panel.ActionsTable, {
    actions, today: TODAY, current: closed[0], closed, onTransition: noop,
  }))
  for (const label of ['Компонент', 'Рекомендація', 'Відповідальний', 'Строк', 'Статус', 'Дії']) assert.match(table, new RegExp(label))
  for (const status of ['Прийнято', 'В роботі', 'Виконано', 'Перевірено']) assert.match(table, new RegExp(`>${status}<`))
  assert.equal(table.match(/class="is-overdue"/g)?.length, 1)
  assert.match(table, /tracker-badge">Прострочено</)
  assert.match(table, /01\.11\.2026/)
  for (const button of ['Взяти в роботу', 'Позначити виконаним', 'Повернути в роботу', 'Підтвердити перевіркою']) {
    assert.match(table, new RegExp(`>${button}<`))
  }
  assert.match(table, /циклом Cycle 2/)
  assert.match(table, /Історія рішень \(1\)/)
  assert.doesNotMatch(table, /Відхилена ідея/)
  const rejected = html(createElement(panel.RejectedList, { actions }))
  assert.match(rejected, /Відхилені пропозиції \(1\)/)
  assert.match(rejected, /Дублює наявний план/)
  assert.equal(html(createElement(panel.RejectedList, { actions: actions.slice(0, 4) })), '')
  assert.match(html(createElement(panel.ActionsTable, { actions: [], today: TODAY, current: closed[0], closed, onTransition: noop })),
    /Прийнятих заходів ще немає/)
  const counters = html(createElement(panel.TrackerCounters, { actions, today: TODAY }))
  for (const label of ['Прийнято', 'В роботі', 'Виконано', 'Перевірено', 'Прострочено']) assert.match(counters, new RegExp(`<dt>${label}</dt>`))
  assert.match(counters, /<dt>Прийнято<\/dt><dd>4<\/dd>/)
  assert.match(counters, /class="is-alert"><dt>Прострочено<\/dt><dd>1<\/dd>/)
})

test('transition form requires evidence for completed and verified and a later closed cycle for verification', () => {
  const form = (target, verifiers = []) => html(createElement(panel.TransitionForm, {
    action: action({ status: target === 'in_progress' ? 'accepted' : target === 'completed' ? 'in_progress' : 'completed' }),
    target, verifiers, onSubmit: noop, onCancel: () => {},
  }))
  assert.match(form('in_progress'), /Докази \(за потреби\)/)
  assert.match(form('completed'), /Докази \(обов’язково\)/)
  const blocked = form('verified')
  assert.match(blocked, /Немає пізнішого закритого циклу/)
  assert.match(blocked, /<button type="submit"[^>]*disabled=""/)
  const ready = form('verified', [cycle(2, '2026-04-01')])
  assert.match(ready, /Оцінювання, яке перевірило результат/)
  assert.match(ready, /Cycle 2 \(з 01\.04\.2026\)/)
  assert.doesNotMatch(ready, /<button type="submit"[^>]*disabled=""/)
})

test('measures section shows load errors without retry for permission problems', () => {
  const closed = [cycle(1, '2025-10-01')]
  const section = state => html(createElement(panel.ActionsSection, {
    state, today: TODAY, current: closed[0], closed, onTransition: noop, onRetry: () => {},
  }))
  assert.match(section({ status: 'loading' }), /Завантажуємо рішення/)
  const denied = section({ status: 'error', message: 'Для вашої ролі трекер рекомендацій недоступний.', code: 403 })
  assert.match(denied, /role="alert"/)
  assert.doesNotMatch(denied, /Спробувати ще раз/)
  assert.match(section({ status: 'error', message: 'Збій', code: 0 }), /Спробувати ще раз/)
  assert.match(section({ status: 'ready', data: trackerData() }), /Навчальний відділ/)
})
