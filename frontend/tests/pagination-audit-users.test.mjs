import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-pagination-audit-users-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const audit = await server.ssrLoadModule('/src/v2/AuditTrail.tsx')
const usersPanel = await server.ssrLoadModule('/src/v2/UsersPanel.tsx')
const list = await server.ssrLoadModule('/src/v2/testList.ts')

const html = (type, props) => renderToStaticMarkup(React.createElement(type, props))
const count = (markup, pattern) => (markup.match(pattern) ?? []).length
const bodyRows = markup => count(markup, /<tr[ >]/g) - 1 // мінус рядок заголовка

// 25 синтетичних подій, новіші першими: непарні id — вхід без циклу, парні — видача кодів у циклі № 4.
const events = Array.from({ length: 25 }, (_, index) => {
  const id = 25 - index
  const login = id % 2 === 1
  return {
    id,
    created_at: new Date(Date.UTC(2026, 10, 20, 9, 0, 0) - index * 60_000).toISOString(),
    actor_role: login ? 'user' : 'admin',
    action: login ? 'auth.login' : 'tokens.issue',
    assessment_id: login ? null : 4,
    details: login ? {} : { count: id },
  }
})

test('audit trail with 25 events renders pagers above and below the table', () => {
  const markup = html(audit.default, { events, error: '' })
  assert.equal(count(markup, /aria-label="Сторінки журналу дій \(угорі\)"/g), 1)
  assert.equal(count(markup, /aria-label="Сторінки журналу дій \(унизу\)"/g), 1)
  const top = markup.indexOf('(угорі)')
  const table = markup.indexOf('<table')
  const bottom = markup.indexOf('(унизу)')
  assert.ok(top > 0 && top < table && table < bottom, 'пейджер угорі, потім таблиця, потім пейджер унизу')
  assert.ok(markup.includes('Показано 1–10 з 25'))
  assert.match(markup, /aria-label="Сторінка 1 з 3" aria-current="page"/)
  assert.ok(markup.includes('На сторінці'))
  // Таблиця, прихований підпис і мобільні data-label не змінилися.
  assert.ok(markup.includes('<caption class="audit-trail__sr-only">'))
  assert.ok(markup.includes('data-label="Дата і час"'))
  // Бейдж рахує весь журнал, а не сторінку.
  assert.ok(markup.includes('25 записів'))
})

test('first audit page shows exactly the 10 newest events', () => {
  const markup = html(audit.default, { events, error: '' })
  assert.equal(bodyRows(markup), 10)
  assert.equal(count(markup, /<time class="audit-trail__time"/g), 10)
  assert.ok(markup.includes('24 коди'), 'подія № 24 — на першій сторінці')
  assert.ok(markup.includes('16 кодів'), 'подія № 16 — десята, ще на першій сторінці')
  assert.ok(!markup.includes('14 кодів'), 'подія № 14 — уже на другій сторінці')
})

test('small audit journal shows the count but no page buttons', () => {
  const markup = html(audit.default, { events: events.slice(0, 3), error: '' })
  assert.ok(markup.includes('Показано 1–3 з 3'))
  assert.ok(!markup.includes('Сторінки журналу дій'))
  assert.equal(bodyRows(markup), 3)
})

test('filters apply before pagination and every filter change gets a new reset key', () => {
  const codes = audit.filterAuditEvents(events, 'tokens.issue', 'all')
  assert.equal(codes.length, 12)
  assert.ok(codes.every(event => event.action === 'tokens.issue'))
  assert.equal(audit.filterAuditEvents(events, 'all', 'none').length, 13)
  assert.equal(audit.filterAuditEvents(events, 'all', '4').length, 12)
  assert.equal(audit.filterAuditEvents(events, 'auth.login', '4').length, 0)
  assert.equal(audit.filterAuditEvents(events, 'all', 'all').length, 25)
  // Сторінки рахуються від відфільтрованого списку: 12 записів → 2 сторінки, друга — 11–12.
  const second = list.paginate(codes, 2, 10)
  assert.equal(second.pageCount, 2)
  assert.equal(list.shownLabel(second), 'Показано 11–12 з 12')
  // resetKey змінюється за будь-якої зміни фільтра (usePagination тоді повертає сторінку 1)
  // і лишається тим самим, поки фільтри не змінено.
  const keys = [['all', 'all'], ['tokens.issue', 'all'], ['all', '4'], ['all', 'none'], ['tokens.issue', '4']]
    .map(([action, cycle]) => audit.auditFilterKey(action, cycle))
  assert.equal(new Set(keys).size, keys.length)
  assert.equal(audit.auditFilterKey('all', 'all'), audit.auditFilterKey('all', 'all'))
  assert.notEqual(audit.auditFilterKey('a|b', 'c'), audit.auditFilterKey('a', 'b|c'))
})

test('a page beyond the filtered range falls back to its last page', () => {
  // Користувач був на 3-й сторінці всього журналу, а після фільтра лишилося 12 записів.
  const page = list.paginate(audit.filterAuditEvents(events, 'tokens.issue', 'all'), 3, 10)
  assert.equal(page.page, 2)
  assert.equal(page.items.length, 2)
  assert.equal(list.shownLabel(page), 'Показано 11–12 з 12')
})

const users = Array.from({ length: 23 }, (_, index) => ({
  id: index + 1, name: `Користувач ${index + 1}`, role: index === 0 ? 'admin' : 'user',
  email_masked: `u***${index + 1}@example.test`, created_at: '2026-11-01T10:00:00Z',
}))

test('users list is paginated above and below and keeps the table markup', () => {
  const markup = html(usersPanel.PaginatedUsersTable, {
    rows: users.map(usersPanel.fromListed), currentUserId: 1, busy: false,
    caption: 'Облікові записи', onRevoke: () => {},
  })
  assert.equal(count(markup, /aria-label="Сторінки облікових записів \(угорі\)"/g), 1)
  assert.equal(count(markup, /aria-label="Сторінки облікових записів \(унизу\)"/g), 1)
  assert.ok(markup.includes('Показано 1–10 з 23'))
  assert.equal(count(markup, /<th scope="row"/g), 10)
  assert.ok(markup.includes('Користувач 10<'))
  assert.ok(!markup.includes('Користувач 11<'), 'одинадцятий запис — на другій сторінці')
  assert.match(markup, /Це ви/)
  assert.ok(markup.includes('<caption class="users-panel__sr-only">Облікові записи</caption>'))
  assert.ok(markup.includes('>Завершити сесії<'))
  assert.ok(!markup.includes('Нова роль для') && !markup.includes('Змінити роль'), 'роль лише для читання')
})

test('role change history is paginated and keeps names', () => {
  const changes = Array.from({ length: 14 }, (_, index) => ({
    id: 14 - index, actor_user_id: 1, target_user_id: index + 2, old_role: 'user', new_role: 'data_officer',
    changed_at: new Date(Date.UTC(2026, 10, 20) - index * 3_600_000).toISOString(),
  }))
  const markup = html(usersPanel.RoleChangeHistory, { changes, users })
  assert.ok(markup.includes('Показано 1–10 з 14'))
  assert.ok(markup.includes('Сторінки історії змін ролей (угорі)'))
  assert.ok(markup.includes('Сторінки історії змін ролей (унизу)'))
  assert.equal(bodyRows(markup), 10)
  assert.ok(markup.includes('Користувач 11<'))
  assert.ok(!markup.includes('Користувач 12<'), 'одинадцята зміна — на другій сторінці')
  assert.match(html(usersPanel.RoleChangeHistory, { changes: [], users }), /Змін ролей ще не було/)
})
