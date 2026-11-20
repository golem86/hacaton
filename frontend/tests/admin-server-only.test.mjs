import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** Роль admin у вебі не призначає й не знімає ніхто — лише власник сервера командою на сервері. */
const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-admin-server-only-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const client = await server.ssrLoadModule('/src/api/client.ts')
const users = await server.ssrLoadModule('/src/api/users.ts')
const usersPanel = await server.ssrLoadModule('/src/v2/UsersPanel.tsx')
const audit = await server.ssrLoadModule('/src/v2/AuditTrail.tsx')

const html = (type, props) => renderToStaticMarkup(React.createElement(type, props))
const count = (markup, pattern) => (markup.match(pattern) ?? []).length
const reply = (data, status = 200) => new Response(JSON.stringify(data), { status })
const MESSAGE = 'Роль адміністратора призначає й знімає лише власник сервера.'

async function withFetch(handler, run) {
  const previous = globalThis.fetch
  globalThis.fetch = handler
  try { await run() } finally { globalThis.fetch = previous }
}

const rows = [
  { id: 1, name: 'Я', role: 'admin', email_masked: 'm***@example.test', created_at: '2026-11-01T08:00:00Z' },
  { id: 2, name: 'Інший адмін', role: 'admin', email_masked: 'a***@example.test', created_at: '2026-11-02T08:00:00Z' },
  { id: 3, name: 'Оператор', role: 'data_officer', email_masked: 'o***@example.test', created_at: '2026-11-03T08:00:00Z' },
  { id: 4, name: 'Користувачка', role: 'user', email_masked: 'u***@example.test', created_at: '2026-11-04T08:00:00Z' },
].map(row => ({ ...row }))

test('role select has no «Адміністратор»; admin rows show the server-only note instead of actions', () => {
  assert.equal(users.ADMIN_ROLE_SERVER_ONLY_MESSAGE, MESSAGE)
  assert.deepEqual([...users.WEB_ASSIGNABLE_ROLES], ['user', 'data_officer'])
  const markup = html(usersPanel.UsersTable, {
    rows: rows.map(usersPanel.fromListed), currentUserId: 1, drafts: {}, busy: false, caption: 'Облікові записи',
    onDraft: () => {}, onRequest: () => {},
  })
  assert.ok(!markup.includes('>Адміністратор</option>'))
  assert.equal(count(markup, /<select/g), 2, 'лише оператор і користувачка')
  assert.equal(count(markup, />Змінити роль</g), 2)
  assert.equal(count(markup, />Завершити сесії</g), 2, 'сесії іншого адміністратора у вебі не завершуються')
  assert.equal(count(markup, new RegExp(MESSAGE.replace('.', '\\.'), 'g')), 1, 'нотатка лише для іншого адміністратора')
  assert.ok(!markup.includes('Нова роль для Інший адмін'))
  assert.match(markup, /Не можна змінити власну роль/)
})

test('changeUserRole never sends a request that grants or removes admin', async () => {
  client.setCsrfToken('session-csrf')
  let calls = 0
  await withFetch(async () => { calls += 1; return reply({}) }, async () => {
    for (const [expected, next] of [['user', 'admin'], ['data_officer', 'admin'], ['admin', 'user'], ['admin', 'data_officer']]) {
      await assert.rejects(users.changeUserRole(7, expected, next), error => error.status === 403 && error.message === MESSAGE)
    }
  })
  assert.equal(calls, 0)
  assert.equal(users.touchesAdminRole('user', 'data_officer'), false)
})

test('403 admin_role_server_only from the server gets the same message for role change and revoke', async () => {
  client.setCsrfToken('session-csrf')
  for (const body of [{ detail: 'admin_role_server_only' }, { detail: { code: 'admin_role_server_only' } }, { code: 'admin_role_server_only' }]) {
    await withFetch(async () => reply(body, 403), async () => {
      await assert.rejects(users.changeUserRole(7, 'user', 'data_officer'), error => error.status === 403 && error.message === MESSAGE)
      await assert.rejects(users.revokeUserSessions(7), error => error.status === 403 && error.message === MESSAGE)
    })
  }
  await withFetch(async () => reply({ detail: 'Недостатньо прав' }, 403), async () => {
    await assert.rejects(users.revokeUserSessions(7), error => error.status === 403 && error.message !== MESSAGE)
  })
  assert.equal(users.isAdminRoleServerOnlyError({ detail: 'self_change' }), false)
})

test('role history names the server command as the actor; audit labels the server role', () => {
  const markup = html(usersPanel.RoleChangeHistory, {
    users: rows,
    changes: [{ id: 5, actor_user_id: 0, target_user_id: 4, old_role: 'user', new_role: 'admin', changed_at: '2026-11-20T10:00:00Z' }],
  })
  assert.ok(markup.includes(usersPanel.SERVER_ACTOR_LABEL))
  assert.ok(!markup.includes('Користувач № 0'))
  assert.match(markup, /Користувачка/)
  assert.equal(audit.actorRoleLabel('server'), 'Власник сервера (серверна команда)')
})

test('section explains that only the server owner assigns the admin role', () => {
  const markup = html(usersPanel.default, { currentUserId: 1 })
  assert.match(markup, /Роль адміністратора\s+призначає й знімає лише власник сервера командою на сервері/)
  assert.match(markup, /лише ролі «Користувач» і «Відповідальний за коди доступу»/)
})
