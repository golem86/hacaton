import { useEffect, useId, useState } from 'react'
import { getUnitResults, type UnitComponentResult, type UnitResults } from '../api/v2User'

/** Бал компонента 0–100 з одним знаком після коми за українським форматом (72,5). */
export function formatUnitScore(value: number | null | undefined) {
  return value == null ? '—' : value.toLocaleString('uk-UA', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

/** Пояснення для статусу без показу балів; для «available» — null. */
export function unitResultsNotice(data: Pick<UnitResults, 'status' | 'min_group_size'>): { title: string; text: string } | null {
  if (data.status === 'no_unit') return { title: 'Підрозділ ще не призначено. Його призначає власник сервера', text: 'Щойно власник сервера призначить вам підрозділ, тут з’являться його агреговані результати.' }
  if (data.status === 'no_closed_cycle') return { title: 'Ще немає закритих циклів', text: 'Результати підрозділу показуються лише після закриття циклу оцінювання.' }
  if (data.status === 'insufficient_data') return { title: 'Недостатньо анкет для показу (менше k)', text: `Щоб захистити анонімність, результати підрозділу, де анкет менше ніж k = ${data.min_group_size}, не показуються.` }
  return null
}

function componentValue(component: UnitComponentResult, k: number) {
  if (component.status === 'suppressed') return <span className="v2-unit-results__hidden" title={`Менше ніж k = ${k} відповідей`}>Приховано (менше k)</span>
  if (component.status === 'insufficient_data' || component.score == null) return <span className="v2-unit-results__hidden">Недостатньо даних</span>
  return <strong>{formatUnitScore(component.score)}<small> / 100</small></strong>
}

export interface UnitResultsViewProps {
  data: UnitResults
  /** Вибраний цикл; null — найновіший закритий (його повертає сервер). */
  selectedId?: number | null
  onSelect?: (assessmentId: number) => void
  busy?: boolean
}

/** Захищені агрегати підрозділу: без розрізів за категорією та без індивідуальних відповідей. */
export function UnitResultsView({ data, selectedId = null, onSelect, busy = false }: UnitResultsViewProps) {
  const id = useId()
  const notice = unitResultsNotice(data)
  const k = data.min_group_size
  const currentId = selectedId ?? data.assessment?.id ?? ''
  return (
    <section className="v2-card v2-unit-results" aria-labelledby={`${id}-title`} aria-busy={busy || undefined}>
      <div className="v2-section-heading">
        <div><p className="v2-overline">Захищені агрегати</p><h2 id={`${id}-title`}>Результати підрозділу</h2></div>
        <span className="v2-pill">{data.unit ? data.unit.name : 'Підрозділ не призначено'}</span>
      </div>
      {/* Без підрозділу вибір циклу нічого не змінює: сервер для будь-якого закритого циклу поверне no_unit. */}
      {data.status !== 'no_unit' && data.available_assessments.length > 0 && (
        <label className="cycle-select v2-unit-results__cycle">Цикл оцінювання
          <select value={currentId} disabled={busy} onChange={(event) => { const next = Number(event.target.value); if (next > 0) onSelect?.(next) }}>
            {data.available_assessments.map((assessment) => <option key={assessment.id} value={assessment.id}>{assessment.name}</option>)}
          </select>
        </label>
      )}
      <dl className="v2-unit-results__meta">
        <div><dt>Підрозділ</dt><dd>{data.unit?.name ?? '—'}</dd></div>
        <div><dt>Цикл</dt><dd>{data.assessment?.name ?? '—'}</dd></div>
        <div><dt>Мінімальний розмір групи (k)</dt><dd>{k || '—'}</dd></div>
        <div><dt>Респондентів</dt><dd>{data.status === 'available' && data.respondents != null ? data.respondents : '—'}</dd></div>
      </dl>
      {notice ? (
        <div className="v2-empty v2-unit-results__notice" role="status" data-status={data.status}><strong>{notice.title}</strong><p className="v2-muted">{notice.text}</p></div>
      ) : data.components.length ? (
        <ul className="v2-unit-results__components" aria-label="Бали компонентів C1–C7">
          {data.components.map((component) => (
            <li key={component.code} className="v2-unit-results__component" data-status={component.status}>
              <span className="v2-unit-results__code">{component.code}</span>
              <span className="v2-unit-results__name">{component.name || component.code}</span>
              {componentValue(component, k)}
            </li>
          ))}
        </ul>
      ) : (
        <div className="v2-empty v2-unit-results__notice" role="status"><strong>Компоненти не розраховано</strong><p className="v2-muted">Для цього циклу сервер не повернув балів компонентів.</p></div>
      )}
      <p className="v2-inline-note">
        Бали 0–100 за методикою адміністративної аналітики{data.methodology_version ? ` (версія ${data.methodology_version})` : ''}. Компонент із менш ніж k відповідями приховано. Індивідуальні відповіді та інші підрозділи не показуються.
      </p>
    </section>
  )
}

/** Завантажує результати підрозділу; 401 обробляє застосунок (повернення на вхід), інші помилки — зрозумілим текстом. */
export function UnitResultsPanel() {
  const [data, setData] = useState<UnitResults | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    getUnitResults(selectedId, controller.signal)
      .then((next) => { setData(next) })
      .catch((nextError: unknown) => {
        if (!controller.signal.aborted) setError(nextError instanceof Error ? nextError.message : 'Не вдалося завантажити результати підрозділу.')
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [selectedId, retry])

  if (error) {
    return <div className="v2-empty" role="alert"><strong>Не вдалося завантажити результати підрозділу</strong><p className="v2-muted">{error}</p><button className="v2-button" type="button" onClick={() => setRetry((value) => value + 1)}>Спробувати ще раз</button>{selectedId !== null && <button className="v2-button v2-button-quiet" type="button" onClick={() => setSelectedId(null)}>Останній закритий цикл</button>}</div>
  }
  if (!data) return <section className="v2-card" role="status">Завантажуємо результати підрозділу…</section>
  return <UnitResultsView data={data} selectedId={selectedId} onSelect={setSelectedId} busy={loading} />
}
