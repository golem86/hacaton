import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { after, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** Ролі admin і data_officer у вебі не призначає й не знімає ніхто — лише власник сервера командою на сервері. */
const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-admin-server-only-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const client = await server.ssrLoadModule('/src/api/client.ts')
const users = await server.ssrLoadModule('/src/api/users.ts')
const usersPanel = await server.ssrLoadModule('/src/v2/UsersPanel.tsx')
const audit = await server.ssrLoadModule('/src/v2/AuditTrail.tsx')

const html = (type, props) => renderToStaticMarkup(React.createElement(type, props))
const count = (markup, pattern) => (markup.match(pattern) ?? []).length
const reply = (data, status = 200) => new Response(JSON.stringify(data), { status })
const HINT = 'Роль призначає власник сервера'
const SESSIONS_MESSAGE = 'Сесії іншого адміністратора завершує лише власник сервера.'

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

test('roles are read-only: no role select or change button, every row hints that the server owner assigns roles', () => {
  assert.equal(users.ROLE_SERVER_ONLY_HINT, HINT)
  const markup = html(usersPanel.UsersTable, {
    rows: rows.map(usersPanel.fromListed), currentUserId: 1, busy: false, caption: 'Облікові записи', onRevoke: () => {},
  })
  assert.equal(count(markup, /<select/g), 0)
  assert.equal(count(markup, /Змінити роль/g), 0)
  assert.equal(count(markup, new RegExp(`>${HINT}<`, 'g')), rows.length, 'підказка в кожному рядку')
  assert.equal(count(markup, new RegExp(`title="${HINT}"`, 'g')), rows.length)
  for (const label of ['Адміністратор', 'Відповідальний за коди доступу', 'Користувач']) assert.ok(markup.includes(`>${label}<`), label)
})

test('sessions: data_officer and user can be ended in the web, another admin cannot, own row points to logout-all', () => {
  const markup = html(usersPanel.UsersTable, {
    rows: rows.map(usersPanel.fromListed), currentUserId: 1, busy: false, caption: 'Облікові записи', onRevoke: () => {},
  })
  assert.equal(count(markup, />Завершити сесії</g), 2, 'оператор і користувачка')
  assert.equal(count(markup, new RegExp(SESSIONS_MESSAGE.replace('.', '\\.'), 'g')), 1, 'лише для іншого адміністратора')
  assert.match(markup, /Вийти на всіх пристроях/)
})

test('the users API module has no role-change call left', async () => {
  for (const name of ['changeUserRole', 'touchesAdminRole', 'WEB_ASSIGNABLE_ROLES', 'ROLE_CONFLICT_MESSAGE', 'SELF_ROLE_CHANGE_MESSAGE', 'isSelfChangeError']) {
    assert.equal(name in users, false, name)
  }
  for (const path of ['../src/api/users.ts', '../src/v2/UsersPanel.tsx']) {
    const source = await readFile(new URL(path, import.meta.url), 'utf8')
    assert.ok(!/\/role[`'"]/.test(source), `${path}: no POST …/role`)
    assert.ok(!/<select/.test(source), `${path}: no role select`)
  }
})

test('403 admin_role_server_only on revoke-sessions explains that only the server owner ends another admin’s sessions', async () => {
  client.setCsrfToken('session-csrf')
  for (const body of [{ detail: 'admin_role_server_only' }, { detail: { code: 'admin_role_server_only' } }, { code: 'admin_role_server_only' }]) {
    await withFetch(async () => reply(body, 403), async () => {
      await assert.rejects(users.revokeUserSessions(7), error => error.status === 403 && error.message === SESSIONS_MESSAGE)
    })
  }
  await withFetch(async () => reply({ detail: 'Недостатньо прав' }, 403), async () => {
    await assert.rejects(users.revokeUserSessions(7), error => error.status === 403 && error.message !== SESSIONS_MESSAGE)
  })
  assert.equal(users.isAdminRoleServerOnlyError({ detail: 'self_change' }), false)
})

test('role history names the server command as the actor; audit labels the server role', () => {
  const markup = html(usersPanel.RoleChangeHistory, {
    users: rows,
    changes: [{ id: 5, actor_user_id: 0, target_user_id: 4, old_role: 'user', new_role: 'data_officer', changed_at: '2026-11-20T10:00:00Z' }],
  })
  assert.ok(markup.includes(usersPanel.SERVER_ACTOR_LABEL))
  assert.ok(!markup.includes('Користувач № 0'))
  assert.match(markup, /Користувачка/)
  assert.match(markup, /Користувач → Відповідальний за коди доступу/)
  assert.equal(audit.actorRoleLabel('server'), 'Власник сервера (серверна команда)')
})

test('section explains that only the server owner assigns the admin and code-issuer roles', () => {
  const markup = html(usersPanel.default, { currentUserId: 1 })
  assert.match(markup, /Ролі адміністратора й відповідального за коди призначає лише власник сервера\./)
  assert.match(markup, /у вебі ролі не змінюються/)
  assert.match(markup, /Історія змін ролей/)
  assert.doesNotMatch(markup, /Змінити роль/)
})
