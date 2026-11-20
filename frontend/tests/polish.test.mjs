import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { after, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-polish-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const audit = await server.ssrLoadModule('/src/v2/AuditTrail.tsx')
const manager = await server.ssrLoadModule('/src/components/AssessmentManager.tsx')
const personal = await server.ssrLoadModule('/src/v2/PersonalModule.tsx')
const official = await server.ssrLoadModule('/src/official/OfficialAssessment.tsx')
const { officialTemplates } = await server.ssrLoadModule('/src/official/catalog.ts')
const AuditTrail = audit.default

const events = [
  { id: 3, created_at: '2026-11-20T09:05:07Z', actor_role: 'admin', action: 'tokens.issue', assessment_id: 4, details: { count: 25 } },
  { id: 2, created_at: '2026-11-19T18:30:00Z', actor_role: 'user', action: 'auth.login', assessment_id: null, details: {} },
  { id: 1, created_at: '2026-11-18T07:00:00Z', actor_role: 'admin', action: 'custom.unknown', assessment_id: 4, details: {} },
]

test('every backend audit action has a Ukrainian label and unknown codes stay raw', async () => {
  const source = await readFile(new URL('../../backend/app/audit.py', import.meta.url), 'utf8')
  const allowlist = source.match(/ALLOWED_ACTIONS\s*=\s*\{([\s\S]*?)\}/)?.[1] ?? ''
  const actions = [...allowlist.matchAll(/"([a-z_.]+)"/g)].map(match => match[1])
  assert.ok(actions.length >= 6, 'ALLOWED_ACTIONS parsed from backend/app/audit.py')
  for (const action of actions) {
    const label = audit.auditActionLabel(action)
    assert.notEqual(label, action, `немає підпису для ${action}`)
    assert.match(label, /[а-щьюяґєії]/i)
  }
  assert.equal(audit.auditActionLabel('custom.unknown'), 'custom.unknown')
  assert.equal(audit.auditActionLabel('toString'), 'toString')
  assert.equal(audit.actorRoleLabel('admin'), 'Адміністратор')
  assert.equal(audit.actorRoleLabel('user'), 'Користувач')
  assert.equal(audit.actorRoleLabel('robot'), 'robot')
  assert.deepEqual(audit.formatAuditDetails('tokens.issue', { count: 25 }), ['25 кодів'])
  assert.deepEqual(audit.formatAuditDetails('tokens.issue', { count: 1 }), ['1 код'])
  assert.deepEqual(audit.formatAuditDetails('assessment.close', {}), [])
})

test('audit dates are formatted for uk-UA and invalid values are kept', () => {
  assert.match(audit.formatAuditDate('2026-11-20T09:05:07Z', 'UTC'), /^20\.11\.2026,? 09:05:07$/)
  assert.equal(audit.formatAuditDate('not-a-date'), 'not-a-date')
})

test('audit trail renders a readable Ukrainian journal with filters', () => {
  const html = renderToStaticMarkup(React.createElement(AuditTrail, { events, error: '' }))
  assert.ok(html.includes('Журнал дій користувачів'))
  assert.ok(html.includes('Зміст анонімних відповідей'))
  for (const text of ['Видача кодів доступу', 'Вхід до системи (2FA)', 'Адміністратор', 'Користувач', '25 кодів', '№ 4', 'custom.unknown']) {
    assert.ok(html.includes(text), text)
  }
  assert.ok(html.includes(audit.formatAuditDate('2026-11-20T09:05:07Z')))
  assert.doesNotMatch(html, />2026-11-20T09:05:07Z</)
  for (const text of ['Тип дії', 'Усі дії', 'Усі цикли', 'Цикл № 4', 'Без циклу']) assert.ok(html.includes(text), text)
  assert.ok(html.includes('3 записи'))
})

test('audit trail has distinct empty and error states', () => {
  const empty = renderToStaticMarkup(React.createElement(AuditTrail, { events: [], error: '' }))
  assert.ok(empty.includes('Записів поки немає'))
  assert.ok(!empty.includes('<table'))
  const failed = renderToStaticMarkup(React.createElement(AuditTrail, { events: [], error: 'Недостатньо прав для цієї дії' }))
  assert.match(failed, /role="alert"/)
  assert.ok(failed.includes('Недостатньо прав для цієї дії'))
  assert.ok(!failed.includes('Записів поки немає'))
})

test('cycle statuses are shown in Ukrainian', () => {
  assert.equal(manager.cycleStatusLabel('draft'), 'Чернетка')
  assert.equal(manager.cycleStatusLabel('open'), 'Відкритий')
  assert.equal(manager.cycleStatusLabel('closed'), 'Закритий')
  assert.equal(manager.cycleStatusLabel('archived'), 'archived')
})

test('participation chart shows «приховано» for suppressed values and never a zero', () => {
  const chart = participation => renderToStaticMarkup(React.createElement(manager.ParticipationChart, { participation }))
  const hidden = chart({ status: 'open', tokens_issued: 12, tokens_unused: null, responses_total: null, participation_percent: null })
  assert.match(hidden, /приховано/)
  assert.ok(!hidden.includes('<canvas'))
  assert.doesNotMatch(hidden, />0</)
  const visible = chart({ status: 'closed', tokens_issued: 40, tokens_unused: 10, responses_total: 30, participation_percent: 75 })
  assert.ok(visible.includes('<canvas'))
  for (const text of ['Використані коди', '>30<', 'Невикористані коди', '>10<', '75%']) assert.ok(visible.includes(text), text)
  assert.ok(chart({ status: 'open', tokens_issued: 0, tokens_unused: null, responses_total: null, participation_percent: null }).includes('Коди ще не видано'))
})

test('personal tests are numbered with padStart and texts use Ukrainian formats', async () => {
  assert.deepEqual([0, 8, 9, 10].map(index => personal.formatTestNumber(index)), ['01', '09', '10', '11'])
  const source = await readFile(new URL('../src/v2/PersonalModule.tsx', import.meta.url), 'utf8')
  assert.ok(!source.includes('0{index + 1}'))
  assert.deepEqual([1, 3, 5, 21].map(count => personal.recordsLabel(count)), ['1 запис', '3 записи', '5 записів', '21 запис'])
  assert.equal(personal.formatAverage(3.456), '3,5')
  assert.equal(personal.formatAverage(null), '—')
})

test('official previews no longer show WIP wording', () => {
  const self = renderToStaticMarkup(React.createElement(official.default, { mode: 'self' }))
  const expert = renderToStaticMarkup(React.createElement(official.default, { mode: 'expert' }))
  assert.ok(self.includes('Офіційна анкета (Додаток В) — демонстраційний перегляд'))
  assert.ok(expert.includes('Експертне оцінювання — демонстраційний перегляд'))
  for (const html of [self, expert]) assert.doesNotMatch(html, /WIP|preview/i)
  for (const template of officialTemplates) {
    for (const text of [template.title, template.contentNote ?? '']) assert.doesNotMatch(official.presentableText(text), /WIP|preview/i)
  }
})
