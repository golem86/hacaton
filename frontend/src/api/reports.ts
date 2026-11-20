import type { AssessmentResults } from '../dashboard/types'
import { ApiError, getJson, request } from './client'

export type ReportFormat = 'pdf' | 'xlsx'

interface CycleReport {
  aggregates: AssessmentResults
  exports: Record<ReportFormat, 'available' | 'unavailable'>
}

const errors: Partial<Record<number, string>> = {
  401: 'Увійдіть знову, щоб переглянути звіт.',
  403: 'Звіти доступні лише адміністратору.',
  404: 'Цикл не знайдено.',
  409: 'Звіт доступний після закриття циклу.',
  501: 'Цей формат експорту недоступний у поточній версії сервера.',
}

const mediaTypes: Record<ReportFormat, string> = {
  pdf: 'application/pdf',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

export function getCycleReport(id: number, signal: AbortSignal) {
  return getJson<CycleReport>(`/v2/admin/reports/${id}`, signal, errors)
}

export async function downloadCycleReport(id: number, format: ReportFormat, signal: AbortSignal) {
  const result = await request(`/v2/admin/reports/${id}/export?format=${format}`, { signal })
  if (!result.ok) {
    throw new ApiError(result.status, errors[result.status] ?? `Не вдалося завантажити звіт (HTTP ${result.status}).`)
  }
  const type = result.headers.get('Content-Type')?.split(';')[0].trim()
  if (type !== mediaTypes[format]) throw new Error('Сервер повернув файл у неочікуваному форматі.')
  const blob = await result.blob()
  if (signal.aborted) return
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `integrity-report-${id}.${format}`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
