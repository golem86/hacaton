import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true },
  cacheDir: 'node_modules/.vite-narrative-test',
  appType: 'custom',
  logLevel: 'error',
})
after(() => server.close())

const api = await server.ssrLoadModule('/src/api/narrative.ts')
const client = await server.ssrLoadModule('/src/api/client.ts')
const panel = await server.ssrLoadModule('/src/v2/NarrativePanel.tsx')
const html = element => renderToStaticMarkup(element)
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

const job = (overrides = {}) => ({
  job_id: 'job_abcdefgh123', status: 'done', kind: 'summary', assessment_ids: [1],
  text: 'Середній бал C1 — 51.4.', verified: true, unverified_numbers: [],
  created_at: '2026-11-20T10:00:00Z', finished_at: '2026-11-20T10:01:30Z', ...overrides,
})
const ready = (enabled = true, reachable = true) => ({ status: 'ready', data: { enabled, reachable, model: enabled ? 'qwen3-8b' : null } })
const cycles = [
  { id: 2, name: '2026-I', status: 'closed' },
  { id: 1, name: '2025-II', status: 'closed' },
]

async function withFetch(handler, run) {
  const previous = globalThis.fetch
  globalThis.fetch = handler
  try { await run() } finally { globalThis.fetch = previous }
}

test('narrative API uses exact paths, methods, bodies and session CSRF', async () => {
  const calls = []
  client.setCsrfToken('test-csrf')
  await withFetch(async (url, options) => {
    const headers = new Headers(options.headers)
    calls.push({ url, method: options.method ?? 'GET', credentials: options.credentials, csrf: headers.get('X-CSRF-Token'),
                 body: options.body === undefined ? undefined : JSON.parse(options.body) })
    if (url.endsWith('/lm/status')) return json({ enabled: true, reachable: true, model: 'qwen3-8b' })
    if (url.includes('/lm/jobs/')) return json(job())
    return json({ job_id: 'job_abcdefgh123', status: 'queued' }, 202)
  }, async () => {
    assert.deepEqual(await api.getLmStatus(), { enabled: true, reachable: true, model: 'qwen3-8b' })
    assert.equal(await api.startCycleNarrative(1, 'summary'), 'job_abcdefgh123')
    assert.equal(await api.startCycleNarrative(1, 'recommendations'), 'job_abcdefgh123')
    assert.equal(await api.startCompareNarrative(1, 2), 'job_abcdefgh123')
    assert.equal((await api.getNarrativeJob('job_abcdefgh123')).text, 'Середній бал C1 — 51.4.')
  })
  assert.deepEqual(calls.map(call => [call.method, call.url, call.body]), [
    ['GET', '/v2/admin/lm/status', undefined],
    ['POST', '/v2/admin/reports/1/narrative', { kind: 'summary' }],
    ['POST', '/v2/admin/reports/1/narrative', { kind: 'recommendations' }],
    ['POST', '/v2/admin/reports/compare/narrative', { base_assessment_id: 1, target_assessment_id: 2 }],
    ['GET', '/v2/admin/lm/jobs/job_abcdefgh123', undefined],
  ])
  assert.ok(calls.every(call => call.credentials === 'include'))
  assert.ok(calls.filter(call => call.method === 'POST').every(call => call.csrf === 'test-csrf'))
})

test('narrative API maps errors to fixed messages without echoing server details', async () => {
  client.setCsrfToken('test-csrf')
  for (const [status, expected] of [[503, 'Локальна ШІ не налаштована на сервері.'], [429, 'Черга генерації заповнена. Спробуйте за кілька хвилин.'],
                                     [409, 'Чернетка доступна після закриття циклу.'], [404, 'Цикл не знайдено.']]) {
    await withFetch(async () => json({ detail: 'internal <b>details</b>' }, status), async () => {
      await assert.rejects(api.startCycleNarrative(1, 'summary'), error => error.status === status && error.message === expected)
    })
  }
  await withFetch(async () => json({ detail: 'Оберіть два різні цикли' }, 422), async () => {
    await assert.rejects(api.startCompareNarrative(1, 1), { message: 'Оберіть два різні цикли' })
  })
  await withFetch(async () => json({ detail: 'x' }, 404), async () => {
    await assert.rejects(api.getNarrativeJob('job_abcdefgh123'), /строк зберігання минув/)
  })
  await withFetch(async () => json({ job_id: '../../etc', status: 'queued' }, 202), async () => {
    await assert.rejects(api.startCycleNarrative(1, 'summary'), /некоректну відповідь/)
  })
})

test('job parser validates shape and keeps only expected fields', () => {
  assert.throws(() => api.parseNarrativeJob({ ...job(), status: 'weird' }), /некоректну/)
  assert.throws(() => api.parseNarrativeJob({ ...job(), text: undefined }), /некоректну/)
  const failed = api.parseNarrativeJob(job({ status: 'failed', text: undefined, verified: undefined, error: '' }))
  assert.equal(failed.error, 'Не вдалося згенерувати текст.')
  const parsed = api.parseNarrativeJob(job({ verified: false, unverified_numbers: ['73.4', 5, null], extra: '<x>' }))
  assert.deepEqual(parsed.unverified_numbers, ['73.4'])
  assert.equal('extra' in parsed, false)
  assert.deepEqual(api.parseLmStatus({ enabled: false, reachable: true, model: 5 }), { enabled: false, reachable: false, model: null })
  assert.throws(() => api.parseLmStatus({ enabled: 'yes' }), /некоректну/)
})

test('polling repeats every interval until the job is done', async () => {
  const states = ['queued', 'running', 'running', 'done']
  const seen = []
  const sleeps = []
  await withFetch(async () => {
    const status = states.shift()
    return json(status === 'done' ? job() : job({ status, text: undefined, verified: undefined, finished_at: undefined }))
  }, async () => {
    const final = await api.pollNarrativeJob('job_abcdefgh123', {
      onUpdate: update => seen.push(update.status), sleep: async ms => { sleeps.push(ms) },
    })
    assert.equal(final.status, 'done')
  })
  assert.deepEqual(seen, ['queued', 'running', 'running', 'done'])
  assert.deepEqual(sleeps, [4000, 4000, 4000])
  assert.ok(api.POLL_INTERVAL_MS >= 3000 && api.POLL_INTERVAL_MS <= 5000)
})

test('polling stops when aborted', async () => {
  const controller = new AbortController()
  await withFetch(async () => json(job({ status: 'running', text: undefined, verified: undefined })), async () => {
    const pending = api.pollNarrativeJob('job_abcdefgh123', { signal: controller.signal, intervalMs: 10_000 })
    setTimeout(() => controller.abort(), 5)
    await assert.rejects(pending)
  })
})

test('done result is plain text with the draft label and a copy button', () => {
  const markup = html(createElement(panel.NarrativeResult, { job: job({ text: '<img src=x onerror=alert(1)>\nДругий рядок' }) }))
  assert.match(markup, /Чернетка, згенерована локальною ШІ\. Перевірте перед використанням\./)
  assert.match(markup, /&lt;img src=x onerror=alert\(1\)&gt;/)
  assert.doesNotMatch(markup, /<img/)
  assert.match(markup, />Копіювати</)
  assert.doesNotMatch(markup, /Деяких чисел немає/)
  assert.doesNotMatch(markup, /style=/)
})

test('unverified numbers are listed as a warning', () => {
  const markup = html(createElement(panel.NarrativeResult, { job: job({ verified: false, unverified_numbers: ['73.4', '2019'] }) }))
  assert.match(markup, /role="alert"/)
  assert.match(markup, /Деяких чисел немає в даних звіту/)
  assert.match(markup, /<li>73\.4<\/li><li>2019<\/li>/)
})

test('queued, running and failed jobs show progress or a generic error', () => {
  const pending = { text: undefined, verified: undefined }
  assert.match(html(createElement(panel.NarrativeResult, { job: job({ ...pending, status: 'queued' }) })), /Резюме циклу: у черзі/)
  assert.match(html(createElement(panel.NarrativeResult, { job: job({ ...pending, status: 'running', kind: 'compare' }) })),
               /Порівняння циклів: генеруємо текст/)
  const failed = html(createElement(panel.NarrativeResult, { job: job({ ...pending, status: 'failed', error: 'Локальна ШІ не відповіла вчасно. Спробуйте пізніше.' }) }))
  assert.match(failed, /role="alert"[^>]*>Локальна ШІ не відповіла вчасно/)
  assert.doesNotMatch(failed, /Копіювати/)
})

test('buttons are enabled only when the local LM is enabled and reachable', () => {
  const enabled = html(createElement(panel.CycleNarrative, { id: 1, lm: ready() }))
  assert.match(enabled, />Резюме \(ШІ\)</)
  assert.match(enabled, />Чернетки рекомендацій \(ШІ\)</)
  assert.doesNotMatch(enabled, /disabled/)
  assert.match(enabled, /не зберігаються в трекер/)

  for (const [lm, reason] of [[ready(false, false), /не налаштована на сервері/], [ready(true, false), /зараз недоступна/],
                              [{ status: 'loading' }, /Перевіряємо доступність/], [{ status: 'error', message: 'збій' }, /Не вдалося перевірити/]]) {
    const markup = html(createElement(panel.CycleNarrative, { id: 1, lm }))
    assert.equal((markup.match(/disabled=""/g) ?? []).length, 2)
    assert.match(markup, reason)
  }
})

test('compare section needs two closed cycles and an enabled LM', () => {
  assert.equal(html(createElement(panel.CompareNarrative, { cycles: cycles.slice(0, 1), lm: ready() })), '')
  const markup = html(createElement(panel.CompareNarrative, { cycles, lm: ready() }))
  assert.match(markup, />Порівняння циклів \(ШІ\)<\/button>/)
  assert.match(markup, /Попередній цикл/)
  assert.match(markup, /Поточний цикл/)
  assert.doesNotMatch(markup, /<button[^>]*disabled/)
  assert.match(html(createElement(panel.CompareNarrative, { cycles, lm: ready(false, false) })), /<button[^>]*disabled=""[^>]*>Порівняння циклів/)
})
