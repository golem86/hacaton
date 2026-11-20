import { useEffect, useRef, useState } from 'react'
import { getManagedAssessments, type Assessment } from '../api/assessments'
import { downloadCycleReport, getCycleReport, type ReportFormat } from '../api/reports'
import { getLmStatus } from '../api/narrative'
import { SuppressionNote } from '../dashboard/suppression'
import { CompareNarrative, CycleNarrative, type LmState } from './NarrativePanel'

type LoadState<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T }
type Report = Awaited<ReturnType<typeof getCycleReport>>
const countFormat = new Intl.NumberFormat('uk-UA')

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

export default function ReportsPanel() {
  const [cycles, setCycles] = useState<LoadState<Assessment[]>>({ status: 'loading' })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    getManagedAssessments(controller.signal).then(list => {
      if (controller.signal.aborted) return
      const closed = list.filter(cycle => cycle.status === 'closed')
      setCycles({ status: 'ready', data: closed })
      setSelectedId(closed[0]?.id ?? null)
    }).catch(error => {
      if (!controller.signal.aborted) {
        setCycles({ status: 'error', message: errorMessage(error, 'Не вдалося завантажити список циклів.') })
      }
    })
    return () => controller.abort()
  }, [attempt])

  const [lm, setLm] = useState<LmState>({ status: 'loading' })
  useEffect(() => {
    const controller = new AbortController()
    getLmStatus(controller.signal).then(data => {
      if (!controller.signal.aborted) setLm({ status: 'ready', data })
    }).catch(error => {
      if (!controller.signal.aborted) setLm({ status: 'error', message: errorMessage(error, 'сервер не відповів.') })
    })
    return () => controller.abort()
  }, [])

  return (
    <section className="v2-card v2-report" aria-labelledby="reports-title">
      <header>
        <h2 id="reports-title">Звіти за циклами</h2>
        <p className="v2-muted">Завантажте зведені результати закритого циклу у форматі PDF або XLSX.</p>
      </header>
      {cycles.status === 'loading' && <p role="status">Завантажуємо список циклів…</p>}
      {cycles.status === 'error' && (
        <div>
          <p role="alert">{cycles.message}</p>
          <button type="button" className="v2-button" onClick={() => {
            setCycles({ status: 'loading' })
            setAttempt(value => value + 1)
          }}>Спробувати ще раз</button>
        </div>
      )}
      {cycles.status === 'ready' && (cycles.data.length === 0
        ? <p>Поки немає закритих циклів для експорту.</p>
        : <label className="cycle-select">Закритий цикл
            <select value={selectedId ?? ''} onChange={event => setSelectedId(Number(event.target.value))}>
              {cycles.data.map(cycle => <option key={cycle.id} value={cycle.id}>{cycle.name}</option>)}
            </select>
          </label>)}
      {selectedId !== null && <ReportDownload key={selectedId} id={selectedId} lm={lm} />}
      {cycles.status === 'ready' && <CompareNarrative cycles={cycles.data} lm={lm} />}
    </section>
  )
}

function ReportDownload({ id, lm }: { id: number; lm: LmState }) {
  const [report, setReport] = useState<LoadState<Report>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [busy, setBusy] = useState<ReportFormat | null>(null)
  const [downloadError, setDownloadError] = useState('')
  const download = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getCycleReport(id, controller.signal).then(data => {
      if (!controller.signal.aborted) setReport({ status: 'ready', data })
    }).catch(error => {
      if (!controller.signal.aborted) {
        setReport({ status: 'error', message: errorMessage(error, 'Не вдалося завантажити звіт.') })
      }
    })
    return () => controller.abort()
  }, [id, attempt])

  useEffect(() => () => download.current?.abort(), [])

  async function save(format: ReportFormat) {
    if (download.current) return
    const controller = new AbortController()
    download.current = controller
    setDownloadError('')
    setBusy(format)
    try {
      await downloadCycleReport(id, format, controller.signal)
    } catch (error) {
      if (!controller.signal.aborted) setDownloadError(errorMessage(error, 'Не вдалося завантажити файл.'))
    } finally {
      download.current = null
      if (!controller.signal.aborted) setBusy(null)
    }
  }

  if (report.status === 'loading') return <p role="status">Готуємо дані звіту…</p>
  if (report.status === 'error') return (
    <div>
      <p role="alert">{report.message}</p>
      <button type="button" className="v2-button" onClick={() => {
        setReport({ status: 'loading' })
        setAttempt(value => value + 1)
      }}>Повторити запит</button>
    </div>
  )

  const { aggregates, exports } = report.data
  return (
    <>
      <dl className="v2-report__metrics">
        <div><dt>Анкет у циклі</dt><dd>{aggregates.responses_total === null ? 'Приховано' : countFormat.format(aggregates.responses_total)}</dd></div>
        <div><dt>Поріг групи</dt><dd>{aggregates.min_group_size}</dd></div>
      </dl>
      <p className="v2-muted">Малі групи приховано за тими самими правилами, що й в аналітиці.</p>
      {aggregates.suppressed && <SuppressionNote k={aggregates.min_group_size} className="v2-muted" />}
      <div className="v2-report__downloads">
        {(['pdf', 'xlsx'] as const).map(format => (
          <button key={format} type="button"
                  className={format === 'pdf' ? 'v2-button v2-button-primary' : 'v2-button'}
                  disabled={busy !== null || exports[format] !== 'available'}
                  onClick={() => void save(format)}>
            Завантажити {format.toUpperCase()}
          </button>
        ))}
      </div>
      {busy && <p role="status">Готуємо {busy.toUpperCase()}…</p>}
      {downloadError && <p className="v2-auth-error" role="alert">{downloadError}</p>}
      <CycleNarrative id={id} lm={lm} />
    </>
  )
}
