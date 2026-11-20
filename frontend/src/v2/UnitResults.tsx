import { useEffect, useId, useState } from 'react'
import { getAssessments, type Assessment } from '../api/assessments'
import { ApiError } from '../api/client'
import { getUnitResults, type UnitComponentStatus, type UnitResults } from '../api/v2User'

/** Закриті цикли від найстарішого до найновішого (за start_date, далі за id). */
export function closedCycles(assessments: Assessment[]): Assessment[] {
  return assessments
    .filter((assessment) => assessment.status === 'closed')
    .sort((a, b) => a.start_date.localeCompare(b.start_date) || a.id - b.id)
}

export function formatUnitScore(value: number | null) {
  return value == null ? '—' : value.toLocaleString('uk-UA', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

const COMPONENT_STATUS_LABEL: Readonly<Record<Exclude<UnitComponentStatus, 'available'>, string>> = {
  suppressed: 'Приховано для захисту анонімності',
  insufficient_data: 'Недостатньо даних',
}

const pluralRules = new Intl.PluralRules('uk-UA')
function responsesLabel(count: number) {
  const form = pluralRules.select(count)
  return form === 'one' ? 'відповідь' : form === 'few' ? 'відповіді' : 'відповідей'
}

/** Відображення відповіді /v2/user/unit-results для трьох станів приватності. */
export function UnitResultsView({ result }: { result: UnitResults }) {
  const headingId = useId()

  if (result.privacy_status === 'no_unit') {
    return (
      <div className="v2-unit-notice" role="status">
        <strong>Підрозділ не призначено</strong>
        <p>Підрозділ користувачу призначає лише власник сервера. Зверніться до адміністратора, щоб вас додали до підрозділу; самостійно змінити його не можна.</p>
      </div>
    )
  }

  if (result.privacy_status === 'suppressed') {
    return (
      <div className="v2-unit-notice" role="status">
        <strong>Результати приховано для захисту анонімності</strong>
        <p>Підрозділ «{result.unit}»: група замала (менше ніж {result.min_group_size} відповідей) або показ результатів дозволив би обчислити дані інших груп. Тому агрегати за цей цикл не показуються.</p>
      </div>
    )
  }

  const responses = result.responses ?? 0
  return (
    <>
      <div className="v2-stat-grid v2-unit-summary">
        <div><span>Підрозділ</span><strong>{result.unit}</strong></div>
        <div><span>Кількість відповідей (округлено вниз до 5)</span><strong>≥ {responses}<small> {responsesLabel(responses)}</small></strong></div>
        <div><span>Шкала</span><strong>0–100</strong></div>
      </div>
      {result.components.length ? (
        <div className="v2-unit-table-wrap">
          <table className="v2-unit-table" aria-labelledby={headingId}>
            <caption id={headingId}>Компоненти C1–C7 · середнє по підрозділу, шкала 0–100</caption>
            <thead><tr><th scope="col">Код</th><th scope="col">Компонент</th><th scope="col">Бал</th><th scope="col"><span className="v2-unit-sr-only">Візуалізація</span></th></tr></thead>
            <tbody>
              {result.components.map((component) => (
                <tr key={component.code}>
                  <th scope="row">{component.code}</th>
                  <td>{component.name}</td>
                  {component.status === 'available' && component.score != null ? (
                    <>
                      <td className="v2-unit-score">{formatUnitScore(component.score)}</td>
                      <td><div className="v2-mini-track v2-unit-bar" aria-hidden="true"><i style={{ width: `${Math.min(100, Math.max(0, component.score))}%` }} /></div></td>
                    </>
                  ) : (
                    <td colSpan={2} className="v2-muted">{COMPONENT_STATUS_LABEL[component.status === 'available' ? 'insufficient_data' : component.status]}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <div className="v2-empty"><strong>Немає даних за компонентами</strong></div>}
      <p className="v2-muted v2-unit-footnote">Показано лише агреговані значення по підрозділу; це не оцінка окремих осіб. Методика: {result.methodology_version}; мінімальний розмір групи — {result.min_group_size}.</p>
    </>
  )
}

type CyclesState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; list: Assessment[] }
type ResultState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'pending' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: UnitResults }

function errorMessage(error: unknown, fallback: string) {
  // Повідомлення ApiError формуються на клієнті (за статусом), тож серверний detail сюди не потрапляє.
  return error instanceof ApiError ? error.message : fallback
}

/** «Результати підрозділу»: вибір закритого циклу й агрегати підрозділу користувача. */
export function UnitResultsScreen() {
  const selectId = useId()
  const [cycles, setCycles] = useState<CyclesState>({ status: 'loading' })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [result, setResult] = useState<ResultState>({ status: 'idle' })
  const [cyclesRetry, setCyclesRetry] = useState(0)
  const [resultRetry, setResultRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setCycles({ status: 'loading' })
    getAssessments(controller.signal)
      .then((list) => {
        const closed = closedCycles(list)
        setCycles({ status: 'ready', list: closed })
        setSelectedId((current) => closed.some((cycle) => cycle.id === current) ? current : closed.at(-1)?.id ?? null)
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setCycles({ status: 'error', message: errorMessage(error, 'Не вдалося завантажити цикли оцінювання.') })
      })
    return () => controller.abort()
  }, [cyclesRetry])

  useEffect(() => {
    if (selectedId == null) { setResult({ status: 'idle' }); return }
    const controller = new AbortController()
    setResult({ status: 'loading' })
    getUnitResults(selectedId, controller.signal)
      .then((data) => setResult({ status: 'ready', data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 409) setResult({ status: 'pending' })
        else setResult({ status: 'error', message: errorMessage(error, 'Не вдалося завантажити результати підрозділу.') })
      })
    return () => controller.abort()
  }, [selectedId, resultRetry])

  const selected = cycles.status === 'ready' ? cycles.list.find((cycle) => cycle.id === selectedId) : undefined

  return (
    <section className="v2-card v2-unit-results" aria-labelledby={`${selectId}-heading`} aria-busy={cycles.status === 'loading' || result.status === 'loading'}>
      <div className="v2-section-heading">
        <div><p className="v2-overline">Захищені агрегати</p><h2 id={`${selectId}-heading`}>Результати підрозділу</h2></div>
        <span className="v2-pill">Лише агрегати</span>
      </div>

      {cycles.status === 'loading' && <p className="v2-muted" role="status">Завантажуємо цикли оцінювання…</p>}
      {cycles.status === 'error' && (
        <div className="v2-empty" role="alert">
          <strong>Не вдалося завантажити цикли</strong>
          <p>{cycles.message}</p>
          <button className="v2-button" type="button" onClick={() => setCyclesRetry((value) => value + 1)}>Спробувати ще раз</button>
        </div>
      )}
      {cycles.status === 'ready' && cycles.list.length === 0 && (
        <div className="v2-empty" role="status"><strong>Закритих циклів поки немає</strong><p>Результати підрозділу з’являться після закриття циклу оцінювання.</p></div>
      )}

      {cycles.status === 'ready' && cycles.list.length > 0 && (
        <>
          <div className="v2-unit-field">
            <label htmlFor={selectId}>Закритий цикл</label>
            <select id={selectId} value={selectedId ?? ''} onChange={(event) => setSelectedId(Number(event.target.value) || null)}>
              {[...cycles.list].reverse().map((cycle) => <option key={cycle.id} value={cycle.id}>{cycle.name} · {cycle.start_date}</option>)}
            </select>
          </div>

          <div aria-live="polite">
            {result.status === 'loading' && <p className="v2-muted" role="status">Завантажуємо результати{selected ? ` за «${selected.name}»` : ''}…</p>}
            {result.status === 'pending' && (
              <div className="v2-unit-notice" role="status"><strong>Цикл ще не закрито</strong><p>Результати з’являться після закриття циклу.</p></div>
            )}
            {result.status === 'error' && (
              <div className="v2-empty" role="alert">
                <strong>Не вдалося завантажити результати</strong>
                <p>{result.message}</p>
                <button className="v2-button" type="button" onClick={() => setResultRetry((value) => value + 1)}>Спробувати ще раз</button>
              </div>
            )}
            {result.status === 'ready' && <UnitResultsView result={result.data} />}
          </div>
        </>
      )}
    </section>
  )
}
