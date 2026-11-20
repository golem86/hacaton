import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-test-list-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const list = await server.ssrLoadModule('/src/v2/testList.ts')
const personal = await server.ssrLoadModule('/src/v2/PersonalModule.tsx')
const api = await server.ssrLoadModule('/src/api/v2User.ts')

// Синтетичний каталог у формі відповіді GET /v2/user/assessments; статуси — на V2_CATALOG_NOW бекенд-тестів.
const NOW = Date.parse('2026-11-18T12:00:00+00:00')
const OPEN = new Set(['personal-2026-q4', 'thematic-2026-reporting-channels', 'thematic-2026-conflict-of-interest', 'training-2026-integrity'])
const ROWS = [
  ['personal-2026-q4', 'Особисте самооцінювання · Q4 2026', '2026-11-03T09:00:00+00:00', '2026-11-17T00:00:00+00:00', '2026-11-24T23:59:59+00:00'],
  ['personal-2027-q1', 'Особисте самооцінювання · Q1 2027', '2026-11-10T10:30:00+00:00', '2027-01-01T00:00:00+00:00', '2027-01-08T23:59:59+00:00'],
  ['personal-2025-q1', 'Особисте самооцінювання · Q1 2025', '2025-01-08T09:00:00+00:00', '2025-01-15T00:00:00+00:00', '2025-01-31T23:59:59+00:00'],
  ['personal-2025-q2', 'Особисте самооцінювання · Q2 2025', '2025-04-01T09:00:00+00:00', '2025-04-07T00:00:00+00:00', '2025-04-25T23:59:59+00:00'],
  ['personal-2025-q3', 'Особисте самооцінювання · Q3 2025', '2025-07-01T09:00:00+00:00', '2025-07-07T00:00:00+00:00', '2025-07-25T23:59:59+00:00'],
  ['personal-2025-q4', 'Особисте самооцінювання · Q4 2025', '2025-09-30T09:00:00+00:00', '2025-10-06T00:00:00+00:00', '2025-10-24T23:59:59+00:00'],
  ['personal-2026-q1', 'Особисте самооцінювання · Q1 2026', '2026-01-05T09:00:00+00:00', '2026-01-12T00:00:00+00:00', '2026-01-30T23:59:59+00:00'],
  ['personal-2026-q2', 'Особисте самооцінювання · Q2 2026', '2026-03-31T09:00:00+00:00', '2026-04-06T00:00:00+00:00', '2026-04-24T23:59:59+00:00'],
  ['personal-2026-q3', 'Особисте самооцінювання · Q3 2026', '2026-06-30T09:00:00+00:00', '2026-07-06T00:00:00+00:00', '2026-07-24T23:59:59+00:00'],
  ['thematic-2026-gifts', 'Тематичне самооцінювання: подарунки та гостинність', '2026-08-18T11:00:00+00:00', '2026-09-01T00:00:00+00:00', '2026-09-30T23:59:59+00:00'],
  ['thematic-2026-reporting-channels', 'Тематичне самооцінювання: канали повідомлень', '2026-10-20T08:15:00+00:00', '2026-11-02T00:00:00+00:00', '2026-11-30T23:59:59+00:00'],
  ['thematic-2026-conflict-of-interest', 'Тематичне самооцінювання: конфлікт інтересів', '2026-10-27T13:40:00+00:00', '2026-11-09T00:00:00+00:00', '2026-12-11T23:59:59+00:00'],
  ['training-2026-integrity', 'Самооцінювання після навчання з доброчесності', '2026-11-12T07:30:00+00:00', '2026-11-16T00:00:00+00:00', '2026-12-04T23:59:59+00:00'],
  ['thematic-2026-leadership', 'Тематичне самооцінювання: приклад керівництва', '2026-11-14T10:00:00+00:00', '2026-12-01T00:00:00+00:00', '2026-12-18T23:59:59+00:00'],
  ['training-2027-onboarding', 'Самооцінювання після вступного інструктажу', '2026-11-16T12:00:00+00:00', '2027-02-01T00:00:00+00:00', '2027-02-15T23:59:59+00:00'],
  ['thematic-2027-transparency', 'Тематичне самооцінювання: прозорість рішень', '2026-11-17T09:20:00+00:00', '2027-03-01T00:00:00+00:00', '2027-03-19T23:59:59+00:00'],
  ['personal-2027-q2', 'Особисте самооцінювання · Q2 2027', '2026-11-18T08:00:00+00:00', '2027-04-05T00:00:00+00:00', '2027-04-23T23:59:59+00:00'],
]
const QUESTIONS = Array.from({ length: 7 }, (_, index) => ({ id: `q${index + 1}`, component: `C${index + 1}`, prompt: 'Синтетичне питання', hint: 'Підказка' }))
const catalog = ROWS.map(([id, name, created_at, opens_at, closes_at]) => ({
  id, name, duration: '7 питань · близько 5 хв', created_at, opens_at, closes_at, status: OPEN.has(id) ? 'open' : 'unavailable', questions: QUESTIONS,
}))
const filters = patch => ({ ...list.DEFAULT_FILTERS, ...patch })
const ids = items => items.map(item => item.id)
const utc = { timeZone: 'UTC' }

test('search by name ignores case, extra spaces and apostrophe variants, including Ukrainian letters', () => {
  assert.equal(list.normalizeSearchText('  ҐРУНТОВНЕ   ЇЖАК\tЄ  І '), 'ґрунтовне їжак є і')
  assert.equal(list.normalizeSearchText("пов'язане"), list.normalizeSearchText('ПОВ’ЯЗАНЕ'))
  assert.equal(list.normalizeSearchText('пов`язане'), list.normalizeSearchText('повʼязане'))
  assert.equal(list.filterTests(catalog, filters({ query: '  ОСОБИСТЕ   САМООЦІНЮВАННЯ ' })).length, 10)
  assert.deepEqual(ids(list.filterTests(catalog, filters({ query: 'тематичне ' }))).length, 5)
  assert.deepEqual(ids(list.filterTests(catalog, filters({ query: 'Канали   ПОВІДОМЛЕНЬ' }))), ['thematic-2026-reporting-channels'])
  // Кілька слів у будь-якому порядку: кожне має бути в назві.
  assert.deepEqual(ids(list.filterTests(catalog, filters({ query: '2026 q1 самооцінювання' }))), ['personal-2026-q1'])
  assert.deepEqual(list.filterTests(catalog, filters({ query: 'немає такого тестування' })), [])
  assert.equal(list.filterTests(catalog, filters({ query: '   ' })).length, catalog.length)
})

test('status filter separates open and unavailable tests', () => {
  assert.equal(list.filterTests(catalog, filters({ status: 'all' })).length, 17)
  assert.deepEqual(new Set(ids(list.filterTests(catalog, filters({ status: 'open' })))), OPEN)
  const unavailable = list.filterTests(catalog, filters({ status: 'unavailable' }))
  assert.equal(unavailable.length, 13)
  assert.ok(unavailable.every(item => item.status === 'unavailable'))
})

test('creation date range is inclusive on both ends', () => {
  const range = (createdFrom, createdTo) => ids(list.filterTests(catalog, filters({ createdFrom, createdTo }), utc))
  assert.deepEqual(range('2026-11-12', '2026-11-16'), ['training-2026-integrity', 'thematic-2026-leadership', 'training-2027-onboarding'])
  assert.deepEqual(range('2026-11-18', ''), ['personal-2027-q2'])
  assert.deepEqual(range('', '2025-01-08'), ['personal-2025-q1'])
  assert.deepEqual(range('2025-01-09', '2025-03-31'), [])
  assert.deepEqual(range('2026-11-16', '2026-11-12'), [], 'перевернутий діапазон нічого не знаходить')
  assert.equal(range('', '').length, 17)
  assert.equal(range('не дата', '').length, 17, 'некоректна межа ігнорується')
})

test('deadline range uses calendar days in the given time zone', () => {
  const range = (deadlineFrom, deadlineTo, timeZone = 'UTC') => ids(list.filterTests(catalog, filters({ deadlineFrom, deadlineTo }), { timeZone }))
  assert.deepEqual(range('2026-11-24', '2026-11-30'), ['personal-2026-q4', 'thematic-2026-reporting-channels'])
  assert.deepEqual(range('2027-01-01', ''), ['personal-2027-q1', 'training-2027-onboarding', 'thematic-2027-transparency', 'personal-2027-q2'])
  assert.deepEqual(range('', '2025-01-31'), ['personal-2025-q1'])
  // 2026-11-24T23:59:59Z у Києві — це вже 25 листопада.
  assert.deepEqual(range('2026-11-24', '2026-11-24', 'Europe/Kyiv'), [])
  assert.deepEqual(range('2026-11-25', '2026-11-25', 'Europe/Kyiv'), ['personal-2026-q4'])
  assert.equal(list.toDateKey('2026-11-24T23:59:59+00:00', 'UTC'), '2026-11-24')
  assert.equal(list.toDateKey('not-a-date', 'UTC'), '')
  // Фільтри поєднуються.
  assert.deepEqual(ids(list.filterTests(catalog, filters({ status: 'open', query: 'тематичне', deadlineTo: '2026-11-30' }), utc)), ['thematic-2026-reporting-channels'])
})

test('default sort puts open tests first by nearest deadline, then upcoming, then recently finished', () => {
  assert.equal(list.DEFAULT_SORT, 'deadline-asc')
  const sorted = ids(list.sortTests(catalog, 'deadline-asc', { now: NOW }))
  assert.deepEqual(sorted, [
    'personal-2026-q4', 'thematic-2026-reporting-channels', 'training-2026-integrity', 'thematic-2026-conflict-of-interest',
    'thematic-2026-leadership', 'personal-2027-q1', 'training-2027-onboarding', 'thematic-2027-transparency', 'personal-2027-q2',
    'thematic-2026-gifts', 'personal-2026-q3', 'personal-2026-q2', 'personal-2026-q1', 'personal-2025-q4', 'personal-2025-q3', 'personal-2025-q2', 'personal-2025-q1',
  ])
  assert.equal(list.availabilityOf(catalog[0], NOW), 'open')
  assert.equal(list.availabilityOf(catalog[1], NOW), 'upcoming')
  assert.equal(list.availabilityOf(catalog[2], NOW), 'closed')
})

test('every sort option orders by name, creation date or deadline without mutating input', () => {
  const before = ids(catalog)
  const sorted = sort => ids(list.sortTests(catalog, sort, { now: NOW }))
  assert.deepEqual(list.SORT_OPTIONS.map(option => option.value), ['deadline-asc', 'deadline-desc', 'created-desc', 'created-asc', 'name-asc', 'name-desc'])
  assert.deepEqual(sorted('deadline-desc').slice(0, 3), ['personal-2027-q2', 'thematic-2027-transparency', 'training-2027-onboarding'])
  assert.equal(sorted('deadline-desc').at(-1), 'personal-2025-q1')
  assert.deepEqual(sorted('created-desc').slice(0, 3), ['personal-2027-q2', 'thematic-2027-transparency', 'training-2027-onboarding'])
  assert.deepEqual(sorted('created-asc').slice(0, 2), ['personal-2025-q1', 'personal-2025-q2'])
  assert.equal(sorted('created-asc').at(-1), 'personal-2027-q2')
  const byName = sorted('name-asc')
  assert.deepEqual(byName.slice(0, 4), ['personal-2025-q1', 'personal-2026-q1', 'personal-2027-q1', 'personal-2025-q2'], 'числа порівнюються як числа')
  assert.equal(byName.at(-1), 'thematic-2027-transparency')
  assert.deepEqual(sorted('name-desc'), [...byName].reverse())
  assert.deepEqual(ids(catalog), before)
  // Українська абетка: Г < Ґ, Е < Є, И < І < Ї; регістр не впливає.
  const letters = ['Їжак', 'іній', 'Ґанок', 'гай', 'Яр', 'Єнот', 'ера', 'Икло'].map((name, index) => ({ ...catalog[0], id: `x${index}`, name }))
  assert.deepEqual(list.sortTests(letters, 'name-asc').map(item => item.name), ['гай', 'Ґанок', 'ера', 'Єнот', 'Икло', 'іній', 'Їжак', 'Яр'])
  // Некоректні дати завжди наприкінці.
  const broken = [{ ...catalog[0], id: 'broken', created_at: 'oops' }, catalog[2], catalog[16]]
  assert.deepEqual(ids(list.sortTests(broken, 'created-desc')), ['personal-2027-q2', 'personal-2025-q1', 'broken'])
  assert.deepEqual(ids(list.sortTests(broken, 'created-asc')), ['personal-2025-q1', 'personal-2027-q2', 'broken'])
})

test('paginate handles empty lists, partial last pages and clamps the page', () => {
  assert.deepEqual(list.paginate([], 1, 6), { items: [], page: 1, pageCount: 1, pageSize: 6, total: 0, start: 0, end: 0 })
  assert.deepEqual(list.paginate([], 4, 6).page, 1)
  const first = list.paginate(catalog, 1, 6)
  assert.deepEqual([first.start, first.end, first.pageCount, first.items.length], [1, 6, 3, 6])
  const last = list.paginate(catalog, 3, 6)
  assert.deepEqual([last.page, last.start, last.end, last.items.length], [3, 13, 17, 5])
  assert.deepEqual(ids(last.items), ids(catalog.slice(12)))
  assert.equal(list.paginate(catalog, 99, 6).page, 3, 'сторінка за межами — остання')
  assert.equal(list.paginate(catalog, 0, 6).page, 1)
  assert.equal(list.paginate(catalog, -5, 6).page, 1)
  assert.equal(list.paginate(catalog, Number.NaN, 6).page, 1)
  assert.equal(list.paginate(catalog, 3, 12).page, 2, 'після збільшення розміру сторінка обмежується')
  assert.deepEqual([list.paginate(catalog, 1, 24).pageCount, list.paginate(catalog, 1, 24).end], [1, 17])
  assert.equal(list.paginate(catalog.slice(0, 12), 2, 6).end, 12, 'повна остання сторінка')
  assert.equal(list.paginate(catalog, 1, 0).pageSize, 6, 'некоректний розмір — типовий')
  assert.deepEqual([...list.PAGE_SIZES], [6, 12, 24])
  assert.equal(list.DEFAULT_PAGE_SIZE, 6)
  assert.equal(list.shownLabel(first), 'Показано 1–6 з 17')
  assert.equal(list.shownLabel(last), 'Показано 13–17 з 17')
  assert.equal(list.shownLabel(list.paginate([], 1, 6)), 'Показано 0 з 0')
})

test('page tokens show first, last and neighbours with ellipses for many pages', () => {
  assert.deepEqual(list.pageTokens(1, 1), [1])
  assert.deepEqual(list.pageTokens(2, 3), [1, 2, 3])
  assert.deepEqual(list.pageTokens(1, 7), [1, 2, 3, 4, 5, 6, 7])
  assert.deepEqual(list.pageTokens(1, 10), [1, 2, 3, 4, 5, 'ellipsis-end', 10])
  assert.deepEqual(list.pageTokens(5, 10), [1, 'ellipsis-start', 4, 5, 6, 'ellipsis-end', 10])
  assert.deepEqual(list.pageTokens(8, 10), [1, 'ellipsis-start', 6, 7, 8, 9, 10])
  assert.deepEqual(list.pageTokens(99, 10), [1, 'ellipsis-start', 6, 7, 8, 9, 10])
})

test('stored list state is validated before use', () => {
  assert.equal(list.parseStoredState(null), null)
  assert.equal(list.parseStoredState('{не json'), null)
  assert.equal(list.parseStoredState('42'), null)
  const parsed = list.parseStoredState(JSON.stringify({ filters: { query: 'Q1', status: 'hacked', createdFrom: '2026-01-01', deadlineTo: '<script>' }, sort: 'evil', pageSize: 1000, page: -1 }))
  assert.deepEqual(parsed, {
    filters: { query: 'Q1', status: 'all', createdFrom: '2026-01-01', createdTo: '', deadlineFrom: '', deadlineTo: '' },
    sort: 'deadline-asc', pageSize: 6, page: 1,
  })
  assert.equal(list.parseStoredState(JSON.stringify({ sort: 'name-desc', pageSize: 12, page: 2 })).sort, 'name-desc')
  assert.equal(list.activeFilterCount(list.DEFAULT_FILTERS), 0)
  assert.equal(list.activeFilterCount(filters({ query: ' x ', status: 'open', createdFrom: '2026-01-01', deadlineTo: '2026-12-31' })), 4)
})

const render = props => renderToStaticMarkup(React.createElement(personal.AvailableTests, {
  assessments: catalog, attempts: [], onStart() {}, now: NOW, timeZone: 'UTC', ...props,
}))
const count = (html, pattern) => (html.match(pattern) ?? []).length
const dateOnly = value => new Intl.DateTimeFormat('uk-UA', { dateStyle: 'medium', timeZone: 'UTC' }).format(Date.parse(value))
const dateTime = value => new Intl.DateTimeFormat('uk-UA', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(Date.parse(value))
const escape = value => value.replace(/&/g, '&amp;').replace(/</g, '&lt;')

test('list renders search, filters, sorting, page size and the «Показано» summary', () => {
  const draft = { id: 'draft-1', assessment_id: 'training-2026-integrity', assessment_name: 'x', status: 'draft', answers: {}, started_at: '2026-11-18T10:00:00Z', completed_at: null, updated_at: '2026-11-18T10:00:00Z' }
  const html = render({ attempts: [draft] })
  for (const text of ['Доступні тестування', 'Пошук за назвою', 'type="search"', 'Статус', 'Доступні зараз', 'Недоступні', 'Дата створення', 'Дедлайн', 'від', 'до', 'Сортування', 'Дедлайн: найближчий', 'Назва: А–Я', 'Назва: Я–А', 'Дата створення: новіші', 'Дата створення: старіші', 'Дедлайн: найпізніший', 'На сторінці', 'Скинути фільтри', 'Фільтри', 'Показано 1–6 з 17', 'Список тестувань', 'сторінка 1 з 3']) {
    assert.ok(html.includes(text), text)
  }
  assert.equal(count(html, /type="date"/g), 4)
  assert.equal(count(html, /<label for="[^"]+"/g), 8, 'кожне поле має підпис')
  assert.equal(count(html, /<article /g), 6)
  assert.match(html, /<option value="6" selected="">6<\/option><option value="12">12<\/option><option value="24">24<\/option>/)
  assert.match(html, /<option value="deadline-asc" selected="">/)
  assert.match(html, /<button[^>]*disabled=""[^>]*>Скинути фільтри<\/button>/)
  assert.match(html, /aria-expanded="false"/)
  // Порядок за замовчуванням і глобальна нумерація.
  assert.deepEqual([...html.matchAll(/class="v2-test-number">(\d+)</g)].map(match => match[1]), ['01', '02', '03', '04', '05', '06'])
  assert.ok(html.indexOf('Особисте самооцінювання · Q4 2026') < html.indexOf('Тематичне самооцінювання: канали повідомлень'))
  // Дії картки: чернетка, відкрите й недоступне.
  assert.ok(html.includes('>Продовжити</button>'))
  assert.equal(count(html, />Розпочати<\/button>/g), 3)
  assert.equal(count(html, />Недоступне<\/button>/g), 2)
  for (const label of ['Доступне зараз', 'Заплановано', 'Створено', 'Відкриття']) assert.ok(html.includes(label), label)
  // Дати у форматі uk-UA і машинозчитувані значення.
  assert.ok(html.includes(`<time dateTime="2026-11-03T09:00:00+00:00">${escape(dateOnly('2026-11-03T09:00:00+00:00'))}</time>`))
  assert.ok(html.includes(escape(dateTime('2026-11-24T23:59:59+00:00'))))
  assert.doesNotMatch(html, />2026-11-24T23:59:59\+00:00</)
  // Пагінація.
  assert.match(html, /<nav class="test-list__pager" aria-label="Сторінки списку тестувань">/)
  assert.match(html, /aria-label="Сторінка 1 з 3" aria-current="page"/)
  assert.equal(count(html, /aria-current="page"/g), 1)
  assert.match(html, /<button class="v2-button test-list__pager-step" type="button" disabled="">.*?Попередня<\/button>/)
  assert.match(html, /<button class="v2-button test-list__pager-step" type="button">Наступна/)
  assert.match(html, /<h3 class="test-list__heading" id="[^"]+" tabindex="-1">/)
})

test('last page, clamping, page size and filters change what the list shows', () => {
  const last = render({ initialState: { page: 3 } })
  assert.ok(last.includes('Показано 13–17 з 17'))
  assert.equal(count(last, /<article /g), 5)
  assert.deepEqual([...last.matchAll(/class="v2-test-number">(\d+)</g)].map(match => match[1]), ['13', '14', '15', '16', '17'])
  assert.match(last, /aria-label="Сторінка 3 з 3" aria-current="page"/)
  assert.match(last, /<button class="v2-button test-list__pager-step" type="button" disabled="">Наступна/)
  assert.ok(last.includes('Завершено'))

  const clamped = render({ initialState: { page: 99 } })
  assert.ok(clamped.includes('Показано 13–17 з 17'))

  const all = render({ initialState: { pageSize: 24 } })
  assert.ok(all.includes('Показано 1–17 з 17'))
  assert.equal(count(all, /<article /g), 17)
  assert.ok(!all.includes('test-list__pager'), 'одна сторінка — без навігації')
  assert.match(all, /<option value="24" selected="">/)

  const open = render({ initialState: { filters: { status: 'open' } } })
  assert.ok(open.includes('Показано 1–4 з 4'))
  assert.ok(open.includes('усього 17'))
  assert.ok(open.includes('Фільтри (1)'))
  assert.match(open, /<button class="v2-button v2-button-quiet test-list__reset" type="button">Скинути фільтри<\/button>/)

  const sortedByName = render({ initialState: { sort: 'name-desc' } })
  assert.match(sortedByName, /<option value="name-desc" selected="">/)
  assert.ok(sortedByName.indexOf('прозорість рішень') < sortedByName.indexOf('приклад керівництва'))
})

test('empty results show a clear message and a reset button', () => {
  const html = render({ initialState: { filters: { query: 'немає такого' } } })
  assert.ok(html.includes('Нічого не знайдено за цими умовами'))
  assert.equal(count(html, /<article /g), 0)
  assert.ok(!html.includes('test-list__pager'))
  assert.equal(count(html, />Скинути фільтри<\/button>/g), 2)
  const none = render({ assessments: [] })
  assert.ok(none.includes('Нічого не знайдено за цими умовами'))
  assert.ok(none.includes('Тестувань поки немає.'))
})

test('assessments API passes created_at through to the list helpers', async () => {
  const oldFetch = globalThis.fetch
  const seen = []
  try {
    globalThis.fetch = async (url, options) => {
      seen.push({ url, credentials: options?.credentials })
      return new Response(JSON.stringify(catalog), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    const items = await api.getPersonalAssessments()
    assert.deepEqual(seen.map(item => item.url), ['/v2/user/assessments'])
    assert.equal(seen[0].credentials, 'include')
    assert.ok(items.every(item => typeof item.created_at === 'string' && item.created_at <= item.opens_at))
    const page = list.paginate(list.sortTests(list.filterTests(items, filters({ createdFrom: '2026-11-01' }), utc), 'created-desc', { now: NOW }), 1, 6)
    assert.equal(list.shownLabel(page), 'Показано 1–6 з 7')
    assert.equal(page.items[0].id, 'personal-2027-q2')
  } finally { globalThis.fetch = oldFetch }
})
