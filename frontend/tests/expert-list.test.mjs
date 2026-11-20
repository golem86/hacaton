import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** Перегляд внесених експертних оцінок (Анкета 1 Додатка В) у розділі «Експертне оцінювання». */
const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-expert-list-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const api = await server.ssrLoadModule('/src/api/annexV.ts')
const list = await server.ssrLoadModule('/src/v2/ExpertAssessmentList.tsx')
const official = await server.ssrLoadModule('/src/official/OfficialAssessment.tsx')

const html = element => renderToStaticMarkup(element)
const reply = (data, status = 200) => new Response(data === undefined ? null : JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

async function withFetch(handler, run) {
  const previous = globalThis.fetch
  globalThis.fetch = handler
  try { await run() } finally { globalThis.fetch = previous }
}

const answer = (questionId, criterion, letter, level, extra = {}) => ({
  question_id: questionId, question: `Питання ${questionId}`, criterion, option_id: `${questionId}-${letter}`, option: `Варіант ${letter} для ${questionId}`, level, ...extra,
})
const record = (id, overrides = {}) => ({
  id, expert_label: `Експерт-посада ${id}`, form: 1, version: '2.0.0', created_at: '2026-11-20T09:15:00Z', entered_role: 'admin', entered_by_user_id: 42,
  answers: [
    answer('av-f1-culture-1', 'leadership', 'e', 5),
    answer('av-f1-culture-4', 'openness', 'a', 1),
    answer('av-f1-culture-5', 'openness', 'd', 4),
    answer('av-f1-accountability-3', 'whistleblowers', 'f', 5),
  ],
  ...overrides,
})
const payload = (items, extra = {}) => ({
  assessment_id: 7, form: 1, version: '2.0.0', count: items.length, items,
  by_criterion: [
    { criterion: 'leadership', title: 'Лідерство керівника', levels: items.length ? [5, 2] : [], mean: items.length ? 3.5 : null },
    { criterion: 'openness', title: 'Відкритість інформації про доброчесність', levels: items.length ? [2.5, 2] : [], mean: items.length ? 2.25 : null },
  ],
  ...extra,
})
const ready = data => ({ status: 'ready', data })

// ---------------------------------------------------------------- API-клієнт

test('getExpertAssessments: GET of the exact path with the session cookie, no CSRF, normalised response', async () => {
  const calls = []
  const body = payload([record(3), { id: 'bad' }, record(5, { entered_by_user_id: null, entered_role: 'admin' })])
  await withFetch(async (url, options = {}) => { calls.push({ url, options }); return reply(body) }, async () => {
    const result = await api.getExpertAssessments(7)
    assert.equal(result.assessment_id, 7)
    assert.equal(result.count, 2)                                          // некоректний запис відкинуто
    assert.deepEqual(result.items.map(item => item.id), [3, 5])
    assert.equal(result.items[1].entered_by_user_id, null)
    assert.deepEqual(result.items[0].answers[0], answer('av-f1-culture-1', 'leadership', 'e', 5))
    assert.deepEqual(result.by_criterion[1], { criterion: 'openness', title: 'Відкритість інформації про доброчесність', levels: [2.5, 2], mean: 2.25 })
  })
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/assessments/7/annex-v/expert')
  assert.equal(calls[0].options.method ?? 'GET', 'GET')
  assert.equal(calls[0].options.credentials, 'include')
  assert.equal(new Headers(calls[0].options.headers).get('X-CSRF-Token'), null)
})

test('getExpertAssessments: Ukrainian messages for 403/404 and an error for malformed JSON', async () => {
  for (const [status, pattern] of [[403, /лише адміністратор/], [404, /Цикл оцінювання не знайдено/]]) {
    await withFetch(async () => reply({ detail: 'x' }, status), async () => {
      await assert.rejects(api.getExpertAssessments(1), error => { assert.equal(error.status, status); assert.match(error.message, pattern); return true })
    })
  }
  await withFetch(async () => reply({ items: 'nope' }), async () => {
    await assert.rejects(api.getExpertAssessments(1), /некоректний перелік експертних оцінок/)
  })
})

test('record helpers: levels per criterion average openness within a record; formatting and author label', () => {
  assert.deepEqual(list.recordLevels(api.normalizeExpertRecord(record(1))), [
    { criterion: 'leadership', level: 5 }, { criterion: 'openness', level: 2.5 }, { criterion: 'whistleblowers', level: 5 },
  ])
  assert.equal(list.formatExpertLevel(2.25), '2,25')
  assert.equal(list.formatExpertLevel(null), '—')
  assert.equal(list.enteredByLabel({ entered_role: 'admin', entered_by_user_id: 42 }), 'Адміністратор · id 42')
  assert.equal(list.enteredByLabel({ entered_role: 'admin', entered_by_user_id: null }), 'Адміністратор')
})

// ---------------------------------------------------------------- Відображення

test('list view: records table with position, date, author, levels and expandable answers; criterion summary', () => {
  const data = payload([record(3), record(5, { expert_label: 'Член робочої групи' })])
  const markup = html(createElement(list.ExpertListView, { state: ready(api.normalizeExpertList(data, 7)) }))
  assert.match(markup, /Внесені експертні оцінки циклу/)
  assert.match(markup, /Експерт-посада 3/)
  assert.match(markup, /Член робочої групи/)
  assert.match(markup, /20\.11\.2026/)
  assert.match(markup, /Адміністратор · id 42/)
  assert.match(markup, /<details[^>]*><summary>Відповіді \(4\)<\/summary>/)
  assert.match(markup, /Питання av-f1-accountability-3<\/strong><span>Варіант f для av-f1-accountability-3<\/span><small>Рівень: 5/)
  assert.match(markup, /<dd>2,5<\/dd>/)                                          // openness: (1 + 4) / 2
  assert.match(markup, /Підсумок за критеріями/)
  assert.match(markup, /Відкритість інформації \(C7\)<\/th><td data-label="Середній рівень"><strong>2,25<\/strong><\/td><td data-label="Експертів">2<\/td>/)
  assert.match(markup, /Показано 1–2 з 2/)
  assert.ok(!/style=/.test(markup))                                             // CSP: без inline-стилів
  assert.ok(!/email|@/.test(markup))
})

test('list view: empty, idle, loading and error states', () => {
  const empty = html(createElement(list.ExpertListView, { state: ready(api.normalizeExpertList(payload([]), 7)) }))
  assert.match(empty, /Для цього циклу експертних оцінок ще не внесено/)
  assert.ok(!empty.includes('<table'))
  assert.match(html(createElement(list.ExpertListView, { state: { status: 'idle' } })), /Оберіть цикл/)
  assert.match(html(createElement(list.ExpertListView, { state: { status: 'loading' } })), /Завантажуємо експертні оцінки/)
  const error = html(createElement(list.ExpertListView, { state: { status: 'error', message: 'Сервіс тимчасово недоступний.' }, onRetry: () => {} }))
  assert.match(error, /role="alert"/)
  assert.match(error, /Спробувати ще раз/)
})

test('list view paginates records like other lists (10 per page)', () => {
  const items = Array.from({ length: 12 }, (_, index) => record(index + 1))
  const markup = html(createElement(list.ExpertListView, { state: ready(api.normalizeExpertList(payload(items), 7)) }))
  assert.match(markup, /Показано 1–10 з 12/)
  assert.match(markup, /Сторінки експертних оцінок \(угорі\)/)
  assert.equal((markup.match(/<tr><th scope="row" data-label="Посада експерта">/g) ?? []).length, 10)
  assert.ok(markup.includes('Експерт-посада 10') && !markup.includes('Експерт-посада 11'))
})

test('expert section renders the list block under the form; the anonymous form does not', () => {
  const cycle = { id: 4, name: 'Цикл 4', start_date: '2026-04-01', status: 'open', min_group_size: 5 }
  const expert = html(createElement(official.default, { mode: 'expert', cycles: [cycle] }))
  assert.match(expert, /Внесені експертні оцінки циклу/)
  assert.match(expert, /Завантажуємо експертні оцінки/)                          // цикл обрано — список вантажиться
  assert.ok(expert.indexOf('Внесені експертні оцінки циклу') > expert.indexOf('Перевірити відповіді'))
  const self = html(createElement(official.default, { mode: 'self', cycles: [cycle] }))
  assert.ok(!self.includes('Внесені експертні оцінки циклу'))
})
