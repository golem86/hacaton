import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import Chart from 'chart.js/auto'
import type { ChartDataset } from 'chart.js'
import { ApiError } from '../api/client'
import {
  getComparisons, getIntegrityIndex, getMethodology, getRecommendations,
  type Comparisons, type IndexComponent, type IntegrityIndex, type Methodology, type Recommendation, type Recommendations,
} from '../api/analytics'
import type { Assessment } from '../api/assessments'
import type { AssessmentResults, ResultComponent } from './types'
import { DashboardSummary } from './DashboardSummary'
import { ComponentDetail, useComponentDetail } from './ComponentDetail'
import { scoreText } from './format'
import {
  describeScore, formatDeltaPoints, isScore, MATURITY_LEVELS, MATURITY_RULE_ID, maturityLevel, scoreZone,
  ZONE_META, ZONE_ORDER, ZoneBadge, zoneColor, ZoneLegend, zoneStyle,
} from './maturity'
import './dashboard.css'

export type OverviewRemote<T> =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string; httpStatus: number | null }
  | { status: 'success'; data: T }

type RemoteError = Extract<OverviewRemote<unknown>, { status: 'error' }>

export interface OverviewState {
  index: OverviewRemote<IntegrityIndex>
  methodology: OverviewRemote<Methodology>
  recommendations: OverviewRemote<Recommendations>
  comparisons: OverviewRemote<Comparisons>
  /** 'idle' when there is no previous closed cycle. */
  previousIndex: OverviewRemote<IntegrityIndex>
}

const DETAIL_ID = 'overview-component-detail'
const ANALYTICS_PATH = '/admin/analytics'
const LOADING = { status: 'loading' } as const

export function initialOverviewState(hasPrevious: boolean): OverviewState {
  return {
    index: LOADING, methodology: LOADING, recommendations: LOADING, comparisons: LOADING,
    previousIndex: hasPrevious ? LOADING : { status: 'idle' },
  }
}

/** Previous closed cycle in chronological order (start_date, then id); null for the first one. */
export function previousClosedCycle(assessments: Assessment[], id: number): Assessment | null {
  const closed = assessments
    .filter(item => item.status === 'closed')
    .sort((left, right) => left.start_date.localeCompare(right.start_date) || left.id - right.id)
  const position = closed.findIndex(item => item.id === id)
  return position > 0 ? closed[position - 1] : null
}

function failure(error: unknown): RemoteError {
  return {
    status: 'error',
    message: error instanceof Error ? error.message : 'Не вдалося завантажити аналітику.',
    httpStatus: error instanceof ApiError ? error.status : null,
  }
}

/** Starts the overview requests for one cycle. The returned function aborts them and ignores late answers. */
export function loadOverview(id: number, previousId: number | null, update: (patch: Partial<OverviewState>) => void): () => void {
  const controller = new AbortController()
  const { signal } = controller
  function settle<T>(request: Promise<T>, apply: (state: OverviewRemote<T>) => void) {
    request.then(
      data => { if (!signal.aborted) apply({ status: 'success', data }) },
      (error: unknown) => { if (!signal.aborted) apply(failure(error)) },
    )
  }
  update(initialOverviewState(previousId !== null))
  settle(getIntegrityIndex(id, signal), index => update({ index }))
  settle(getMethodology(signal), methodology => update({ methodology }))
  settle(getRecommendations(id, signal), recommendations => update({ recommendations }))
  settle(getComparisons(id, undefined, signal), comparisons => update({ comparisons }))
  if (previousId !== null) settle(getIntegrityIndex(previousId, signal), previousIndex => update({ previousIndex }))
  return () => controller.abort()
}

/** Same client-side navigation as go() in main.tsx. */
export function navigateTo(path: string) {
  history.pushState({}, '', path)
  window.dispatchEvent(new PopStateEvent('popstate'))
}

/** 503: demo analytics disabled on the server; 409: results do not fit the demo methodology. */
function disabledAnalytics(state: OverviewState): RemoteError | null {
  for (const remote of [state.index, state.recommendations, state.comparisons]) {
    if (remote.status === 'error' && (remote.httpStatus === 503 || remote.httpStatus === 409)) return remote
  }
  return null
}

function isRetryable(remote: RemoteError) {
  return remote.httpStatus !== 503 && remote.httpStatus !== 409
}

function formatIndex(value: number) {
  return value.toLocaleString('uk-UA', { maximumFractionDigits: 2 })
}

function approvalText(status: string | undefined) {
  if (status === 'proposed') return 'запропонована'
  return status ?? 'невідомий'
}

const pluralRules = new Intl.PluralRules('uk-UA')
function plural(count: number, one: string, few: string, many: string) {
  const rule = pluralRules.select(count)
  return rule === 'one' ? one : rule === 'few' ? few : many
}

function compareCodes(left: { code: string }, right: { code: string }) {
  return left.code.localeCompare(right.code, 'en', { numeric: true })
}

type ScoredComponent = ResultComponent & { score: number }

export interface ExecutiveOverviewProps {
  results: AssessmentResults
  assessments: Assessment[]
  /** Key indicator tiles; DashboardSummary by default. */
  kpis?: ReactNode
}

export function ExecutiveOverview(props: ExecutiveOverviewProps) {
  // A new cycle remounts the loader, so state of the previous cycle can never be shown for the next one.
  return <OverviewLoader key={props.results.assessment.id} {...props} />
}

function OverviewLoader({ results, assessments, kpis }: ExecutiveOverviewProps) {
  const id = results.assessment.id
  const previous = useMemo(() => previousClosedCycle(assessments, id), [assessments, id])
  const previousId = previous?.id ?? null
  const [state, setState] = useState<OverviewState>(() => initialOverviewState(previousId !== null))
  const [attempt, setAttempt] = useState(0)
  const detail = useComponentDetail()

  useEffect(() => loadOverview(id, previousId, patch => setState(current => ({ ...current, ...patch }))), [id, previousId, attempt])

  return <ExecutiveOverviewView results={results} previous={previous} state={state} kpis={kpis} selectedCode={detail.selected}
    onOpen={detail.open} onClose={detail.close} onRetry={() => setAttempt(value => value + 1)} onNavigate={navigateTo} />
}

export interface ExecutiveOverviewViewProps {
  results: AssessmentResults
  previous: Assessment | null
  state: OverviewState
  kpis?: ReactNode
  selectedCode?: string | null
  onOpen?: (code: string, trigger: HTMLElement | null) => void
  onClose?: () => void
  onRetry?: () => void
  onNavigate?: (path: string) => void
}

export function ExecutiveOverviewView({
  results, previous, state, kpis, selectedCode = null, onOpen = () => {}, onClose = () => {}, onRetry, onNavigate = navigateTo,
}: ExecutiveOverviewViewProps) {
  const components = useMemo(() => [...results.components].sort(compareCodes), [results.components])
  const index = state.index.status === 'success' ? state.index.data : null
  const proposals = state.recommendations.status === 'success' ? state.recommendations.data.proposals : null
  const previousRows = state.previousIndex.status === 'success' ? state.previousIndex.data.components : null
  const disabled = disabledAnalytics(state)

  const scored = components.filter((item): item is ScoredComponent => isScore(item.score))
  const strengths = scored.filter(item => scoreZone(item.score) === 'strength')
    .sort((left, right) => right.score - left.score || compareCodes(left, right)).slice(0, 3)
  const weak = scored.filter(item => scoreZone(item.score) === 'critical' || scoreZone(item.score) === 'problem')
    .sort((left, right) => left.score - right.score || compareCodes(left, right))
  const missing = components.filter(item => !isScore(item.score))
  const selected = components.find(item => item.code === selectedCode) ?? null

  const analyticsNote = disabled
    ? `Внесок в індекс і рекомендації недоступні: ${disabled.httpStatus === 503 ? 'аналітичний модуль вимкнено на сервері' : 'результати циклу не відповідають демонстраційній методиці'}.`
    : state.index.status === 'error' || state.recommendations.status === 'error' ? 'Внесок в індекс або рекомендації не вдалося завантажити.'
    : state.index.status === 'loading' || state.recommendations.status === 'loading' ? 'Завантажуємо Integrity Index і рекомендації…' : undefined
  const previousRow = selected && previousRows ? previousRows.find(row => row.code === selected.code) : undefined

  return (
    <div className="exec-overview">
      {disabled && (
        <div className="analytics-notice exec-notice" role="status">
          <strong>Integrity Index, рекомендації та сигнали розривів зараз недоступні. </strong>
          {disabled.httpStatus === 503
            ? 'Аналітичний модуль не ввімкнений у конфігурації сервера. '
            : 'Результати цього циклу не відповідають демонстраційній методиці (потрібні компоненти C1–C7 з її вагами). '}
          Зони, профіль C1–C7 і ключові показники нижче побудовано з агрегованих результатів циклу.
        </div>
      )}

      <div className="exec-hero">
        <IndexCard state={state} previous={previous} onRetry={onRetry} />
        <section className="exec-card exec-radar" aria-labelledby="exec-radar-heading">
          <p className="dashboard-kicker">Профіль C1–C7</p>
          <h3 id="exec-radar-heading">Компоненти за зонами</h3>
          {components.length === 0 ? <p className="exec-muted">Результатів компонентів для цього циклу немає.</p> : (
            <OverviewRadar components={components} previousName={previousRows && previous ? previous.name : null} previousRows={previousRows} />
          )}
        </section>
      </div>

      <ZoneLegend />

      <div className="exec-lists">
        <ZoneListCard id="exec-strengths-heading" title="Сильні сторони" kicker="Бал ≥ 75"
          empty="Компонентів у зоні «Сильна сторона» (бал ≥ 75) у цьому циклі немає."
          items={strengths} proposals={proposals} selectedCode={selectedCode} onOpen={onOpen} />
        <ZoneListCard id="exec-weak-heading" title="Проблемні та критичні зони" kicker="Бал < 50"
          empty="Компонентів із балом нижче 50 у цьому циклі немає."
          items={weak} proposals={proposals} selectedCode={selectedCode} onOpen={onOpen} />
      </div>
      {missing.length > 0 && (
        <p className="exec-muted exec-missing">
          Без бала (приховано або немає даних), зону не визначено:{' '}
          {missing.map((item, position) => <span key={item.code}>{position > 0 && ', '}
            <button type="button" className="exec-inline-button" aria-expanded={selectedCode === item.code} aria-controls={DETAIL_ID}
              onClick={event => onOpen(item.code, event.currentTarget)}>{item.code} · {item.name}</button>
          </span>)}
        </p>
      )}

      {selected && <ComponentDetail id={DETAIL_ID} component={selected} categories={results.categories}
        indexComponent={index?.components.find(row => row.code === selected.code)}
        recommendations={proposals ?? null}
        analyticsNote={analyticsNote}
        previous={previous && previousRows ? { name: previous.name, score: previousRow?.status === 'ok' ? previousRow.score : null } : null}
        onClose={onClose} />}

      <div className="exec-signals">
        <SignalCard id="exec-recommendations-heading" title="Рекомендації за правилами" remote={state.recommendations}
          count={proposals?.length ?? null}
          description="Пропозиції за явними правилами методики. Це не затверджений план: кожна потребує рішення людини."
          breakdown={proposals ? ruleBreakdown(proposals) : []}
          actionLabel="Переглянути рекомендації" onAction={() => onNavigate(ANALYTICS_PATH)} />
        <SignalCard id="exec-gaps-heading" title="Сигнали розривів між категоріями" remote={state.comparisons}
          count={state.comparisons.status === 'success' ? gapSignals(state.comparisons.data) : null}
          description="Пари видимих категорій із розривом ≥ 25 п.п. (правило CATEGORY_GAP_GE_25_V1). Сигнал для перегляду, не доказ порушень."
          breakdown={[]}
          actionLabel="Переглянути порівняння" onAction={() => onNavigate(ANALYTICS_PATH)} />
      </div>

      {kpis ?? <DashboardSummary results={results} />}

      <RulesDetails methodology={state.methodology.status === 'success' ? state.methodology.data : null} />
    </div>
  )
}

/** Only visible pairs count: an unavailable (suppressed) pair never becomes a signal. */
export function gapSignals(data: Comparisons): number {
  return data.category_comparisons.filter(item => item.status === 'ok' && item.flag === true).length
}

function ruleBreakdown(proposals: Recommendation[]): string[] {
  const counts = new Map<string, number>()
  proposals.forEach(item => counts.set(item.rule_id, (counts.get(item.rule_id) ?? 0) + 1))
  return [...counts].sort(([left], [right]) => left.localeCompare(right)).map(([rule, count]) => `${rule}: ${count}`)
}

function IndexCard({ state, previous, onRetry }: { state: OverviewState; previous: Assessment | null; onRetry?: () => void }) {
  const remote = state.index
  const index = remote.status === 'success' ? remote.data : null
  const methodology = state.methodology.status === 'success' ? state.methodology.data : null
  const value = index && index.status === 'ok' && isScore(index.index) ? index.index : null
  const zone = scoreZone(value)
  const level = maturityLevel(value)
  const version = index?.methodology_version ?? methodology?.version
  const approval = index?.approval_status ?? methodology?.approval_status
  const syntheticOnly = index?.synthetic_only ?? methodology?.synthetic_only

  let body: ReactNode
  if (remote.status === 'loading' || remote.status === 'idle') body = <p className="exec-muted" role="status">Завантажуємо індекс…</p>
  else if (remote.status === 'error') body = (
    <div className="exec-muted">
      <p>{remote.httpStatus === 503 ? 'Індекс не сформовано: аналітичний модуль вимкнено на сервері.'
        : remote.httpStatus === 409 ? 'Індекс не сформовано для цього циклу: результати не відповідають демонстраційній методиці.'
        : `Індекс недоступний. ${remote.message}`}</p>
      {isRetryable(remote) && onRetry && <button type="button" className="dashboard-action-button" onClick={onRetry}>Спробувати ще раз</button>}
    </div>
  )
  else if (value === null || level === null) body = <p className="exec-muted">Індекс недоступний: {index?.status === 'suppressed' ? 'дані приховано для захисту малих груп.' : 'бракує даних хоча б одного компонента.'}</p>
  else body = (
    <>
      <p className="exec-index-value"><strong>{formatIndex(value)}</strong><span>зі 100</span></p>
      <p className="exec-index-labels">
        <ZoneBadge zone={zone} />
        <span className="exec-level">Рівень зрілості {level.level} з 5 · {level.label} <small>({level.range})</small></span>
      </p>
    </>
  )

  return (
    <section className="exec-card exec-index" aria-labelledby="exec-index-heading" style={zoneStyle(zone)}>
      <div>
        <p className="dashboard-kicker">Integrity Index</p>
        <h3 id="exec-index-heading">Інтегральний показник циклу</h3>
      </div>
      {body}
      <IndexDelta current={value} previous={previous} remote={state.previousIndex} />
      <p className="exec-method">
        {version ? `Методика ${version}` : 'Методика індексу'} · демонстраційна методика, статус: {approvalText(approval)}
        {syntheticOnly ? ' · лише синтетичні дані' : ''}. Зону й рівень визначено за правилом команди, а не за офіційною шкалою.
      </p>
    </section>
  )
}

function IndexDelta({ current, previous, remote }: { current: number | null; previous: Assessment | null; remote: OverviewRemote<IntegrityIndex> }) {
  let content: ReactNode
  let note = false
  if (!previous) content = 'Попереднього закритого циклу немає.'
  else if (remote.status === 'loading' || remote.status === 'idle') content = `Завантажуємо індекс циклу «${previous.name}»…`
  else if (remote.status === 'error') content = `Індекс попереднього циклу «${previous.name}» недоступний.`
  else {
    const before = remote.data.status === 'ok' && isScore(remote.data.index) ? remote.data.index : null
    if (before === null) content = `Індекс попереднього циклу «${previous.name}» недоступний: бракує даних або їх приховано.`
    else if (current === null) content = `Зміну не обчислено: індекс цього циклу недоступний. Попередній цикл «${previous.name}»: ${formatIndex(before)} зі 100.`
    else {
      const delta = current - before
      const rounded = Math.round(delta * 100) / 100
      note = true
      content = <>
        <strong className="exec-delta-value">{formatDeltaPoints(delta)}</strong>{' '}
        {rounded > 0 ? 'зростання' : rounded < 0 ? 'зниження' : 'без змін'} порівняно з «{previous.name}» ({formatIndex(before)} → {formatIndex(current)})
      </>
    }
  }
  return (
    <div className="exec-delta">
      <span className="exec-delta-label">Порівняння з попереднім циклом</span>
      <p>{content}</p>
      {note && <small>Різниця округлених індексів. Зіставність циклів обмежена: різні вибірки, версії анкет не зафіксовано.</small>}
    </div>
  )
}

function OverviewRadar({ components, previousName, previousRows }: {
  components: ResultComponent[]
  previousName: string | null
  previousRows: IndexComponent[] | null
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const previousScores = useMemo(() => previousRows ? components.map(item => {
    const row = previousRows.find(candidate => candidate.code === item.code)
    return row && row.status === 'ok' && isScore(row.score) ? row.score : null
  }) : null, [components, previousRows])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const datasets: ChartDataset<'radar', (number | null)[]>[] = [{
      label: 'Цей цикл',
      data: components.map(item => isScore(item.score) ? item.score : null),
      borderColor: '#276456',
      backgroundColor: 'rgba(77, 149, 135, .16)',
      pointBackgroundColor: components.map(item => zoneColor(item.score)),
      pointBorderColor: '#ffffff',
      pointBorderWidth: 1.5,
      pointRadius: 6,
      pointHoverRadius: 8,
      borderWidth: 2,
      spanGaps: false,
    }]
    if (previousScores && previousName) datasets.push({
      label: `Попередній: ${previousName}`,
      data: previousScores,
      borderColor: '#7d8c88',
      borderDash: [6, 4],
      backgroundColor: 'transparent',
      pointBackgroundColor: '#7d8c88',
      pointRadius: 2.5,
      borderWidth: 1.5,
      spanGaps: false,
    })
    const chart = new Chart<'radar', (number | null)[]>(canvas, {
      type: 'radar',
      data: { labels: components.map(item => item.code), datasets },
      options: {
        animation: false,
        maintainAspectRatio: false,
        responsive: true,
        scales: {
          r: {
            min: 0,
            max: 100,
            beginAtZero: true,
            ticks: { stepSize: 25, showLabelBackdrop: false, color: '#526762', backdropColor: 'transparent' },
            grid: { color: '#dbe7e2' },
            angleLines: { color: '#dbe7e2' },
            pointLabels: { color: '#17302f', font: { size: 12, weight: 650 } },
          },
        },
        plugins: {
          legend: { display: datasets.length > 1, position: 'bottom', labels: { color: '#17302f', usePointStyle: true, pointStyle: 'circle', padding: 12 } },
          tooltip: {
            filter: item => item.raw !== null,
            callbacks: {
              title: items => {
                const item = components[items[0]?.dataIndex ?? -1]
                return item ? `${item.code} · ${item.name}` : ''
              },
              label: context => ` ${context.dataset.label}: ${scoreText(Number(context.raw))} · ${ZONE_META[scoreZone(Number(context.raw))].label}`,
            },
          },
        },
      },
    })
    return () => chart.destroy()
  }, [components, previousName, previousScores])

  return (
    <div className="chart-frame exec-radar-frame">
      <canvas ref={canvasRef} role="img" aria-label={`Радарна діаграма балів компонентів C1–C7 за шкалою 0–100; точки зафарбовано за зонами${previousScores ? '; пунктиром показано попередній закритий цикл' : ''}. Значення наведено у списку.`} />
      <ul className="sr-only">{components.map((item, position) => (
        <li key={item.code}>
          {item.code}, {item.name}: {scoreText(item.score)}; {describeScore(item.score)}
          {previousScores && `; попередній цикл: ${scoreText(previousScores[position])}`}
        </li>
      ))}</ul>
    </div>
  )
}

function ZoneListCard({ id, title, kicker, empty, items, proposals, selectedCode, onOpen }: {
  id: string
  title: string
  kicker: string
  empty: string
  items: ScoredComponent[]
  proposals: Recommendation[] | null
  selectedCode: string | null
  onOpen: (code: string, trigger: HTMLElement | null) => void
}) {
  return (
    <section className="exec-card" aria-labelledby={id}>
      <p className="dashboard-kicker">{kicker}</p>
      <h3 id={id}>{title}</h3>
      {items.length === 0 ? <p className="exec-muted exec-list-empty">{empty}</p> : (
        <ul className="exec-zone-list">
          {items.map(item => {
            const zone = scoreZone(item.score)
            const count = proposals?.filter(proposal => proposal.component_code === item.code).length ?? 0
            return (
              <li key={item.code}>
                <button type="button" className="exec-zone-item" style={zoneStyle(zone)} aria-expanded={selectedCode === item.code} aria-controls={DETAIL_ID}
                  onClick={event => onOpen(item.code, event.currentTarget)}>
                  <span className="exec-zone-main"><span className="dashboard-code">{item.code}</span><span>{item.name}</span></span>
                  <span className="exec-zone-meta">
                    <strong>{scoreText(item.score)}</strong>
                    <ZoneBadge zone={zone} short />
                    {count > 0 && <small>{count} {plural(count, 'рекомендація', 'рекомендації', 'рекомендацій')}</small>}
                  </span>
                  <span className="sr-only">: відкрити деталізацію</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function SignalCard({ id, title, remote, count, description, breakdown, actionLabel, onAction }: {
  id: string
  title: string
  remote: OverviewRemote<unknown>
  count: number | null
  description: string
  breakdown: string[]
  actionLabel: string
  onAction: () => void
}) {
  return (
    <section className="exec-card exec-signal" aria-labelledby={id}>
      <h3 id={id}>{title}</h3>
      {remote.status === 'success' && count !== null
        ? <p className="exec-signal-value">{count.toLocaleString('uk-UA')}</p>
        : remote.status === 'error'
          ? <p className="exec-signal-value exec-signal-unavailable">Недоступно</p>
          : <p className="exec-signal-value exec-signal-unavailable" role="status">Завантаження…</p>}
      <p className="exec-muted">{description}</p>
      {breakdown.length > 0 && <ul className="exec-breakdown" aria-label="За правилами">{breakdown.map(item => <li key={item}>{item}</li>)}</ul>}
      <button type="button" className="dashboard-action-button" onClick={onAction}>{actionLabel}</button>
    </section>
  )
}

function RulesDetails({ methodology }: { methodology: Methodology | null }) {
  return (
    <details className="exec-rules">
      <summary>Як визначено зони, рівні зрілості та індекс</summary>
      <p>
        Демонстраційне правило команди <code>{MATURITY_RULE_ID}</code>, не офіційна шкала. Нижня межа діапазону включна, верхня — ні.
        Межа «менше 50» збігається з правилом рекомендацій LOW_SCORE_LT_50_V1. Приховані або відсутні бали не стають нулем і не отримують зони.
      </p>
      <div className="exec-rules-grid">
        <table className="exec-rules-table">
          <caption>Зони</caption>
          <thead><tr><th scope="col">Зона</th><th scope="col">Бал</th></tr></thead>
          <tbody>{ZONE_ORDER.map(zone => <tr key={zone}><td><ZoneBadge zone={zone} /></td><td>{ZONE_META[zone].range}</td></tr>)}</tbody>
        </table>
        <table className="exec-rules-table">
          <caption>Рівні зрілості</caption>
          <thead><tr><th scope="col">Рівень</th><th scope="col">Бал</th></tr></thead>
          <tbody>{MATURITY_LEVELS.map(level => <tr key={level.level}><td>{level.level} · {level.label}</td><td>{level.range}</td></tr>)}</tbody>
        </table>
      </div>
      {methodology && (
        <>
          <p>
            Integrity Index за методикою {methodology.version} (статус: {approvalText(methodology.approval_status)}): <code>{methodology.formula}</code>.
            {' '}Ваги: {Object.entries(methodology.weights).sort(([left], [right]) => left.localeCompare(right, 'en', { numeric: true }))
              .map(([code, weight]) => `${code} ${weight}`).join(' · ')}.
          </p>
          {methodology.limitations.length > 0 && <ul>{methodology.limitations.map(item => <li key={item}>{item}</li>)}</ul>}
        </>
      )}
    </details>
  )
}
