import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'

let api
let server
const originalFetch = globalThis.fetch
const assessment = { id: 3, name: 'Цикл', start_date: '2026-11-16', status: 'open', min_group_size: 5 }
const questionnaire = [{ code: 'A', name: 'Компонент', weight: 1, questions: [{ id: 9, text: 'Питання', scale: [1, 5] }] }]
const token = 'private-one-time-code'
const body = { token, respondent_category: 'mgmt', unit: 'Факультет 1', answers: [{ question_id: 9, value: 3 }] }

before(async () => {
  server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-assessments-test', appType: 'custom' })
  api = await server.ssrLoadModule('/src/api/assessments.ts')
})
after(async () => { globalThis.fetch = originalFetch; await server?.close() })

const reply = (value, status = 200) => new Response(JSON.stringify(value), { status })
function mockFetch(handler) {
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options })
    return handler(url, options)
  }
  return calls
}
function assertNoTokenLeak(error) { assert.equal(String(error).includes(token), false) }

test('GET methods preserve routes, roles, signal and valid responses', async () => {
  const controller = new AbortController()
  const calls = mockFetch(url => {
    if (url.endsWith('/questionnaires')) return reply(questionnaire)
    if (url.endsWith('/units')) return reply(['Факультет 1'])
    if (url.endsWith('/assessments/3')) return reply(assessment)
    return reply([assessment])
  })
  assert.deepEqual(await api.getAssessments(controller.signal), [assessment])
  assert.deepEqual(await api.getAssessment(3, controller.signal), assessment)
  assert.deepEqual(await api.getQuestionnaire(3, controller.signal), questionnaire)
  assert.deepEqual(await api.getUnits(controller.signal), ['Факультет 1'])
  assert.deepEqual(calls.map(call => new URL(call.url, 'http://localhost').pathname), [
    '/api/assessments', '/api/assessments/3', '/api/assessments/3/questionnaires', '/api/units',
  ])
  assert.deepEqual(calls.map(call => call.options.headers['X-Role']), ['manager', 'manager', 'respondent', 'respondent'])
  assert.ok(calls.every(call => call.options.signal === controller.signal))
})

test('GET rejects malformed JSON and invalid response shapes', async () => {
  const cases = [
    [() => api.getAssessments(), reply([{}])],
    [() => api.getAssessment(3), reply({ ...assessment, id: '3' })],
    [() => api.getQuestionnaire(3), reply([{ ...questionnaire[0], weight: '1' }])],
    [() => api.getQuestionnaire(3), reply([{ ...questionnaire[0], questions: [{ id: '9', text: 'Питання', scale: [1, 5] }] }])],
    [() => api.getQuestionnaire(3), reply([{ ...questionnaire[0], questions: [{ id: 9, text: 'Питання', scale: [1] }] }])],
    [() => api.getUnits(), reply(['Факультет 1', 7])],
    [() => api.getAssessments(), new Response('{', { status: 200 })],
  ]
  for (const [call, response] of cases) {
    mockFetch(() => response)
    await assert.rejects(call(), /API повернув некоректну відповідь/)
  }
})

test('GET preserves network and abort handling', async () => {
  mockFetch(() => { throw new Error('offline') })
  await assert.rejects(api.getAssessments(), /Не вдалося з’єднатися з API/)
  const controller = new AbortController()
  controller.abort()
  mockFetch(() => { throw new DOMException('Aborted', 'AbortError') })
  await assert.rejects(api.getUnits(controller.signal), { name: 'AbortError' })
})

test('POST confirms only 201 accepted and keeps code in body', async () => {
  const calls = mockFetch(() => reply({ status: 'accepted' }, 201))
  assert.deepEqual(await api.submitQuestionnaire(3, body), { status: 'accepted' })
  assert.equal(calls.length, 1)
  assert.equal(new URL(calls[0].url, 'http://localhost').pathname, '/api/assessments/3/submissions')
  assert.equal(calls[0].url.includes(token), false)
  assert.equal(calls[0].options.headers['X-Role'], 'respondent')
  assert.equal(calls[0].options.headers['Content-Type'], 'application/json')
  assert.deepEqual(JSON.parse(calls[0].options.body), body)
})

test('POST classifies 400, 401, 403, 409 and 422 as confirmed refusals without echoing detail', async () => {
  for (const status of [400, 401, 403, 409, 422]) {
    const calls = mockFetch(() => reply({ detail: [{ loc: ['body', 'token'], input: token, msg: token }] }, status))
    await assert.rejects(api.submitQuestionnaire(3, body), error => {
      assert.equal(error instanceof api.SubmissionOutcomeUnknownError, false)
      assertNoTokenLeak(error)
      return true
    })
    assert.equal(calls.length, 1)
    assert.equal(calls[0].url.includes(token), false)
  }
  mockFetch(() => reply({ detail: `sensitive ${token}` }, 403))
  await assert.rejects(api.submitQuestionnaire(3, body), error => { assertNoTokenLeak(error); return true })
  mockFetch(() => new Response('{', { status: 422 }))
  await assert.rejects(api.submitQuestionnaire(3, body), error => {
    assert.equal(error instanceof api.SubmissionOutcomeUnknownError, false)
    assertNoTokenLeak(error)
    return true
  })
})

test('POST uses typed unknown outcome on network failure, abort, malformed success and unexpected response', async () => {
  const controller = new AbortController()
  const cases = [
    () => { throw new Error(token) },
    () => { controller.abort(); throw new DOMException('Aborted', 'AbortError') },
    () => new Response('{', { status: 201 }),
    () => reply({ status: 'other' }, 201),
    () => reply({ status: 'accepted' }, 200),
    () => ({ status: 201, json: async () => { throw new DOMException('Aborted', 'AbortError') } }),
    () => reply({ detail: token }, 500),
  ]
  for (const handler of cases) {
    const calls = mockFetch(handler)
    await assert.rejects(api.submitQuestionnaire(3, body, controller.signal), error => {
      assert.ok(error instanceof api.SubmissionOutcomeUnknownError)
      assert.equal(error.kind, 'submission-outcome-unknown')
      assertNoTokenLeak(error)
      return true
    })
    assert.equal(calls.length, 1)
    assert.equal(calls[0].url.includes(token), false)
  }
})
