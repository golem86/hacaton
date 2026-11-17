import { useEffect, useState, type ReactNode } from 'react'
import {
  getComparisons, getIntegrityIndex, getMethodology, getRecommendations,
  type Comparisons, type IntegrityIndex, type Methodology, type Recommendations,
} from '../api/analytics'
import type { Assessment } from '../api/assessments'
import { categoryName } from './format'
import './dashboard.css'

export type RemoteState<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'success'; data: T }

export interface KeyedRemoteState<T> {
  key: string
  state: RemoteState<T>
}

export function visibleRemoteState<T>(stored: KeyedRemoteState<T>, key: string): RemoteState<T> {
  return stored.key === key ? stored.state : { status: 'loading' }
}

export function canShowAnalytics(
  assessment: Assessment | null,
  selectedId: number | null,
  detailLoading: boolean,
  detailError: string,
): assessment is Assessment {
  return !detailLoading && !detailError && assessment?.id === selectedId && assessment.status === 'closed'
}

/** Abort the request and ignore a late response even if fetch does not honor abort. */
export function loadAnalytics<T>(
  request: (signal: AbortSignal) => Promise<T>,
  onState: (state: RemoteState<T>) => void,
): () => void {
  const controller = new AbortController()
  onState({ status: 'loading' })
  request(controller.signal)
    .then(data => {
      if (!controller.signal.aborted) onState({ status: 'success', data })
    })
    .catch((error: unknown) => {
      if (!controller.signal.aborted) onState({
        status: 'error',
        message: error instanceof Error ? error.message : 'Не вдалося завантажити аналітику.',
      })
    })
  return () => controller.abort()
}

function useRemote<T>(request: (signal: AbortSignal) => Promise<T>, key: string) {
  const [stored, setStored] = useState<KeyedRemoteState<T>>({ key, state: { status: 'loading' } })
  const [retry, setRetry] = useState(0)
  const requestKey = `${key}:${retry}`
  useEffect(() => loadAnalytics(request, state => setStored({ key: requestKey, state })), [requestKey])
  return { state: visibleRemoteState(stored, requestKey), retry: () => setRetry(value => value + 1) }
}

export function ModuleState<T>({ state, retry, children }: {
  state: RemoteState<T>
  retry: () => void
  children: (data: T) => ReactNode
}) {
  if (state.status === 'loading') return <p role="status">Завантажуємо аналітику…</p>
  if (state.status === 'error') return (
    <div role="alert">
      <p>{state.message}</p>
      <button type="button" onClick={retry}>Спробувати ще раз</button>
    </div>
  )
  return <>{children(state.data)}</>
}

export function DemoNotice({ approvalStatus, syntheticOnly, official }: {
  approvalStatus: string
  syntheticOnly: boolean
  official: boolean
}) {
  return (
    <p className="analytics-notice">
      {approvalStatus === 'proposed' && 'Методика має статус «запропонована». '}
      {syntheticOnly && 'Лише для синтетичних даних; результати не є реальним оцінюванням. '}
      {!official && 'Неофіційна демонстраційна методика.'}
    </p>
  )
}

function IndexPanel({ id }: { id: number }) {
  const { state, retry } = useRemote(
    (signal) => Promise.all([getIntegrityIndex(id, signal), getMethodology(signal)]),
    `index:${id}`,
  )
  return (
    <section className="dashboard-panel" aria-labelledby="index-heading">
      <h2 id="index-heading">Integrity Index</h2>
      <ModuleState state={state} retry={retry}>{([index, methodology]: [IntegrityIndex, Methodology]) =>
        <IndexContent index={index} methodology={methodology} />}</ModuleState>
    </section>
  )
}

export function IndexContent({ index, methodology }: { index: IntegrityIndex; methodology: Methodology }) {
  return (
    <>
      <DemoNotice approvalStatus={index.approval_status} syntheticOnly={index.synthetic_only} official={index.official} />
          <p>Версія методики: {index.methodology_version}. Формула: {methodology.formula}.</p>
          {index.status !== 'ok' || index.index === null
            ? <p>Індекс недоступний: {index.status === 'suppressed' ? 'дані приховано для захисту групи.' : 'бракує даних.'}</p>
            : <p className="analytics-number">{index.index.toLocaleString('uk-UA')} зі 100</p>}
          <h3>Складові</h3>
          {index.components.length === 0
            ? <p>Складових поки немає.</p>
            : <ul>{index.components.map(item => (
              <li key={item.code}>
                <strong>{item.code} · {item.name}</strong>{' '}
                {item.status === 'ok' && item.score !== null && item.contribution !== null
                  ? `— ${item.score.toLocaleString('uk-UA')} зі 100; вага ${item.weight}; внесок ${item.contribution.toLocaleString('uk-UA')}`
                  : '— немає доступного бала'}
              </li>
            ))}</ul>}
          <details>
            <summary>Методика та обмеження</summary>
            <p>Статус: {methodology.approval_status}; версія: {methodology.version}.</p>
            <ul>{methodology.limitations.map(item => <li key={item}>{item}</li>)}</ul>
          </details>
    </>
  )
}

function RecommendationsPanel({ id }: { id: number }) {
  const { state, retry } = useRemote(signal => getRecommendations(id, signal), `recommendations:${id}`)
  return (
    <section className="dashboard-panel" aria-labelledby="recommendations-heading">
      <h2 id="recommendations-heading">Recommendations</h2>
      <ModuleState state={state} retry={retry}>{(data: Recommendations) =>
        <RecommendationsContent data={data} />}</ModuleState>
    </section>
  )
}

export function RecommendationsContent({ data }: { data: Recommendations }) {
  return (
    <>
          <p className="analytics-notice">Пропозиції за синтетичною демометодикою {data.methodology_version} ({data.approval_status}). Потребують рішення людини; не є затвердженим планом.</p>
          {data.proposals.length === 0
            ? <p>Рекомендацій за поточними правилами немає.</p>
            : <ul>{data.proposals.map(item => (
              <li key={item.id}><strong>{item.component_code} · {item.rule_id}</strong> — {item.text}</li>
            ))}</ul>}
    </>
  )
}

function ComparisonsPanel({ id, assessments }: { id: number; assessments: Assessment[] }) {
  const [selection, setSelection] = useState<{ id?: number; revision: number }>({ revision: 0 })
  const comparisonId = selection.id
  const { state, retry } = useRemote(
    signal => getComparisons(id, comparisonId, signal),
    `comparisons:${id}:${selection.revision}`,
  )
  const alternatives = assessments.filter(item => item.id !== id && item.status === 'closed')
  return (
    <section className="dashboard-panel" aria-labelledby="comparisons-heading">
      <h2 id="comparisons-heading">Comparative Analytics</h2>
      <p className="analytics-notice">Порівняння лише для синтетичних даних за запропонованою демометодикою; розриви є сигналом для перегляду, не доказом порушень.</p>
      <label htmlFor="comparison-cycle">Порівняти з іншим закритим циклом</label>{' '}
      <select id="comparison-cycle" value={comparisonId ?? ''} onChange={event =>
        setSelection(previous => ({
          id: event.target.value ? Number(event.target.value) : undefined,
          revision: previous.revision + 1,
        }))}>
        <option value="">Лише категорії поточного циклу</option>
        {alternatives.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
      {alternatives.length === 0 && <p>Іншого закритого циклу для порівняння немає.</p>}
      <ModuleState state={state} retry={retry}>{(data: Comparisons) =>
        <ComparisonsContent data={data} />}</ModuleState>
    </section>
  )
}

export function ComparisonsContent({ data }: { data: Comparisons }) {
  return (
    <>
          {data.category_comparisons.length === 0
            ? <p>Порівнянь категорій поки немає.</p>
            : <ul>{data.category_comparisons.map((item, position) => (
              <li key={`${item.component_code}-${item.left_category}-${item.right_category}-${position}`}>
                {item.component_code}: {categoryName(item.left_category)} / {categoryName(item.right_category)} —{' '}
                {item.status === 'ok' && item.gap_points !== null
                  ? `${item.gap_points.toLocaleString('uk-UA')} п.п.${item.flag ? ' · сигнал для перегляду' : ''}`
                  : 'недоступно через приховування або брак даних'}
              </li>
            ))}</ul>}
          {data.period_comparison && (
            <div>
              <h3>Зіставлення циклів</h3>
              <p>{data.period_comparison.before_assessment.name} → {data.period_comparison.after_assessment.name}:{' '}
                {data.period_comparison.status === 'limited_comparability' && data.period_comparison.change_points !== null
                  ? `${data.period_comparison.change_points.toLocaleString('uk-UA')} п.п.`
                  : 'числова зміна недоступна'}</p>
              <strong>Обмежена зіставність</strong>
              <ul>{data.period_comparison.warnings.map(item => <li key={item}>{item}</li>)}</ul>
            </div>
          )}
    </>
  )
}

export function AnalyticsModules({ id, assessments }: { id: number; assessments: Assessment[] }) {
  return (
    <>
      <IndexPanel id={id} />
      <RecommendationsPanel id={id} />
      <ComparisonsPanel id={id} assessments={assessments} />
    </>
  )
}
