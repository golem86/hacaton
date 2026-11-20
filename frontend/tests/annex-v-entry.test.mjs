import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** «Зрілість за Додатком В»: внесення даних (анкети, експерт, чеклист Додатка Б, об’єктивні показники). */
const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-annex-v-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const client = await server.ssrLoadModule('/src/api/client.ts')
const api = await server.ssrLoadModule('/src/api/annexV.ts')
const validation = await server.ssrLoadModule('/src/official/validation.ts')
const { getOfficialTemplate } = await server.ssrLoadModule('/src/official/catalog.ts')
const catalogV2 = await server.ssrLoadModule('/src/official/catalog-v2.ts')
const official = await server.ssrLoadModule('/src/official/OfficialAssessment.tsx')
const checklist = await server.ssrLoadModule('/src/v2/ChecklistPanel.tsx')
const indicators = await server.ssrLoadModule('/src/v2/ObjectiveIndicatorsPanel.tsx')
const nav = await server.ssrLoadModule('/src/v2/navigation.ts')

const html = element => renderToStaticMarkup(element)
const reply = (data, status = 200) => new Response(data === undefined ? null : JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
const noop = () => {}

async function withFetch(handler, run) {
  const previous = globalThis.fetch
  globalThis.fetch = handler
  try { await run() } finally { globalThis.fetch = previous }
}
function recorder(route) {
  const calls = []
  const handler = async (url, options = {}) => {
    const headers = new Headers(options.headers)
    calls.push({ url, method: options.method ?? 'GET', credentials: options.credentials, csrf: headers.get('X-CSRF-Token'), headers, body: options.body === undefined ? undefined : JSON.parse(options.body) })
    return route(url, options)
  }
  return { calls, handler }
}

const fullAnswers = form => Object.fromEntries(getOfficialTemplate(`appendix-v-form-${form}`, '2.0.0').questions.map(q => [q.id, q.options[0].id]))
const item = (overrides = {}) => ({
  code: 'B-1.1', criterion: 'ethics', text: 'Затверджено кодекс етики', source: 'Додаток Б (адаптовано)', status: null, evidence: null,
  entered_role: null, entered_at: null, confirmed: false, confirmed_role: null, confirmed_at: null, ...overrides,
})
const indicator = (overrides = {}) => ({ id: 3, criterion: 'education', name: 'Охоплення навчанням', unit: '%', value: 72, target: 90, period: '2026', entered_role: 'data_officer', confirmed: false, confirmed_role: null, ...overrides })
const cycle = (id, status, extra = {}) => ({ id, name: `Цикл ${id}`, start_date: `2026-0${id}-01`, status, min_group_size: 5, ...extra })

// ---------------------------------------------------------------- API

test('anonymous response: exact path, POST, no cookie, no CSRF, access code only in the JSON body', async () => {
  client.setCsrfToken('csrf-secret')
  const answers = fullAnswers(2)
  const { calls, handler } = recorder(() => reply({ status: 'accepted' }, 201))
  await withFetch(handler, async () => {
    const result = await api.submitAnnexVResponse(7, { access_token: 'abc123def', category: 'staff', form: 2, version: '2.0.0', answers })
    assert.deepEqual(result, { status: 'accepted' })
  })
  assert.equal(calls.length, 1)
  const [call] = calls
  assert.equal(call.url, '/api/assessments/7/annex-v/responses')
  assert.equal(call.method, 'POST')
  assert.equal(call.credentials, 'omit')
  assert.equal(call.csrf, null)
  assert.ok(!call.url.includes('abc123def'))
  assert.ok(![...call.headers.values()].some(value => value.includes('abc123def')))
  assert.deepEqual(call.body, { access_token: 'abc123def', category: 'staff', form: 2, version: '2.0.0', answers })
  assert.equal(Object.keys(call.body.answers).length, 10)
})

test('anonymous response maps 409/422 to Ukrainian messages without echoing the server detail', async () => {
  for (const [status, pattern] of [[409, /закрито або цей код доступу вже використано/], [422, /перевірте код доступу/], [429, /Забагато спроб/]]) {
    await withFetch(async () => reply({ detail: 'secret-code-xyz is used' }, status), async () => {
      await assert.rejects(api.submitAnnexVResponse(1, { access_token: 'secret-code-xyz', category: 'staff', form: 2, version: '2.0.0', answers: {} }),
        error => { assert.equal(error.status, status); assert.match(error.message, pattern); assert.ok(!error.message.includes('secret-code-xyz')); return true })
    })
  }
  await withFetch(async () => { throw new TypeError('network') }, async () => {
    await assert.rejects(api.submitAnnexVResponse(1, { access_token: 'x', category: 'staff', form: 2, version: '2.0.0', answers: {} }), api.AnnexVOutcomeUnknownError)
  })
  await withFetch(async () => reply({}, 500), async () => {
    await assert.rejects(api.submitAnnexVResponse(1, { access_token: 'x', category: 'staff', form: 2, version: '2.0.0', answers: {} }), /могли прийняти/)
  })
})

test('expert assessment: admin session with CSRF, exact body, 201 id, 409 shows server detail', async () => {
  client.setCsrfToken('csrf-1')
  const answers = fullAnswers(1)
  const { calls, handler } = recorder(() => reply({ id: 11 }, 201))
  await withFetch(handler, async () => {
    assert.deepEqual(await api.submitExpertAssessment(4, { expert_label: 'Начальник кафедри', form: 1, version: '2.0.0', answers }), { id: 11 })
  })
  assert.equal(calls[0].url, '/api/assessments/4/annex-v/expert')
  assert.equal(calls[0].method, 'POST')
  assert.equal(calls[0].credentials, 'include')
  assert.equal(calls[0].csrf, 'csrf-1')
  assert.deepEqual(calls[0].body, { expert_label: 'Начальник кафедри', form: 1, version: '2.0.0', answers })
  await withFetch(async () => reply({ detail: 'Цикл у статусі чернетки.' }, 409), async () => {
    await assert.rejects(api.submitExpertAssessment(4, { expert_label: 'Аудитор', form: 1, version: '2.0.0', answers }), /Цикл у статусі чернетки/)
  })
  await withFetch(async () => reply({ detail: [{ loc: ['body', 'expert_label'] }] }, 422), async () => {
    await assert.rejects(api.submitExpertAssessment(4, { expert_label: 'Аудитор', form: 1, version: '2.0.0', answers }), /посаду експерта/)
  })
})

test('checklist: GET list, PUT status+evidence with CSRF, POST confirm; same-user confirm 409 is shown', async () => {
  client.setCsrfToken('csrf-2')
  const { calls, handler } = recorder((url, options) => {
    if (options.method === 'PUT') return reply(item({ status: 'partial', evidence: 'Наказ № 5', entered_role: 'data_officer' }))
    if (url.endsWith('/confirm')) return reply(item({ status: 'partial', confirmed: true, confirmed_role: 'admin' }))
    return reply({ items: [item(), item({ code: 'B-2.1', status: 'yes', confirmed: true, confirmed_role: 'admin' }), { bogus: true }] })
  })
  await withFetch(handler, async () => {
    const list = await api.getChecklist(5)
    assert.equal(list.length, 2)
    assert.deepEqual(checklist.checklistCounters(list), { entered: 1, confirmed: 1, total: 2 })
    const updated = await api.updateChecklistItem(5, 'B-1.1', { status: 'partial', evidence: 'Наказ № 5' })
    assert.equal(updated.status, 'partial')
    const confirmed = await api.confirmChecklistItem(5, 'B-1.1')
    assert.equal(confirmed.confirmed, true)
  })
  assert.deepEqual(calls.map(call => [call.method, call.url]), [
    ['GET', '/api/assessments/5/checklist'],
    ['PUT', '/api/assessments/5/checklist/B-1.1'],
    ['POST', '/api/assessments/5/checklist/B-1.1/confirm'],
  ])
  assert.equal(calls[0].csrf, null)
  assert.ok(calls.slice(1).every(call => call.csrf === 'csrf-2' && call.credentials === 'include'))
  assert.deepEqual(calls[1].body, { status: 'partial', evidence: 'Наказ № 5' })
  assert.equal(calls[2].body, undefined)

  await withFetch(async () => reply({ detail: 'Не можна підтвердити власний запис.' }, 409), async () => {
    await assert.rejects(api.confirmChecklistItem(5, 'B-1.1'), error => error.status === 409 && error.message === 'Не можна підтвердити власний запис.')
  })
  await withFetch(async () => reply({}, 409), async () => {
    await assert.rejects(api.confirmChecklistItem(5, 'B-1.1'), error => error.message === api.SELF_CONFIRM_MESSAGE)
  })
  const odd = recorder(() => reply(item({ code: 'a/b c' })))
  await withFetch(odd.handler, () => api.updateChecklistItem(5, 'a/b c', { status: 'no' }))
  assert.equal(odd.calls[0].url, '/api/assessments/5/checklist/a%2Fb%20c')
  assert.deepEqual(odd.calls[0].body, { status: 'no' })
})

test('objective indicators: GET, POST create body, POST confirm by indicator id', async () => {
  client.setCsrfToken('csrf-3')
  const { calls, handler } = recorder(url => {
    if (url.endsWith('/confirm')) return reply(indicator({ confirmed: true, confirmed_role: 'admin' }))
    if (url.endsWith('/objective-indicators') && calls.at(-1).method === 'POST') return reply(indicator(), 201)
    return reply({ items: [indicator(), { id: 'x' }] })
  })
  await withFetch(handler, async () => {
    assert.equal((await api.getObjectiveIndicators(2)).length, 1)
    const body = validation.indicatorPayload({ criterion: 'education', name: ' Охоплення навчанням ', value: '72,5', target: '90', period: ' 2026 ' })
    assert.deepEqual(body, { criterion: 'education', name: 'Охоплення навчанням', value: 72.5, target: 90, period: '2026' })
    await api.createObjectiveIndicator(2, body)
    assert.equal((await api.confirmObjectiveIndicator(3)).confirmed, true)
  })
  assert.deepEqual(calls.map(call => [call.method, call.url, call.csrf]), [
    ['GET', '/api/assessments/2/objective-indicators', null],
    ['POST', '/api/assessments/2/objective-indicators', 'csrf-3'],
    ['POST', '/api/objective-indicators/3/confirm', 'csrf-3'],
  ])
  assert.deepEqual(calls[1].body, { criterion: 'education', name: 'Охоплення навчанням', value: 72.5, target: 90, period: '2026' })
  await withFetch(async () => reply({}, 409), async () => {
    await assert.rejects(api.confirmObjectiveIndicator(3), error => error.message === api.SELF_CONFIRM_MESSAGE)
  })
})

test('mutations without a CSRF token are not sent', async () => {
  client.setCsrfToken('')
  let called = false
  await withFetch(async () => { called = true; return reply({}) }, async () => {
    await assert.rejects(api.confirmChecklistItem(1, 'B-1'), /CSRF/)
    await assert.rejects(api.submitExpertAssessment(1, { expert_label: 'Аудитор', form: 1, version: '2.0.0', answers: {} }), /CSRF/)
  })
  assert.equal(called, false)
  client.setCsrfToken('csrf-4')
})

// ---------------------------------------------------------------- валідація

test('validation: access code, expert label (position, not a name), checklist entry and indicator draft', () => {
  assert.match(validation.validateAccessCode('  '), /Введіть/)
  assert.match(validation.validateAccessCode('a b'), /пробілів/)
  assert.match(validation.validateAccessCode('x'.repeat(129)), /128/)
  assert.equal(validation.validateAccessCode(' 0123abcd '), null)

  assert.match(validation.validateExpertLabel('ab'), /щонайменше 3/)
  assert.match(validation.validateExpertLabel('x'.repeat(121)), /120/)
  assert.match(validation.validateExpertLabel('Іваненко Іван Іванович'), /ПІБ/)
  assert.match(validation.validateExpertLabel('Петренко О.В.'), /ПІБ/)
  assert.match(validation.validateExpertLabel('expert@example.test'), /email/)
  for (const ok of ['Начальник кафедри', 'Заступник начальника з навчальної роботи', 'Член робочої групи', 'Аудитор']) assert.equal(validation.validateExpertLabel(ok), null, ok)

  assert.ok(validation.validateChecklistEntry({ status: '', evidence: '' }).status)
  assert.ok(validation.validateChecklistEntry({ status: 'yes', evidence: 'x'.repeat(501) }).evidence)
  assert.deepEqual(validation.validateChecklistEntry({ status: 'partial', evidence: '' }), {})

  const draft = { criterion: 'education', name: 'Охоплення', value: '50', target: '80', period: '2026' }
  assert.deepEqual(validation.validateIndicatorDraft(draft), {})
  assert.ok(validation.validateIndicatorDraft({ ...draft, criterion: 'maturity' }).criterion)
  assert.ok(validation.validateIndicatorDraft({ ...draft, criterion: 'unknown' }).criterion)
  assert.ok(validation.validateIndicatorDraft({ ...draft, value: '101' }).value)
  assert.ok(validation.validateIndicatorDraft({ ...draft, target: 'abc' }).target)
  assert.ok(validation.validateIndicatorDraft({ ...draft, value: '' }).value)
  assert.ok(validation.validateIndicatorDraft({ ...draft, name: 'ab' }).name)
  assert.ok(validation.validateIndicatorDraft({ ...draft, period: ' ' }).period)
})

test('submission setup and answers: every question required, only template keys are sent', () => {
  const setup = official.setupErrors
  assert.deepEqual(Object.keys(setup('self', { cycleId: null, category: '', code: '', label: '' })), ['cycle', 'category', 'code'])
  assert.deepEqual(setup('self', { cycleId: 1, category: 'staff', code: 'abc', label: '' }), {})
  assert.deepEqual(Object.keys(setup('expert', { cycleId: 1, category: '', code: '', label: 'Іваненко Іван' })), ['label'])
  assert.deepEqual(setup('expert', { cycleId: 1, category: '', code: '', label: 'Член робочої групи' }), {})
  const template = getOfficialTemplate('appendix-v-form-1', '2.0.0')
  const answers = { ...fullAnswers(1), 'av-f2-culture-1': 'av-f2-culture-1-a' }
  assert.deepEqual(Object.keys(validation.answersForTemplate(template, answers)), template.questions.map(q => q.id))
  assert.equal(catalogV2.ANNEX_V_CRITERIA.length, 11)
  assert.ok(Object.isFrozen(catalogV2.ANNEX_V_CRITERIA))
  assert.deepEqual(api.INDICATOR_CRITERIA, catalogV2.ANNEX_V_CRITERIA.filter(key => key !== 'maturity'))
  assert.equal(api.criterionLabel('ethics'), 'Етика й корпоративна культура (C1)')
  assert.equal(api.criterionLabel('maturity'), 'Загальний рівень зрілості (самооцінка)')
  assert.equal(api.criterionLabel('raw-key'), 'raw-key')
})

// ---------------------------------------------------------------- рендер

test('self questionnaire renders cycle/category/form/code setup, anonymity note and no own score', () => {
  const markup = html(createElement(official.default, { mode: 'self', cycles: [cycle(1, 'open', { categories: ['staff', 'cadets'] }), cycle(2, 'closed')] }))
  for (const text of ['Цикл оцінювання', 'Категорія респондента', 'Анкета 2 — особовий склад', 'Анкета 1 — робоча група', 'Одноразовий код доступу', 'Анонімно.', 'не пов’язується з вашим обліковим записом', 'лише для одного подання'])
    assert.ok(markup.includes(text), text)
  assert.ok(markup.includes('Цикл 1'))
  assert.ok(!markup.includes('Цикл 2'), 'closed cycles are not offered to respondents')
  assert.ok(markup.includes('Працівники') && markup.includes('Курсанти') && !markup.includes('Керівництво'))
  assert.match(markup, /<input id="official-code" type="password" autocomplete="off"/i)
  assert.doesNotMatch(markup, /Ваш рівень|ваш бал|a = 1/)
  assert.doesNotMatch(markup, /не зберігаються/)
  const empty = html(createElement(official.default, { mode: 'self', cycles: [cycle(2, 'closed')] }))
  assert.ok(empty.includes('Зараз немає відкритих циклів'))
  assert.ok(html(createElement(official.default, { mode: 'self' })).includes('Завантажуємо цикли оцінювання'))
})

test('expert questionnaire offers open and closed cycles, position field, form 1 and the level rule', () => {
  const markup = html(createElement(official.default, { mode: 'expert', cycles: [cycle(1, 'open'), cycle(2, 'closed'), cycle(3, 'draft')] }))
  assert.ok(markup.includes('Цикл 1 · відкритий') && markup.includes('Цикл 2 · закритий') && !markup.includes('Цикл 3'))
  assert.ok(markup.includes('Посада або роль експерта'))
  assert.ok(markup.includes('Не вказуйте ПІБ'))
  assert.ok(markup.includes('Питання 1 з 12'))
  assert.ok(markup.includes('a = 1, b = 2'))
  assert.ok(!markup.includes('Одноразовий код доступу'))
})

test('checklist view: who enters/confirms, counters, badges, admin-only confirm and error message', () => {
  const items = [item(), item({ code: 'B-1.2', status: 'yes', evidence: 'Наказ', entered_role: 'data_officer', entered_at: '2026-11-19T10:00:00Z' }),
    item({ code: 'B-1.3', status: 'no', confirmed: true, confirmed_role: 'admin' })]
  const props = role => ({ role, cycles: { status: 'ready', data: [cycle(1, 'open')] }, cycleId: 1, onCycle: noop, onRetryCycles: noop,
    items: { status: 'ready', data: items }, onRetryItems: noop, busy: null, messages: { 'B-1.2': { kind: 'error', text: api.SELF_CONFIRM_MESSAGE } }, onSave: noop, onConfirm: noop })
  const admin = html(createElement(checklist.ChecklistView, props('admin')))
  for (const text of ['Чеклист Додатка Б', 'Хто вносить і хто підтверджує', 'data_officer', 'не той самий користувач', 'Внесено', 'Підтверджено', 'Усього пунктів',
    'Не підтверджено', 'Підтверджено (Адміністратор)', 'Так', 'Частково', 'Ні', 'Додаток Б (адаптовано)', 'Етика й корпоративна культура (C1)', 'Вніс: Відповідальний за коди доступу', api.SELF_CONFIRM_MESSAGE])
    assert.ok(admin.includes(text), text)
  assert.match(admin, /<dt>Внесено<\/dt><dd>2<\/dd>/)
  assert.match(admin, /<dt>Підтверджено<\/dt><dd>1<\/dd>/)
  assert.match(admin, /<dt>Усього пунктів<\/dt><dd>3<\/dd>/)
  assert.equal(admin.match(/>Підтвердити</g)?.length, 1, 'only entered, unconfirmed items can be confirmed')
  const officer = html(createElement(checklist.ChecklistView, props('data_officer')))
  assert.ok(!officer.includes('>Підтвердити<'))
  assert.ok(officer.includes('Зберегти'))
  const loading = html(createElement(checklist.ChecklistView, { ...props('admin'), items: { status: 'loading' } }))
  assert.ok(loading.includes('Завантажуємо чеклист'))
  const failed = html(createElement(checklist.ChecklistView, { ...props('admin'), cycles: { status: 'error', message: 'Помилка мережі' } }))
  assert.ok(failed.includes('Помилка мережі') && failed.includes('Спробувати ще раз'))
  assert.ok(html(createElement(checklist.ChecklistView, { ...props('admin'), items: { status: 'ready', data: [] } })).includes('ще не сформовано'))
})

test('objective indicators view: list, add form, admin confirm and badges', () => {
  const props = role => ({ role, cycles: { status: 'ready', data: [cycle(1, 'closed')] }, cycleId: 1, onCycle: noop, onRetryCycles: noop,
    items: { status: 'ready', data: [indicator(), indicator({ id: 4, value: 95, confirmed: true, confirmed_role: 'admin' })] }, onRetryItems: noop,
    busy: null, formError: '', messages: {}, onCreate: async () => true, onConfirm: noop })
  const admin = html(createElement(indicators.ObjectiveIndicatorsView, props('admin')))
  for (const text of ['Об’єктивні показники', 'Охоплення навчанням', 'Навчання персоналу (C5)', '72%', '90%', 'нижче цілі', 'Додати показник', 'Критерій Додатка В',
    'Значення, %', 'Ціль, %', 'Період', 'Не підтверджено', 'Підтверджено (Адміністратор)', 'Хто вносить і хто підтверджує'])
    assert.ok(admin.includes(text), text)
  assert.equal(admin.match(/>Підтвердити</g)?.length, 1)
  assert.ok(!admin.includes('value="maturity"'))
  const officer = html(createElement(indicators.ObjectiveIndicatorsView, props('data_officer')))
  assert.ok(!officer.includes('>Підтвердити<'))
  assert.ok(officer.includes('Додати показник'))
  assert.ok(html(createElement(indicators.ObjectiveIndicatorsView, { ...props('admin'), items: { status: 'ready', data: [] } })).includes('показників ще немає'))
})

test('navigation adds checklist and objective sections for admin and data_officer', () => {
  const admin = nav.navigationFor('admin')
  assert.deepEqual(admin.find(entry => entry.key === 'checklist'), { key: 'checklist', title: 'Чеклист Додатка Б', path: '/admin/checklist' })
  assert.deepEqual(admin.find(entry => entry.key === 'objective'), { key: 'objective', title: 'Об’єктивні показники', path: '/admin/objective' })
  assert.ok(admin.some(entry => entry.key === 'expert'))
  assert.deepEqual(nav.routeFromPath('/officer/checklist'), { role: 'data_officer', section: 'checklist' })
  assert.deepEqual(nav.routeFromPath('/officer/objective'), { role: 'data_officer', section: 'objective' })
  assert.deepEqual(nav.routeFromPath('/admin/objective'), { role: 'admin', section: 'objective' })
  assert.equal(nav.sectionTitle({ role: 'data_officer', section: 'checklist' }), 'Чеклист Додатка Б')
  assert.ok(!nav.navigationFor('user').some(entry => ['checklist', 'objective'].includes(entry.key)))
})
