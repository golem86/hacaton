import { useEffect, useRef, useState } from 'react'
import { downloadMaturityReport, type ReportFormat } from '../api/reports'

export const MATURITY_REPORT_FORMATS: readonly ReportFormat[] = ['pdf', 'xlsx']

/** Підпис кнопки: «Звіт зрілості PDF» / «Звіт зрілості XLSX». */
export function maturityReportLabel(format: ReportFormat) {
  return `Звіт зрілості ${format.toUpperCase()}`
}

/**
 * Кнопки звіту зрілості за Додатком В (GET /v2/admin/reports/{id}/maturity-export) — лише для адміністратора
 * і закритого циклу; сервер перевіряє роль і стан циклу сам, помилки (403/404/409/503) показуються людськими словами.
 */
export function MaturityReportButtons({ id }: { id: number }) {
  const [busy, setBusy] = useState<ReportFormat | null>(null)
  const [error, setError] = useState('')
  const download = useRef<AbortController | null>(null)

  useEffect(() => () => download.current?.abort(), [])

  async function save(format: ReportFormat) {
    if (download.current) return
    const controller = new AbortController()
    download.current = controller
    setError('')
    setBusy(format)
    try {
      await downloadMaturityReport(id, format, controller.signal)
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Не вдалося завантажити звіт зрілості.')
    } finally {
      download.current = null
      if (!controller.signal.aborted) setBusy(null)
    }
  }

  return (
    <div className="mp-report-export" role="group" aria-label="Звіт зрілості за Додатком В">
      <div className="v2-report__downloads">
        {MATURITY_REPORT_FORMATS.map(format => (
          <button key={format} type="button" className="v2-button" disabled={busy !== null}
                  onClick={() => void save(format)}>
            {maturityReportLabel(format)}
          </button>
        ))}
      </div>
      {busy && <p role="status">Готуємо звіт зрілості {busy.toUpperCase()}…</p>}
      {error && <p className="v2-auth-error" role="alert">{error}</p>}
    </div>
  )
}
