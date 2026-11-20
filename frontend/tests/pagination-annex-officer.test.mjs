import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** Пагінація (вгорі й унизу) у чеклисті Додатка Б, об’єктивних показниках, відкритих циклах і групах участі. */
const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-pagination-annex-officer-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const checklist = await server.ssrLoadModule('/src/v2/ChecklistPanel.tsx')
const indicators = await server.ssrLoadModule('/src/v2/ObjectiveIndicatorsPanel.tsx')
const officer = await server.ssrLoadModule('/src/v2/DataOfficerPanel.tsx')
const participation = await server.ssrLoadModule('/src/components/Participation.tsx')
const issuer = await server.ssrLoadModule('/src/components/AccessCodeIssuer.tsx')
const admin = await server.ssrLoadModule('/src/api/admin.ts')

const html = element => renderToStaticMarkup(element)
const noop = () => {}
const count = (markup, pattern) => markup.match(pattern)?.length ?? 0
const pad = n => String(n).padStart(2, '0')

const cycle = (id, status = 'open', extra = {}) => ({ id, name: `Цикл ${pad(id)}`, start_date: `2026-01-${pad(id)}`, end_date: null, status, min_group_size: 5, categories: ['cadets'], ...extra })
const item = n => ({
  code: `B-${pad(n)}`, criterion: 'ethics', text: `Пункт ${pad(n)}`, source: 'Додаток Б (адаптовано)',
  status: n <= 12 ? 'yes' : null, evidence: n <= 12 ? 'Наказ' : null, entered_role: n <= 12 ? 'data_officer' : null, entered_at: null,
  confirmed: n <= 5, confirmed_role: n <= 5 ? 'admin' : null, confirmed_at: null,
})
const indicator = n => ({ id: n, criterion: 'education', name: `Показник ${pad(n)}`, unit: '%', value: 50, target: 90, period: '2026', entered_role: 'data_officer', confirmed: n % 2 === 0, confirmed_role: n % 2 === 0 ? 'admin' : null })

const checklistProps = (items, extra = {}) => ({ role: 'admin', cycles: { status: 'ready', data: [cycle(1)] }, cycleId: 1, onCycle: noop, onRetryCycles: noop,
  items: { status: 'ready', data: items }, onRetryItems: noop, busy: null, messages: {}, onSave: noop, onConfirm: noop, ...extra })
const indicatorProps = items => ({ role: 'admin', cycles: { status: 'ready', data: [cycle(1, 'closed')] }, cycleId: 1, onCycle: noop, onRetryCycles: noop,
  items: { status: 'ready', data: items }, onRetryItems: noop, busy: null, formError: '', messages: {}, onCreate: async () => true, onConfirm: noop })

/** Перевіряє спільну розмітку ListPagination: лічильник, вибір розміру й дві навігації (вгорі й унизу). */
function assertPaged(markup, name, { shown, pages }) {
  assert.ok(markup.includes(`Показано ${shown}`), `count label ${shown}`)
  assert.ok(markup.includes(`aria-label="Сторінки ${name} (угорі)"`), 'top pager')
  assert.ok(markup.includes(`aria-label="Сторінки ${name} (унизу)"`), 'bottom pager')
  assert.equal(count(markup, /aria-current="page"/g), 2, 'current page marked in both pagers')
  assert.equal(count(markup, new RegExp(`aria-label="Сторінка ${pages} з ${pages}"`, 'g')), 2, 'last page button in both pagers')
  assert.ok(markup.includes('На сторінці'), 'page size select')
  assert.match(markup, /<option value="10" selected="">10<\/option><option value="25">25<\/option><option value="50">50<\/option>/)
}

test('checklist: 20 Annex Б items are paged by 10 with pagers above and below, counters stay over all items', () => {
  const items = Array.from({ length: 20 }, (_, index) => item(index + 1))
  const markup = html(createElement(checklist.ChecklistView, checklistProps(items)))
  assertPaged(markup, 'чеклиста Додатка Б', { shown: '1–10 з 20', pages: 2 })
  assert.ok(markup.includes('B-01') && markup.includes('B-10'))
  assert.ok(!markup.includes('B-11') && !markup.includes('B-20'), 'second page is not rendered')
  assert.equal(count(markup, /<tr><th scope="row"/g), 10)
  assert.match(markup, /<dt>Внесено<\/dt><dd>12<\/dd>/)
  assert.match(markup, /<dt>Підтверджено<\/dt><dd>5<\/dd>/)
  assert.match(markup, /<dt>Усього пунктів<\/dt><dd>20<\/dd>/)
  // Пагінація стоїть між лічильниками й таблицею, а нижня навігація — після таблиці.
  const top = markup.indexOf('(угорі)'), table = markup.indexOf('<table'), bottom = markup.indexOf('(унизу)')
  assert.ok(markup.indexOf('Усього пунктів') < top && top < table && table < markup.indexOf('</table>') && markup.indexOf('</table>') < bottom)
})

test('checklist: a short list shows the count but no page navigation; empty list keeps its message', () => {
  const markup = html(createElement(checklist.ChecklistView, checklistProps([item(1), item(2), item(3)])))
  assert.ok(markup.includes('Показано 1–3 з 3'))
  assert.ok(!markup.includes('(угорі)') && !markup.includes('(унизу)') && !markup.includes('На сторінці'))
  const empty = html(createElement(checklist.ChecklistView, checklistProps([])))
  assert.ok(empty.includes('ще не сформовано') && !empty.includes('Показано'))
})

test('checklist table accepts a cycle resetKey and keeps role rules on the paged rows', () => {
  const items = Array.from({ length: 20 }, (_, index) => item(index + 1))
  const second = html(createElement(checklist.ChecklistTable, { items, role: 'data_officer', busy: null, onSave: noop, onConfirm: noop, resetKey: '2' }))
  assert.ok(second.includes('Показано 1–10 з 20'))
  assert.ok(!second.includes('>Підтвердити<'), 'data_officer still cannot confirm')
})

test('objective indicators: list is paged with counters over all indicators; form stays below', () => {
  const items = Array.from({ length: 23 }, (_, index) => indicator(index + 1))
  const markup = html(createElement(indicators.ObjectiveIndicatorsView, indicatorProps(items)))
  assertPaged(markup, 'об’єктивних показників', { shown: '1–10 з 23', pages: 3 })
  assert.ok(markup.includes('Показник 10') && !markup.includes('Показник 11'))
  assert.match(markup, /<dt>Показників<\/dt><dd>23<\/dd>/)
  assert.match(markup, /<dt>Підтверджено<\/dt><dd>11<\/dd>/)
  assert.ok(markup.indexOf('(унизу)') < markup.indexOf('Додати показник</h3>'), 'add form comes after the bottom pager')
  const short = html(createElement(indicators.ObjectiveIndicatorsView, indicatorProps([indicator(1)])))
  assert.ok(short.includes('Показано 1–1 з 1') && !short.includes('(угорі)'))
})

test('data officer: open cycles list is paged and closed cycles are not counted', () => {
  const cycles = [...Array.from({ length: 14 }, (_, index) => cycle(index + 1)), cycle(20, 'closed'), cycle(21, 'closed')]
  const markup = html(createElement(officer.OpenCyclesList, { cycles, selectedId: 1, locked: false, onSelect: noop }))
  assertPaged(markup, 'відкритих циклів', { shown: '1–10 з 14', pages: 2 })
  assert.equal(count(markup, /class="officer-panel__cycle(?: is-active)?"/g), 10)
  assert.ok(markup.includes('Цикл 10') && !markup.includes('Цикл 11') && !markup.includes('Цикл 20'))
  assert.match(markup, /aria-pressed="true"/)
  const few = html(createElement(officer.OpenCyclesList, { cycles: [cycle(1), cycle(2)], selectedId: null, locked: true, onSelect: noop }))
  assert.ok(few.includes('Показано 1–2 з 2') && !few.includes('(угорі)'))
  assert.match(html(createElement(officer.OpenCyclesList, { cycles: [cycle(3, 'closed')], selectedId: null, locked: false, onSelect: noop })), /Відкритих циклів немає/)
})

test('participation: groups by unit are paged; small breakdowns have no page navigation', () => {
  const groups = Array.from({ length: 27 }, (_, index) => ({ category: 'cadets', unit: `Підрозділ ${pad(index + 1)}`, responses: 5 + index }))
  const closed = admin.normalizeParticipation({ status: 'closed', tokens_issued: 400, tokens_unused: 10, responses_total: 390, participation_percent: 97.5, counts_exact: true, groups, suppressed: false })
  const markup = html(createElement(participation.ParticipationView, { participation: closed, cycle: { status: 'closed', min_group_size: 5 }, byUnit: true, onByUnitChange: noop }))
  assertPaged(markup, 'груп участі', { shown: '1–10 з 27', pages: 3 })
  assert.ok(markup.includes('Підрозділ 10') && !markup.includes('Підрозділ 11'))
  assert.ok(markup.includes('Категорія · підрозділ'))
  assert.match(markup, /Анкет:<\/dt> <dd>390<\/dd>/, 'totals stay over the whole cycle')
  const small = admin.normalizeParticipation({ status: 'closed', tokens_issued: 40, tokens_unused: 10, responses_total: 30, participation_percent: 75, counts_exact: true, groups: [{ category: 'cadets', responses: 26 }], suppressed: true })
  const smallMarkup = html(createElement(participation.ParticipationView, { participation: small, cycle: { status: 'closed', min_group_size: 5 } }))
  assert.ok(smallMarkup.includes('Показано 1–1 з 1') && !smallMarkup.includes('(угорі)'))
})

test('issued access codes stay a single textarea (not paged), so every code can be copied, downloaded and printed', () => {
  const tokens = Array.from({ length: 30 }, (_, index) => `CODE-${pad(index + 1)}`)
  const issued = { assessmentId: 7, assessmentName: 'Цикл 07', category: 'cadets', expiresDays: 14, issuedAt: '2026-11-20T10:00:00Z', tokens }
  const markup = html(createElement(issuer.IssuedCodesView, { issued, onDismiss: noop }))
  assert.ok(markup.includes('CODE-01') && markup.includes('CODE-30'))
  assert.ok(!markup.includes('Показано') && !markup.includes('Сторінки'))
})
