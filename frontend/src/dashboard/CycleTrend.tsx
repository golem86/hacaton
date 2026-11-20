import { useEffect, useMemo, useRef, useState } from 'react'
import Chart from 'chart.js/auto'
import { ApiError } from '../api/client'
import type { Assessment } from '../api/assessments'
import { getAssessmentResults } from './results'
import type { AssessmentResults, ResultComponent } from './types'
import type { RemoteState } from './AnalyticsModules'
import './dashboard.css'

const componentColors = ['#245f52', '#3b7a70', '#639780', '#9b8a4f', '#547b9b', '#9b6656', '#78729b']

function cycleLabel(item: Assessment) {
  const date = new Intl.DateTimeFormat('uk-UA', { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(`${item.start_date}T00:00:00Z`))
  return `${item.name} · ${date}`
}

function shortCycleLabels(cycles: Assessment[]) {
  const totals = new Map<string, number>()
  cycles.forEach(cycle => {
    const year = cycle.start_date.slice(0, 4)
    totals.set(year, (totals.get(year) ?? 0) + 1)
  })
  const seen = new Map<string, number>()
  return cycles.map(cycle => {
    const year = cycle.start_date.slice(0, 4)
    const ordinal = (seen.get(year) ?? 0) + 1
    seen.set(year, ordinal)
    return (totals.get(year) ?? 0) > 1 ? `${year} · ${ordinal}` : year
  })
}

function useTrend(assessments: Assessment[]) {
  const candidates = useMemo(() => assessments
    .filter(item => item.status === 'closed')
    .sort((left, right) => left.start_date.localeCompare(right.start_date) || left.id - right.id)
    .slice(-12), [assessments])
  const key = candidates.map(item => item.id).join(',')
  const [state, setState] = useState<RemoteState<{ cycles: Assessment[]; results: AssessmentResults[] }>>({ status: 'loading' })
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setState({ status: 'loading' })
    Promise.all(candidates.map(item => getAssessmentResults(item.id, controller.signal)))
      .then(results => { if (!controller.signal.aborted) setState({ status: 'success', data: { cycles: candidates, results } }) })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setState({ status: 'error', message: error instanceof Error ? error.message : 'Не вдалося завантажити динаміку.', retryable: !(error instanceof ApiError && error.status === 503) })
      })
    return () => controller.abort()
  }, [key, retry])

  return { state, retry: () => setRetry(value => value + 1) }
}

export function CycleTrend({ assessments, selectedId }: { assessments: Assessment[]; selectedId: number }) {
  const { state, retry } = useTrend(assessments)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const series = useMemo(() => {
    if (state.status !== 'success') return []
    const components = new Map<string, string>()
    state.data.results.forEach(result => result.components.forEach(component => components.set(component.code, component.name)))
    const codes = [...components.keys()].sort((left, right) => left.localeCompare(right, 'en', { numeric: true }))
    return codes.map((code, index) => ({
      code,
      name: components.get(code) ?? code,
      color: componentColors[index % componentColors.length],
      values: state.data.results.map(result => result.components.find(component => component.code === code)?.score ?? null),
    }))
  }, [state])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || state.status !== 'success' || state.data.cycles.length < 2 || series.length === 0) return
    const chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels: shortCycleLabels(state.data.cycles),
        datasets: series.map(item => ({
          label: item.code,
          data: item.values,
          borderColor: item.color,
          backgroundColor: item.color,
          pointBackgroundColor: item.color,
          pointBorderColor: state.data.cycles.map(cycle => cycle.id === selectedId ? '#163b35' : '#ffffff'),
          pointBorderWidth: state.data.cycles.map(cycle => cycle.id === selectedId ? 2 : 1),
          pointRadius: state.data.cycles.map(cycle => cycle.id === selectedId ? 5 : 3),
          pointHoverRadius: 7,
          borderWidth: 2,
          tension: 0.2,
          spanGaps: false,
        })),
      },
      options: {
        animation: false,
        maintainAspectRatio: false,
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { grid: { display: false }, ticks: { color: '#526762', maxRotation: 0, minRotation: 0, autoSkip: true, maxTicksLimit: 6 } },
          y: { min: 0, max: 100, grid: { color: '#e4ece8' }, ticks: { stepSize: 25, color: '#526762' } },
        },
        plugins: {
          legend: { position: 'bottom', labels: { color: '#17302f', usePointStyle: true, pointStyle: 'circle', padding: 12 } },
          tooltip: {
            filter: item => item.raw !== null,
            callbacks: {
              title: items => {
                const cycle = state.status === 'success' ? state.data.cycles[items[0]?.dataIndex ?? -1] : undefined
                return cycle ? cycleLabel(cycle) : ''
              },
              label: context => {
                const component = series[context.datasetIndex]
                return ` ${component?.code} · ${component?.name}: ${Number(context.raw).toLocaleString('uk-UA', { maximumFractionDigits: 1 })} зі 100`
              },
            },
          },
        },
      },
    })
    return () => chart.destroy()
  }, [selectedId, series, state])

  return (
    <section className="dashboard-panel" aria-labelledby="cycle-trend-heading">
      <div className="dashboard-panel-heading"><div><p className="dashboard-kicker">Закриті цикли</p><h2 id="cycle-trend-heading">Динаміка компонентів</h2><p className="dashboard-panel-description">Хронологічне зіставлення доступних агрегатів. Відсутні або приховані значення не підміняються нулями.</p></div></div>
      {state.status === 'loading' && <p role="status" className="dashboard-empty">Завантажуємо агрегати закритих циклів…</p>}
      {state.status === 'error' && <div className="dashboard-chart-error" role="alert"><p>{state.message}</p>{state.retryable !== false && <button type="button" className="dashboard-action-button" onClick={retry}>Спробувати ще раз</button>}</div>}
      {state.status === 'success' && state.data.cycles.length < 2 && <p className="dashboard-empty">Для графіка динаміки потрібні щонайменше два закриті цикли. Зараз доступно: {state.data.cycles.length}.</p>}
      {state.status === 'success' && state.data.cycles.length >= 2 && series.length === 0 && <p className="dashboard-empty">API не повернув компонентів для зіставлення.</p>}
      {state.status === 'success' && state.data.cycles.length >= 2 && series.length > 0 && <>
        <div className="chart-frame trend-chart-frame"><canvas ref={canvasRef} role="img" aria-label="Лінійний графік балів компонентів за закритими циклами у хронологічному порядку, фіксована шкала 0–100. Короткі підписи осі показують рік; повні назви циклів і компонентів наведено в таблиці й підказках." /></div>
        <p className="dashboard-scroll-cue">На телефоні прокрутіть таблицю горизонтально, щоб побачити всі цикли →</p>
        <div className="dashboard-table-scroll" role="region" aria-label="Доступні значення динаміки, таблиця" tabIndex={0}>
          <table className="dashboard-table dashboard-trend-table"><caption>Бали компонентів за закритими циклами; вибраний цикл позначено.</caption>
            <thead><tr><th scope="col">Компонент</th>{state.data.cycles.map(cycle => <th scope="col" key={cycle.id} aria-current={cycle.id === selectedId ? 'true' : undefined}>{cycleLabel(cycle)}{cycle.id === selectedId && <small>Вибраний цикл</small>}</th>)}</tr></thead>
            <tbody>{series.map(component => <tr key={component.code}><th scope="row"><span className="dashboard-code">{component.code}</span> {component.name}</th>{state.data.results.map(result => {
              const item: ResultComponent | undefined = result.components.find(value => value.code === component.code)
              return <td key={result.assessment.id}>{item ? item.score === null ? 'Недоступно: приховано або немає даних' : `${item.score.toLocaleString('uk-UA', { maximumFractionDigits: 1 })} зі 100` : 'Немає даних'}</td>
            })}</tr>)}</tbody>
          </table>
        </div>
        <p className="dashboard-chart-note">Шкала 0–100. Маркери легенди відповідають кольорам серій; виділене кільце позначає вибраний цикл. Повні назви циклів наведено в таблиці й підказках. Порівняння циклів може мати обмежену зіставність відповідно до методики.</p>
      </>}
    </section>
  )
}
