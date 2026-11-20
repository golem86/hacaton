import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** Звіт зрілості за Додатком В: API-клієнт GET /v2/admin/reports/{id}/maturity-export і кнопки PDF/XLSX. */
const server = await createServer({
  server: { middlewareMode: true, hmr: false },
  optimizeDeps: { noDiscovery: true },
  cacheDir: 'node_modules/.vite-maturity-report-test',
  appType: 'custom',
  logLevel: 'error',
})
after(() => server.close())

const reports = await server.ssrLoadModule('/src/api/reports.ts')
const buttons = await server.ssrLoadModule('/src/dashboard/MaturityReportButtons.tsx')
const { ApiError } = await server.ssrLoadModule('/src/api/client.ts')

const PDF = 'application/pdf'
const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
const text = markup => markup.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')

/** Підміна fetch і DOM-завантаження (у node немає document/URL.createObjectURL). */
async function withDownload(reply, run) {
  const calls = { fetch: [], links: [], revoked: [] }
  const saved = {
    fetch: globalThis.fetch, document: globalThis.document, window: globalThis.window,
    create: URL.createObjectURL, revoke: URL.revokeObjectURL,
  }
  globalThis.fetch = async (url, options = {}) => { calls.fetch.push({ url, options }); return reply(url) }
  globalThis.document = {
    createElement: () => {
      const link = { click() { calls.links.push({ href: link.href, download: link.download }) }, remove() {} }
      return link
    },
    body: { appendChild() {} },
  }
  globalThis.window = { setTimeout: callback => callback(), dispatchEvent() {} }
  URL.createObjectURL = () => 'blob:maturity'
  URL.revokeObjectURL = url => calls.revoked.push(url)
  try { await run(calls) } finally {
    globalThis.fetch = saved.fetch
    if (saved.document === undefined) delete globalThis.document; else globalThis.document = saved.document
    if (saved.window === undefined) delete globalThis.window; else globalThis.window = saved.window
    URL.createObjectURL = saved.create
    URL.revokeObjectURL = saved.revoke
  }
}

const file = type => new Response(new Uint8Array([37, 80, 68, 70]), { status: 200, headers: { 'Content-Type': type } })

test('downloadMaturityReport запитує маршрут експорту із сесією й зберігає файл з ASCII-назвою', async () => {
  for (const [format, type] of [['pdf', PDF], ['xlsx', XLSX]]) {
    await withDownload(() => file(type), async calls => {
      await reports.downloadMaturityReport(7, format, new AbortController().signal)
      assert.equal(calls.fetch.length, 1)
      assert.equal(calls.fetch[0].url, `/v2/admin/reports/7/maturity-export?format=${format}`)
      assert.equal(calls.fetch[0].options.credentials, 'include')
      assert.equal(calls.fetch[0].options.method, undefined)                 // GET, без CSRF
      assert.deepEqual(calls.links, [{ href: 'blob:maturity', download: `maturity-report-7.${format}` }])
      assert.deepEqual(calls.revoked, ['blob:maturity'])
    })
  }
})

test('downloadMaturityReport показує людські повідомлення для 403/404/409/503', async () => {
  for (const status of [403, 404, 409, 503]) {
    await withDownload(() => new Response('{"detail":"x"}', { status }), async calls => {
      await assert.rejects(reports.downloadMaturityReport(3, 'pdf', new AbortController().signal), error => {
        assert.ok(error instanceof ApiError)
        assert.equal(error.status, status)
        assert.equal(error.message, reports.MATURITY_REPORT_ERRORS[status])
        assert.match(error.message, /[а-яіїєґ]/i)
        assert.doesNotMatch(error.message, /HTTP|detail/)
        return true
      })
      assert.equal(calls.links.length, 0)
    })
  }
  assert.match(reports.MATURITY_REPORT_ERRORS[409], /після закриття циклу/)
  assert.match(reports.MATURITY_REPORT_ERRORS[403], /адміністратору/)
})

test('downloadMaturityReport відхиляє файл неочікуваного типу і невідомий статус', async () => {
  await withDownload(() => file('text/html'), async calls => {
    await assert.rejects(reports.downloadMaturityReport(3, 'xlsx', new AbortController().signal), /неочікуваному форматі/)
    assert.equal(calls.links.length, 0)
  })
  await withDownload(() => new Response(null, { status: 500 }), async () => {
    await assert.rejects(reports.downloadMaturityReport(3, 'pdf', new AbortController().signal), /HTTP 500/)
  })
})

test('звіт циклу й надалі завантажується з власного маршруту і з власною назвою', async () => {
  await withDownload(() => file(PDF), async calls => {
    await reports.downloadCycleReport(4, 'pdf', new AbortController().signal)
    assert.equal(calls.fetch[0].url, '/v2/admin/reports/4/export?format=pdf')
    assert.equal(calls.links[0].download, 'integrity-report-4.pdf')
  })
})

test('кнопки «Звіт зрілості PDF» і «Звіт зрілості XLSX»', () => {
  const markup = renderToStaticMarkup(createElement(buttons.MaturityReportButtons, { id: 5 }))
  const visible = text(markup)
  assert.match(visible, /Звіт зрілості PDF/)
  assert.match(visible, /Звіт зрілості XLSX/)
  assert.equal((markup.match(/<button type="button"/g) ?? []).length, 2)
  assert.doesNotMatch(markup, /disabled/)
  assert.match(markup, /role="group" aria-label="Звіт зрілості за Додатком В"/)
  assert.deepEqual(buttons.MATURITY_REPORT_FORMATS, ['pdf', 'xlsx'])
})

test('кнопки є в розділі «Звіти» і в панелі зрілості адміністратора', async () => {
  const source = path => readFile(new URL(path, import.meta.url), 'utf8')
  const panel = await source('../src/v2/ReportsPanel.tsx')
  assert.match(panel, /<MaturityReportButtons id=\{id\} \/>/)
  const maturity = await source('../src/dashboard/MaturityPanel.tsx')
  assert.match(maturity, /exportable && state\.status === 'success' && <MaturityReportButtons/)
  const main = await source('../src/main.tsx')
  assert.match(main, /<MaturityPanel assessments=\{assessments\} selectedId=\{id\} exportable \/>/)
})
