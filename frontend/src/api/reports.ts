import type { AssessmentResults } from '../dashboard/types'
import { normalizeResults } from '../dashboard/suppression'
import { ApiError, getJson, request, statusMessage } from './client'

export type ReportFormat = 'pdf' | 'xlsx'

interface CycleReport {
  aggregates: AssessmentResults
  exports: Record<ReportFormat, 'available' | 'unavailable'>
}

const errors: Partial<Record<number, string>> = {
  401: 'Сесію завершено, увійдіть знову.',
  403: 'Звіти доступні лише адміністратору.',
  404: 'Цикл не знайдено.',
  409: 'Звіт доступний після закриття циклу.',
  501: 'Цей формат експорту недоступний у поточній версії сервера.',
}

const mediaTypes: Record<ReportFormat, string> = {
  pdf: 'application/pdf',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

export async function getCycleReport(id: number, signal: AbortSignal): Promise<CycleReport> {
  const report = await getJson<CycleReport>(`/v2/admin/reports/${id}`, signal, errors)
  if (report === null || typeof report !== 'object' || report.aggregates === null || typeof report.aggregates !== 'object') {
    throw new ApiError(200, 'API повернув некоректну відповідь звіту.')
  }
  // Ті самі правила, що й для /results: приховані групи не перелічуються, лишається прапорець suppressed.
  return { ...report, aggregates: normalizeResults(report.aggregates) }
}

export async function downloadCycleReport(id: number, format: ReportFormat, signal: AbortSignal) {
  await downloadFile(`/v2/admin/reports/${id}/export?format=${format}`, `integrity-report-${id}.${format}`, format, signal, errors)
}

/** Повідомлення для звіту зрілості за Додатком В (ті самі умови, що й GET /api/assessments/{id}/maturity). */
export const MATURITY_REPORT_ERRORS: Readonly<Partial<Record<number, string>>> = {
  401: 'Сесію завершено, увійдіть знову.',
  403: 'Звіт зрілості доступний лише адміністратору.',
  404: 'Цикл не знайдено.',
  409: 'Звіт зрілості доступний після закриття циклу.',
  503: 'Аналітика зрілості вимкнена в поточній конфігурації сервера, тож звіт не сформовано.',
}

/** GET /v2/admin/reports/{id}/maturity-export?format=pdf|xlsx — звіт зрілості за Додатком В. */
export async function downloadMaturityReport(id: number, format: ReportFormat, signal: AbortSignal) {
  await downloadFile(`/v2/admin/reports/${id}/maturity-export?format=${format}`, `maturity-report-${id}.${format}`, format, signal, MATURITY_REPORT_ERRORS)
}

async function downloadFile(path: string, filename: string, format: ReportFormat, signal: AbortSignal,
  messages: Readonly<Partial<Record<number, string>>>) {
  const result = await request(path, { signal })
  if (!result.ok) {
    throw new ApiError(result.status, messages[result.status] ?? (result.status === 413 || result.status === 429 ? statusMessage(result.status) : `Не вдалося завантажити звіт (HTTP ${result.status}).`))
  }
  const type = result.headers.get('Content-Type')?.split(';')[0].trim()
  if (type !== mediaTypes[format]) throw new Error('Сервер повернув файл у неочікуваному форматі.')
  const blob = await result.blob()
  if (signal.aborted) return
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
