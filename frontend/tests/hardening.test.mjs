import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** V2 hardening: ролі, керування користувачами, counts_exact, suppressed, logout-all, нові коди відповідей. */
const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-hardening-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const client = await server.ssrLoadModule('/src/api/client.ts')
const auth = await server.ssrLoadModule('/src/api/auth.ts')
const users = await server.ssrLoadModule('/src/api/users.ts')
const admin = await server.ssrLoadModule('/src/api/admin.ts')
const assessments = await server.ssrLoadModule('/src/api/assessments.ts')
const nav = await server.ssrLoadModule('/src/v2/navigation.ts')
const suppression = await server.ssrLoadModule('/src/dashboard/suppression.tsx')
const { getAssessmentResults } = await server.ssrLoadModule('/src/dashboard/results.ts')
const { DashboardSummary } = await server.ssrLoadModule('/src/dashboard/DashboardSummary.tsx')
const participation = await server.ssrLoadModule('/src/components/Participation.tsx')
const issuer = await server.ssrLoadModule('/src/components/AccessCodeIssuer.tsx')
const manager = await server.ssrLoadModule('/src/components/AssessmentManager.tsx')
const usersPanel = await server.ssrLoadModule('/src/v2/UsersPanel.tsx')
const officer = await server.ssrLoadModule('/src/v2/DataOfficerPanel.tsx')
const { AccountMenu } = await server.ssrLoadModule('/src/v2/AccountMenu.tsx')

const html = element => renderToStaticMarkup(element)
const reply = (data, status = 200) => new Response(data === undefined ? null : JSON.stringify(data), { status })

async function withFetch(handler, run) {
  const previous = globalThis.fetch
  globalThis.fetch = handler
  try { await run() } finally { globalThis.fetch = previous }
}

function recorder(route) {
  const calls = []
  const handler = async (url, options = {}) => {
    const headers = new Headers(options.headers)
    calls.push({ url, method: options.method ?? 'GET', credentials: options.credentials, csrf: headers.get('X-CSRF-Token'), body: options.body === undefined ? undefined : JSON.parse(options.body) })
    return route(url, options)
  }
  return { calls, handler }
}

// ---------------------------------------------------------------------------- навігація за ролями

test('data_officer menu has codes, participation and Annex V data entry — no results, analytics, audit, reports or tracker', () => {
  const items = nav.navigationFor('data_officer')
  assert.deepEqual(items.map(item => item.key), ['codes', 'participation', 'checklist', 'objective'])
  assert.ok(items.every(item => item.path.startsWith('/officer/')))
  const titles = items.map(item => item.title).join(' | ')
  for (const forbidden of [/Огляд/, /Аналітика/, /Журнал/, /Звіти/, /Трекер/, /Результати/, /Користувачі/]) assert.doesNotMatch(titles, forbidden)
  assert.equal(nav.homePathFor('data_officer'), '/officer')
  assert.equal(nav.PANEL_TEXT.data_officer.overline, 'ВІДПОВІДАЛЬНИЙ ЗА КОДИ ДОСТУПУ')
})

test('admin menu gains «Користувачі й ролі»; user menu stays personal', () => {
  const adminItems = nav.navigationFor('admin')
  assert.deepEqual(adminItems.find(item => item.key === 'users'), { key: 'users', title: 'Користувачі й ролі', path: '/admin/users' })
  for (const key of ['overview', 'analytics', 'tracker', 'testing', 'audit', 'reports']) assert.ok(adminItems.some(item => item.key === key), key)
  const userItems = nav.navigationFor('user')
  assert.ok(userItems.every(item => item.path.startsWith('/app/')))
  assert.ok(!userItems.some(item => ['users', 'codes', 'audit'].includes(item.key)))
})

test('routes map to the right cabinet and fall back to its first section', () => {
  assert.deepEqual(nav.routeFromPath('/officer/participation'), { role: 'data_officer', section: 'participation' })
  assert.deepEqual(nav.routeFromPath('/officer'), { role: 'data_officer', section: 'codes' })
  assert.deepEqual(nav.routeFromPath('/officer/analytics'), { role: 'data_officer', section: 'codes' })
  assert.deepEqual(nav.routeFromPath('/admin/users'), { role: 'admin', section: 'users' })
  assert.deepEqual(nav.routeFromPath('/admin/codes'), { role: 'admin', section: 'overview' })
  assert.deepEqual(nav.routeFromPath('/app/stats'), { role: 'user', section: 'stats' })
  assert.equal(nav.sectionTitle({ role: 'data_officer', section: 'participation' }), 'Участь')
})

test('role labels cover the new role and unknown roles stay raw', () => {
  assert.equal(auth.roleLabel('data_officer'), 'Відповідальний за коди доступу')
  assert.equal(auth.roleLabel('admin'), 'Адміністратор')
  assert.equal(auth.roleLabel('robot'), 'robot')
  assert.deepEqual([...auth.USER_ROLES], ['user', 'admin', 'data_officer'])
  assert.equal(auth.isUserRole('data_officer'), true)
  assert.equal(auth.isUserRole('auditor'), false)
})

test('account menu offers «Вийти на всіх пристроях» for every role', () => {
  for (const role of ['user', 'admin', 'data_officer']) {
    const markup = html(createElement(AccountMenu, { user: { name: 'Тест', email: 'test@example.test', role }, onLogout: () => {}, onLogoutAll: async () => {} }))
    assert.match(markup, />Вийти на всіх пристроях</)
    assert.match(markup, />Вийти</)
    assert.ok(markup.includes(auth.roleLabel(role)))
  }
})

// ---------------------------------------------------------------------------- auth: logout-all, 429, 401

test('logout-all posts with session CSRF; an already finished session counts as logged out', async () => {
  client.setCsrfToken('session-csrf')
  const { calls, handler } = recorder(() => reply({ status: 'logged_out_all' }))
  await withFetch(handler, async () => {
    assert.deepEqual(await auth.logoutAllSessions(), { status: 'logged_out_all' })
  })
  assert.deepEqual(calls.map(call => [call.method, call.url, call.credentials, call.csrf]), [['POST', '/v2/auth/logout-all', 'include', 'session-csrf']])
  await withFetch(async () => reply({ detail: 'Потрібен вхід до системи' }, 401), async () => {
    assert.deepEqual(await auth.logoutAllSessions(), { status: 'logged_out_all' })
  })
  await withFetch(async () => reply({}, 500), async () => {
    await assert.rejects(auth.logoutAllSessions(), error => error.status === 500)
  })
})

test('2FA lockout (429) on verify and resend shows the lockout message', async () => {
  client.setCsrfToken('pending-csrf')
  await withFetch(async () => reply({ detail: 'Too many' }, 429), async () => {
    await assert.rejects(auth.verifyTwoFactor('123456'), error => error.status === 429 && error.message === auth.TWO_FACTOR_LOCKOUT_MESSAGE)
    await assert.rejects(auth.resendTwoFactor(), error => error.status === 429 && error.message === auth.TWO_FACTOR_LOCKOUT_MESSAGE)
  })
  assert.match(auth.TWO_FACTOR_LOCKOUT_MESSAGE, /^Забагато невдалих спроб коду\. Спробуйте пізніше або зверніться до адміністратора/)
})

test('413 says «Запит завеликий» and 422 never echoes validation details', async () => {
  client.setCsrfToken('session-csrf')
  await withFetch(async () => new Response('too large', { status: 413 }), async () => {
    await assert.rejects(auth.loginUser({ email: 'a@example.test', password: 'x'.repeat(12) }), error => error.status === 413 && /^Запит завеликий/.test(error.message))
    await assert.rejects(admin.createCycle({ name: 'x' }), error => error.status === 413 && /^Запит завеликий/.test(error.message))
    await assert.rejects(users.changeUserRole(5, 'user', 'admin'), error => error.status === 413 && /^Запит завеликий/.test(error.message))
  })
  await withFetch(async () => reply({ detail: [{ loc: ['body', 'name'], msg: 'bad', type: 'x' }] }, 422), async () => {
    await assert.rejects(admin.createCycle({ name: 'secret-input' }), error => error.status === 422 && !/secret-input|loc|msg/.test(error.message))
  })
  assert.equal(client.statusMessage(413), client.PAYLOAD_TOO_LARGE_MESSAGE)
  assert.equal(client.statusMessage(401), 'Сесію завершено, увійдіть знову.')
})

test('anonymous survey treats 413 and 429 as definitely not accepted', async () => {
  for (const status of [413, 429]) {
    await withFetch(async () => new Response('', { status }), async () => {
      await assert.rejects(assessments.submitQuestionnaire(1, { token: 't', respondent_category: 'cadets', unit: 'U', answers: [] }), error => {
        assert.equal(error instanceof assessments.SubmissionOutcomeUnknownError, false)
        return /Анкету не надіслано/.test(error.message)
      })
    })
  }
})

test('401 on a protected route (revoked session, changed role) raises the session-expired event', async () => {
  const saved = globalThis.window
  const events = []
  globalThis.window = { dispatchEvent: event => events.push(event.type) }
  try {
    await withFetch(async () => reply({ detail: 'Потрібен вхід до системи' }, 401), async () => {
      await assert.rejects(users.listUsers(), error => error.status === 401 && error.message === 'Сесію завершено, увійдіть знову.')
      await assert.rejects(admin.getParticipation(3), error => error.status === 401)
      await assert.rejects(auth.getCurrentUser(), error => error.status === 401)
    })
  } finally {
    if (saved === undefined) delete globalThis.window
    else globalThis.window = saved
  }
  assert.deepEqual(events, ['v2-session-expired', 'v2-session-expired'], '/v2/auth/* never raises the event')
})

// ---------------------------------------------------------------------------- керування користувачами (admin)

const listed = [
  { id: 1, name: 'Адмін', role: 'admin', email_masked: 'a***@example.test', created_at: '2026-11-01T08:00:00Z' },
  { id: 2, name: 'Оператор кодів', role: 'data_officer', email_masked: 'o***@example.test', created_at: '2026-11-02T08:00:00Z' },
  { id: 3, name: 'Користувач', role: 'user', email_masked: 'u***@example.test', created_at: '2026-11-03T08:00:00Z' },
]

test('users API: list, exact email search, role change with expected_role, revoke sessions, history', async () => {
  client.setCsrfToken('session-csrf')
  const { calls, handler } = recorder((url, options) => {
    if (url === '/v2/admin/users') return reply(listed)
    if (url === '/v2/admin/users/lookup') return JSON.parse(options.body).email.startsWith('missing') ? reply({ detail: 'Not found' }, 404) : reply({ id: 3, name: 'Користувач', email: 'user+qa@example.test', role: 'user', created_at: '2026-11-03T08:00:00Z' })
    if (url.endsWith('/role')) return reply({ id: 3, role: 'data_officer' })
    if (url.endsWith('/revoke-sessions')) return reply({ revoked: 2 })
    if (url === '/v2/admin/role-changes') return reply([{ id: 9, actor_user_id: 1, target_user_id: 3, old_role: 'user', new_role: 'data_officer', changed_at: '2026-11-20T10:00:00Z' }])
    return reply({}, 500)
  })
  await withFetch(handler, async () => {
    assert.equal((await users.listUsers()).length, 3)
    assert.equal((await users.findUserByEmail(' user+qa@example.test ')).email, 'user+qa@example.test')
    assert.equal(await users.findUserByEmail('missing@example.test'), null)
    await users.changeUserRole(3, 'user', 'data_officer')
    assert.equal(await users.revokeUserSessions(3), 2)
    assert.equal((await users.getRoleChanges())[0].new_role, 'data_officer')
  })
  assert.deepEqual(calls.map(call => [call.method, call.url]), [
    ['GET', '/v2/admin/users'],
    ['POST', '/v2/admin/users/lookup'],
    ['POST', '/v2/admin/users/lookup'],
    ['POST', '/v2/admin/users/3/role'],
    ['POST', '/v2/admin/users/3/revoke-sessions'],
    ['GET', '/v2/admin/role-changes'],
  ])
  // Email іде лише в JSON-тілі lookup (обрізаний), ніколи в URL.
  assert.deepEqual(calls[1].body, { email: 'user+qa@example.test' })
  assert.deepEqual(calls[2].body, { email: 'missing@example.test' })
  assert.ok(calls.every(call => !/email|%40|@/.test(call.url)), 'no email in any URL')
  assert.deepEqual(calls[3].body, { expected_role: 'user', new_role: 'data_officer' })
  assert.ok(calls.every(call => call.credentials === 'include'))
  assert.ok(calls.filter(call => call.method === 'POST').every(call => call.csrf === 'session-csrf'))
  assert.ok(calls.filter(call => call.method === 'GET').every(call => call.csrf === null))
})

test('role change errors: 403 self_change, other 403, 409 conflict, 404 missing', async () => {
  client.setCsrfToken('session-csrf')
  const cases = [
    [reply({ detail: 'self_change' }, 403), 403, /^Не можна змінити власну роль/],
    [reply({ detail: { code: 'self_change', message: 'x' } }, 403), 403, /^Не можна змінити власну роль/],
    [reply({ code: 'self_change' }, 403), 403, /^Не можна змінити власну роль/],
    [reply({ detail: 'Недостатньо прав' }, 403), 403, /Недостатньо прав для зміни ролей/],
    [reply({ detail: 'expected_role mismatch' }, 409), 409, /^Роль уже змінена іншим адміністратором, оновіть список/],
    [reply({ detail: 'Not found' }, 404), 404, /^Користувача не знайдено/],
  ]
  for (const [response, status, message] of cases) {
    await withFetch(async () => response.clone(), async () => {
      await assert.rejects(users.changeUserRole(1, 'admin', 'user'), error => error.status === status && message.test(error.message))
    })
  }
  await assert.rejects(users.changeUserRole(1, 'admin', 'root'), error => error.status === 422)
})

test('users table: masked email only, own row cannot change its role, others get role select and actions', () => {
  const markup = html(createElement(usersPanel.UsersTable, {
    rows: listed.map(usersPanel.fromListed), currentUserId: 1, drafts: {}, busy: false, caption: 'Облікові записи',
    onDraft: () => {}, onRequest: () => {},
  }))
  assert.match(markup, /a\*\*\*@example\.test/)
  assert.doesNotMatch(markup, /user\+qa@example\.test/)
  assert.match(markup, /Це ви/)
  assert.match(markup, /Не можна змінити власну роль/)
  assert.equal(markup.match(/>Змінити роль</g)?.length, 2, 'two other accounts')
  assert.equal(markup.match(/>Завершити сесії</g)?.length, 2)
  for (const label of ['Користувач', 'Адміністратор', 'Відповідальний за коди доступу']) assert.ok(markup.includes(`>${label}</option>`), label)
})

test('confirmation explains the effect before a role change or a session revoke', () => {
  const user = usersPanel.fromListed(listed[2])
  const role = html(createElement(usersPanel.ConfirmAction, { action: { kind: 'role', user, newRole: 'data_officer' }, busy: false, onConfirm: () => {}, onCancel: () => {} }))
  assert.match(role, /role="alertdialog"/)
  assert.match(role, /з «Користувач» на «Відповідальний за коди доступу»/)
  assert.match(role, /Усі сесії цього користувача буде завершено/)
  const revoke = html(createElement(usersPanel.ConfirmAction, { action: { kind: 'revoke', user }, busy: false, onConfirm: () => {}, onCancel: () => {} }))
  assert.match(revoke, /Завершити всі сесії користувача «Користувач»/)
  assert.equal(usersPanel.sessionsLabel(1), '1 сесію')
  assert.equal(usersPanel.sessionsLabel(3), '3 сесії')
  assert.equal(usersPanel.sessionsLabel(5), '5 сесій')
})

test('role change history names known accounts and keeps unknown ids', () => {
  const markup = html(createElement(usersPanel.RoleChangeHistory, {
    users: listed,
    changes: [
      { id: 2, actor_user_id: 1, target_user_id: 3, old_role: 'user', new_role: 'data_officer', changed_at: '2026-11-20T10:00:00Z' },
      { id: 1, actor_user_id: 1, target_user_id: 77, old_role: 'admin', new_role: 'user', changed_at: '2026-11-19T10:00:00Z' },
    ],
  }))
  assert.match(markup, /Адмін/)
  assert.match(markup, /Користувач → Відповідальний за коди доступу/)
  assert.match(markup, /Користувач № 77/)
  assert.match(html(createElement(usersPanel.RoleChangeHistory, { users: [], changes: [] })), /Змін ролей ще не було/)
})

// ---------------------------------------------------------------------------- коди доступу (data_officer) і admin

test('token issuance sends count, category and expiry; 403 explains that only data_officer issues codes', async () => {
  client.setCsrfToken('officer-csrf')
  const { calls, handler } = recorder(() => reply({ tokens: ['a'.repeat(32)] }, 201))
  await withFetch(handler, async () => {
    assert.deepEqual(await admin.issueAccessTokens(4, 25, 'staff', 30), { tokens: ['a'.repeat(32)] })
  })
  assert.equal(calls[0].url, '/api/assessments/4/tokens?count=25&category=staff&expires_days=30')
  assert.equal(calls[0].csrf, 'officer-csrf')
  await withFetch(async () => reply({ detail: 'Недостатньо прав для цієї дії' }, 403), async () => {
    await assert.rejects(admin.issueAccessTokens(4, 1, 'staff'), error => error.status === 403 && /data_officer/.test(error.message))
  })
})

test('admin cycle manager no longer issues codes and explains who does', async () => {
  const source = await readFile(new URL('../src/components/AssessmentManager.tsx', import.meta.url), 'utf8')
  assert.ok(!source.includes('issueAccessTokens'), 'admin UI has no token issuance call')
  const markup = html(createElement(manager.default))
  assert.doesNotMatch(markup, />Видати коди</)
  const note = html(createElement(manager.CodesDelegatedNote))
  assert.match(note, /Коди видає Відповідальний за коди доступу \(роль data_officer\)/)
})

const openCycle = { id: 7, name: 'Весна 2027', start_date: '2027-03-01', status: 'open', min_group_size: 5, categories: ['cadets', 'staff'] }
const issued = { assessmentId: 7, assessmentName: 'Весна 2027', category: 'staff', expiresDays: 14, issuedAt: '2027-03-02T09:30:00.000Z', tokens: ['0123456789abcdef0123456789abcdef', 'fedcba9876543210fedcba9876543210'] }

test('code issuer form has category, count and expiry; codes are shown once with download, print and a warning', () => {
  const form = html(createElement(issuer.AccessCodeIssuer, { cycle: openCycle, issued: null, onIssued: () => {}, onDismiss: () => {} }))
  for (const label of ['Категорія кодів', 'Кількість кодів', 'Строк дії, днів', '>Видати коди<', 'Коди буде показано лише один раз']) assert.ok(form.includes(label), label)
  assert.match(form, /value="14"/)
  assert.match(form, /<option value="cadets"[^>]*>Курсанти<\/option><option value="staff"[^>]*>Працівники<\/option>/)

  const shown = html(createElement(issuer.AccessCodeIssuer, { cycle: openCycle, issued, onIssued: () => {}, onDismiss: () => {} }))
  assert.ok(shown.includes(issuer.ONE_TIME_WARNING))
  assert.match(shown, /повторно показати ці коди неможливо/)
  assert.match(shown, /<textarea[^>]*readOnly=""/i)
  assert.ok(shown.includes('0123456789abcdef0123456789abcdef'))
  for (const label of ['Завантажити файл .txt', 'Надрукувати', 'Сховати коди']) assert.ok(shown.includes(label), label)
  assert.match(shown, /<button class="v2-button v2-button-primary" disabled="" type="submit">Видати коди<\/button>/, 'no new issuance while codes are on screen')

  const closed = html(createElement(issuer.AccessCodeIssuer, { cycle: { ...openCycle, status: 'closed' }, issued: null, onIssued: () => {}, onDismiss: () => {} }))
  assert.match(closed, /лише для відкритого циклу/)
})

test('codes file has a header and one code per line; its name carries no personal data', () => {
  const text = issuer.codesFileText(issued)
  const lines = text.split('\r\n')
  assert.ok(lines.includes('0123456789abcdef0123456789abcdef'))
  assert.ok(lines.includes('fedcba9876543210fedcba9876543210'))
  assert.match(text, /Категорія: Працівники/)
  assert.match(text, /Строк дії: 14 дн\./)
  assert.equal(issuer.codesFileName(issued), 'access-codes-cycle-7-staff-202703020930.txt')
  assert.equal(issuer.validateIssueInput(10, 14), '')
  assert.match(issuer.validateIssueInput(0, 14), /від 1 до 500/)
  assert.match(issuer.validateIssueInput(501, 14), /від 1 до 500/)
  assert.match(issuer.validateIssueInput(10, 366), /від 1 до 365/)
  assert.match(issuer.validateIssueInput(1.5, 14), /ціле число/)
})

test('data officer cabinet lists only open cycles and locks switching while codes are shown', () => {
  const cycles = [openCycle, { ...openCycle, id: 8, name: 'Закритий', status: 'closed' }, { ...openCycle, id: 9, name: 'Ще відкритий' }]
  const markup = html(createElement(officer.OpenCyclesList, { cycles, selectedId: 7, locked: true, onSelect: () => {} }))
  assert.match(markup, /Весна 2027/)
  assert.match(markup, /Ще відкритий/)
  assert.doesNotMatch(markup, /Закритий/)
  assert.match(markup, /aria-pressed="false" disabled=""/)
  assert.match(html(createElement(officer.OpenCyclesList, { cycles: [cycles[1]], selectedId: null, locked: false, onSelect: () => {} })), /Відкритих циклів немає/)
  assert.match(officer.OFFICER_SCOPE_NOTE, /Результати, аналітика, журнал дій, звіти й трекер для цієї ролі недоступні/)
})

// ---------------------------------------------------------------------------- участь: counts_exact і suppressed

test('participation is normalized: counts_exact, legacy hidden groups dropped, by_unit query', async () => {
  const open = admin.normalizeParticipation({ status: 'open', tokens_issued: 40, tokens_unused: 15, responses_total: 25, participation_percent: 62.5, counts_exact: false, groups: null })
  assert.equal(open.counts_exact, false)
  assert.equal(open.suppressed, false)
  const legacy = admin.normalizeParticipation({ status: 'closed', tokens_issued: 40, tokens_unused: 10, responses_total: 30, participation_percent: 75,
    groups: [{ category: 'cadets', responses: 26, hidden: false }, { category: 'staff', responses: null, hidden: true }] })
  assert.equal(legacy.counts_exact, true, 'old backend without the flag was exact')
  assert.deepEqual(legacy.groups, [{ category: 'cadets', responses: 26 }])
  assert.equal(legacy.suppressed, true)
  const flagged = admin.normalizeParticipation({ status: 'closed', tokens_issued: 40, tokens_unused: 10, responses_total: 30, participation_percent: 75, counts_exact: true,
    groups: [{ category: 'cadets', unit: 'Кафедра 1', responses: 12 }], suppressed: true })
  assert.equal(flagged.suppressed, true)
  assert.equal(flagged.groups[0].unit, 'Кафедра 1')
  const { calls, handler } = recorder(() => reply({ status: 'closed', tokens_issued: 1, tokens_unused: null, responses_total: null, participation_percent: null, counts_exact: true, groups: null, suppressed: false }))
  await withFetch(handler, async () => { await admin.getParticipation(5, { byUnit: true }) })
  assert.equal(calls[0].url, '/api/assessments/5/participation?by_unit=true')
})

test('open cycle shows «≥ N» with an explanation and no chart; closed cycle shows exact numbers', () => {
  assert.equal(participation.formatParticipationCount(null, false), 'приховано')
  assert.equal(participation.formatParticipationCount(25, false), '≥ 25')
  assert.equal(participation.formatParticipationCount(1250, true), (1250).toLocaleString('uk-UA'))
  assert.equal(participation.formatParticipationPercent(62.5, false), `≈ ${(62.5).toLocaleString('uk-UA')}%`)

  const open = admin.normalizeParticipation({ status: 'open', tokens_issued: 40, tokens_unused: 15, responses_total: 25, participation_percent: 62.5, counts_exact: false, groups: null })
  const openMarkup = html(createElement(participation.ParticipationView, { participation: open, cycle: { status: 'open', min_group_size: 5 } }))
  assert.match(openMarkup, /Приблизні значення/)
  assert.match(openMarkup, /округлено вниз до кратного 5 і показано лише від порогу групи \(5\)/)
  assert.match(openMarkup, /Анкет:<\/dt> <dd>≥ 25<\/dd>/)
  assert.match(openMarkup, /Невикористаних:<\/dt> <dd>≥ 15<\/dd>/)
  assert.match(openMarkup, /Видано кодів:<\/dt> <dd>40<\/dd>/)
  assert.ok(!openMarkup.includes('<canvas'), 'rounded values are not drawn as an exact split')
  assert.match(openMarkup, /після закриття циклу/)

  const closed = admin.normalizeParticipation({ status: 'closed', tokens_issued: 40, tokens_unused: 10, responses_total: 30, participation_percent: 75, counts_exact: true,
    groups: [{ category: 'cadets', responses: 26 }], suppressed: true })
  const closedMarkup = html(createElement(participation.ParticipationView, { participation: closed, cycle: { status: 'closed', min_group_size: 5 } }))
  assert.match(closedMarkup, /Анкет:<\/dt> <dd>30<\/dd>/)
  assert.doesNotMatch(closedMarkup, /≥|Приблизні значення/)
  assert.match(closedMarkup, /показано точні значення/)
  assert.match(closedMarkup, /Курсанти/)
  assert.doesNotMatch(closedMarkup, /Працівники/)
  assert.match(closedMarkup, /Частину груп приховано для захисту анонімності \(менше 5 відповідей\)/)
  assert.ok(closedMarkup.includes('<canvas'))
})

// ---------------------------------------------------------------------------- результати: suppressed

const newResults = {
  assessment: { id: 2, name: 'Cycle 2', status: 'closed' }, min_group_size: 6, responses_total: 40, suppressed: true,
  categories: [{ category: 'cadets', responses: 30 }],
  components: [{ code: 'C1', name: 'Компонент', weight: 1, score: 70, suppressed: true, by_category: [{ category: 'cadets', score: 71 }], objective_indicators: [] }],
}

test('results keep the new suppressed flag and drop legacy hidden entries with their names', async () => {
  const normalized = suppression.normalizeResults(newResults)
  assert.equal(normalized.suppressed, true)
  assert.equal(normalized.components[0].suppressed, true)
  const legacy = suppression.normalizeResults({
    assessment: { id: 1, name: 'Cycle 1', status: 'closed' }, min_group_size: 5, responses_total: 40,
    categories: [{ category: 'cadets', responses: 30, hidden: false }, { category: 'staff', responses: null, hidden: true }],
    components: [{ code: 'C1', name: 'К', weight: 1, score: 60, by_category: [{ category: 'cadets', score: 61, hidden: false }, { category: 'staff', score: 12.3, hidden: false }], objective_indicators: [] }],
  })
  assert.deepEqual(legacy.categories, [{ category: 'cadets', responses: 30 }])
  assert.deepEqual(legacy.components[0].by_category, [{ category: 'cadets', score: 61 }], 'a cell of a hidden category is dropped too')
  assert.equal(legacy.suppressed, true)
  const clean = suppression.normalizeResults({ ...newResults, suppressed: false, components: [{ ...newResults.components[0], suppressed: false }] })
  assert.equal(clean.suppressed, false)
  assert.equal(suppression.suppressionNoteText(6), 'Частину груп приховано для захисту анонімності (менше 6 відповідей).')
  assert.equal(suppression.suppressionNoteText(), 'Частину груп приховано для захисту анонімності (менше k відповідей).')

  await withFetch(async () => reply(newResults), async () => {
    const results = await getAssessmentResults(2)
    assert.equal(results.suppressed, true)
  })
  const summary = html(createElement(DashboardSummary, { results: suppression.normalizeResults(newResults) }))
  assert.match(summary, /Показаних категорій/)
  assert.match(summary, /менше 6 відповідей/)
})

// ---------------------------------------------------------------------------- цикли з сесією і CSP

test('admin and data officer read cycles with the session; the anonymous survey list stays cookie-free', async () => {
  const { calls, handler } = recorder(() => reply([{ id: 1, name: 'Чернетка', start_date: '2026-11-16', status: 'draft', min_group_size: 5 }]))
  await withFetch(handler, async () => {
    assert.equal((await assessments.getManagedAssessments())[0].status, 'draft')
    await assessments.getAssessments()
  })
  assert.deepEqual(calls.map(call => call.credentials), ['include', 'omit'])
  for (const file of ['../src/main.tsx', '../src/components/AssessmentManager.tsx', '../src/v2/ReportsPanel.tsx', '../src/v2/TrackerPanel.tsx', '../src/v2/DataOfficerPanel.tsx']) {
    const source = await readFile(new URL(file, import.meta.url), 'utf8')
    assert.ok(source.includes('getManagedAssessments'), file)
  }
})

async function sourceFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  const nested = await Promise.all(entries.map(entry => entry.isDirectory() ? sourceFiles(new URL(`${entry.name}/`, dir)) : [new URL(entry.name, dir)]))
  return nested.flat().filter(url => /\.(tsx?|css)$/.test(url.pathname))
}

test('strict CSP: no inline script or style in index.html, no eval / new Function in sources', async () => {
  const index = await readFile(new URL('../index.html', import.meta.url), 'utf8')
  assert.doesNotMatch(index, /<script(?![^>]*\bsrc=)[^>]*>/i, 'every script has src')
  assert.doesNotMatch(index, /<style|\sstyle=|\son[a-z]+=/i)
  for (const file of await sourceFiles(new URL('../src/', import.meta.url))) {
    const source = await readFile(file, 'utf8')
    assert.doesNotMatch(source, /\beval\s*\(|new\s+Function\s*\(|dangerouslySetInnerHTML|innerHTML\s*=/, file.pathname)
  }
})
