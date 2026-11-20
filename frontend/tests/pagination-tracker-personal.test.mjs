import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true },
  cacheDir: 'node_modules/.vite-pagination-tracker-personal-test',
  appType: 'custom',
  logLevel: 'error',
})
after(() => server.close())

const panel = await server.ssrLoadModule('/src/v2/TrackerPanel.tsx')
const personal = await server.ssrLoadModule('/src/v2/PersonalModule.tsx')
const html = element => renderToStaticMarkup(element)
const count = (markup, pattern) => (markup.match(pattern) ?? []).length
const noop = async () => {}

const TODAY = '2026-11-20'
// Синтетичні записи без персональних даних: відповідальний — підрозділ, тексти — шаблонні.
const action = (id, overrides = {}) => ({
  id, assessment_id: 1, recommendation_id: `rec-${id}`, rule_id: 'LOW_SCORE_LT_50_V1', component_code: `C${(id % 7) + 1}`,
  text: `Захід ${id}`, methodology_version: 'team-results-demo-0.1', status: 'accepted',
  owner: 'Навчальний відділ', due_date: '2026-12-01', decision_reason: 'Погоджено', evidence_refs: [],
  verified_in_assessment_id: null, overdue: false, allowed_transitions: ['in_progress'],
  history: [], created_at: '2026-11-20T10:00:00Z', updated_at: '2026-11-20T10:00:00Z',
  ...overrides,
})
const proposal = id => ({
  id: `p-${id}`, rule_id: 'LOW_SCORE_LT_50_V1', component_code: 'C3', text: `Пропозиція ${id}`,
  status: 'proposed', requires_human_decision: true,
})
const cycle = { id: 1, name: 'Cycle 1', start_date: '2026-01-01', status: 'closed', min_group_size: 5, questionnaire_version: 'demo-v1' }
const attempt = (id, status = 'completed') => ({
  id: `a-${id}`, assessment_id: `t-${id}`, assessment_name: `Тестування ${id}`, status, answers: { q1: 4, q2: 3 },
  started_at: '2026-11-01T10:00:00Z', completed_at: status === 'completed' ? '2026-11-02T10:00:00Z' : null, updated_at: '2026-11-02T10:00:00Z',
})
const range = (length, from = 1) => Array.from({ length }, (_, index) => index + from)

function assertTopAndBottom(markup, name, pages) {
  const top = `aria-label="Сторінки ${name} (угорі)"`
  const bottom = `aria-label="Сторінки ${name} (унизу)"`
  assert.ok(markup.includes(top), top)
  assert.ok(markup.includes(bottom), bottom)
  assert.equal(count(markup, /<nav class="test-list__pager"/g), 2)
  assert.equal(count(markup, /aria-current="page"/g), 2)
  assert.equal(count(markup, new RegExp(`aria-label="Сторінка 1 з ${pages}" aria-current="page"`, 'g')), 2)
  return { top: markup.indexOf(top), bottom: markup.indexOf(bottom) }
}

test('tracker proposals show 10 per page with pagers above and below, decided ones excluded', () => {
  const proposals = range(24).map(proposal)
  const markup = html(createElement(panel.ProposalsList, { proposals, decided: new Set(['p-1']), today: TODAY, onDecide: noop }))
  assert.ok(markup.includes('Показано 1–10 з 23'))
  assert.equal(count(markup, /<li class="tracker-proposal">/g), 10)
  assert.ok(!markup.includes('Пропозиція 1<'), 'вирішена пропозиція не показується')
  assert.ok(markup.includes('Пропозиція 2<') && markup.includes('Пропозиція 11<'))
  assert.ok(!markup.includes('Пропозиція 12<'), 'лише перша сторінка')
  const { top, bottom } = assertTopAndBottom(markup, 'пропозицій', 3)
  const list = markup.indexOf('<ul class="tracker-proposals">')
  assert.ok(top < list && list < bottom)
  assert.match(markup, /<option value="10" selected="">10<\/option><option value="25">25<\/option><option value="50">50<\/option>/)
})

test('short proposal list keeps the «Показано» line but no page navigation', () => {
  const markup = html(createElement(panel.ProposalsList, { proposals: range(3).map(proposal), decided: new Set(), today: TODAY, onDecide: noop }))
  assert.ok(markup.includes('Показано 1–3 з 3'))
  assert.equal(count(markup, /<li class="tracker-proposal">/g), 3)
  assert.ok(!markup.includes('test-list__pager'))
  assert.ok(!markup.includes('<select'), 'вибір розміру сторінки — лише для довгих списків')
  const done = html(createElement(panel.ProposalsList, { proposals: [proposal(1)], decided: new Set(['p-1']), today: TODAY, onDecide: noop }))
  assert.ok(done.includes('Усі пропозиції цього циклу вже розглянуто'))
  assert.ok(!done.includes('list-pagination'))
})

test('accepted actions table paginates rows, keeps headers and skips rejected decisions', () => {
  const actions = [...range(13).map(id => action(id)), action(99, { status: 'rejected', allowed_transitions: [] })]
  const markup = html(createElement(panel.ActionsTable, { actions, today: TODAY, current: cycle, closed: [cycle], onTransition: noop }))
  assert.ok(markup.includes('Показано 1–10 з 13'))
  assert.equal(count(markup, /<td data-label="Компонент">/g), 10)
  assert.equal(count(markup, /<th scope="col">/g), 6)
  assert.ok(!markup.includes('Захід 11<') && !markup.includes('Захід 99<'))
  const { top, bottom } = assertTopAndBottom(markup, 'прийнятих заходів', 2)
  const table = markup.indexOf('<table class="tracker-table">')
  assert.ok(top < table && table < bottom)
  const empty = html(createElement(panel.ActionsTable, { actions: [], today: TODAY, current: cycle, closed: [cycle], onTransition: noop }))
  assert.ok(empty.includes('Прийнятих заходів ще немає'))
  assert.ok(!empty.includes('list-pagination'))
})

test('summary counters count every action, not only the current page', () => {
  const actions = [
    ...range(12).map(id => action(id)),
    ...range(6, 20).map(id => action(id, { status: 'in_progress', due_date: '2026-01-01' })),
  ]
  const counters = html(createElement(panel.TrackerCounters, { actions, today: TODAY }))
  assert.match(counters, /<dt>Прийнято<\/dt><dd>18<\/dd>/)
  assert.match(counters, /<dt>В роботі<\/dt><dd>6<\/dd>/)
  assert.match(counters, /<dt>Прострочено<\/dt><dd>6<\/dd>/)
})

test('tracker resets both lists to page 1 when the cycle changes', () => {
  const source = readFileSync(new URL('../src/v2/TrackerPanel.tsx', import.meta.url), 'utf8')
  assert.equal(count(source, /resetKey=\{String\(assessment\.id\)\}/g), 2)
  assert.equal(count(source, /usePagination\([a-z]+, \{ resetKey \}\)/g), 2)
  assert.match(source, /<TrackerCycle key=\{selected\.id\}/)
})

test('«Мої результати» paginate completed attempts with pagers above and below', () => {
  const attempts = [attempt(0, 'draft'), ...range(12).map(id => attempt(id))]
  const markup = html(createElement(personal.CompletedAttempts, { attempts }))
  assert.ok(markup.includes('12 записів'), 'лічильник — за всіма завершеними')
  assert.ok(markup.includes('Показано 1–10 з 12'))
  assert.equal(count(markup, /<article class="v2-history-item"/g), 10)
  assert.ok(!markup.includes('Тестування 0<'), 'чернетка не показується')
  assert.ok(!markup.includes('Тестування 11<'))
  const { top, bottom } = assertTopAndBottom(markup, 'результатів', 2)
  const list = markup.indexOf('<div class="v2-history-list">')
  assert.ok(top < list && list < bottom)

  const few = html(createElement(personal.CompletedAttempts, { attempts: range(2).map(id => attempt(id)) }))
  assert.ok(few.includes('Показано 1–2 з 2'))
  assert.ok(!few.includes('test-list__pager'))
  const none = html(createElement(personal.CompletedAttempts, { attempts: [attempt(1, 'draft')] }))
  assert.ok(none.includes('Історія поки порожня'))
  assert.ok(!none.includes('list-pagination'))
})

test('pager buttons keep 44 px tap targets and compact width on phones', () => {
  const css = readFileSync(new URL('../src/v2/test-list.css', import.meta.url), 'utf8')
  assert.match(css, /\.test-list__pager \.v2-button \{\s*min-height: 2\.75rem;/)
  assert.match(css, /\.test-list__pages \.test-list__page \{\s*min-width: 2\.75rem;/)
  assert.match(css, /\.test-list__pager \.v2-button \{\s*width: auto;/)
})
