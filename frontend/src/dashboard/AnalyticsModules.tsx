import { useEffect, useState, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import {
  getComparisons, getIntegrityIndex, getMethodology, getRecommendations,
  type Comparisons, type IntegrityIndex, type Methodology, type Recommendation, type Recommendations,
} from '../api/analytics'
import type { Assessment } from '../api/assessments'
import { categoryName } from './format'
import {
  CATEGORY_GAP_THRESHOLD, PRIORITY_RULE, RULE_SET, explainRecommendation, formatChange, formatNumber,
  groupRecommendations, localizeBackendText, persistenceText, ruleTitle,
} from './explain'
import { ObjectiveComparison } from './ObjectiveComparison'
import './dashboard.css'
import './analytics-explain.css'

export type RemoteState<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string; retryable?: boolean }
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
        retryable: !(error instanceof ApiError && error.status === 503),
      })
    })
  return () => controller.abort()
}

interface Remote<T> {
  state: RemoteState<T>
  retry: () => void
}

function useRemote<T>(request: (signal: AbortSignal) => Promise<T>, key: string): Remote<T> {
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
      {state.retryable !== false && <button type="button" onClick={retry}>Спробувати ще раз</button>}
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

function approvalLabel(status: string): string {
  if (status === 'proposed') return 'запропонована'
  if (status === 'approved') return 'затверджена'
  return status
}

function formatWeight(weight: number): string {
  return weight.toLocaleString('uk-UA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function ShortHash({ label, value }: { label: string; value: unknown }) {
  if (typeof value !== 'string' || value.length === 0) return null
  return <p className="ax-meta">{label}: <code title={value}>{value.slice(0, 16)}…</code></p>
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

const unavailableScore = {
  missing: 'Немає даних',
  suppressed: 'Приховано для захисту групи',
}

export function IndexContent({ index, methodology }: { index: IntegrityIndex; methodology: Methodology }) {
  const limitations = [...new Set([...methodology.limitations, ...index.warnings])]
  const weightTotal = index.components.reduce((sum, item) => sum + item.weight, 0)
  return (
    <>
      <DemoNotice approvalStatus={index.approval_status} syntheticOnly={index.synthetic_only} official={index.official} />
      {index.status !== 'ok' || index.index === null
        ? <p>Індекс недоступний: {index.status === 'suppressed' ? 'дані приховано для захисту групи.' : 'бракує даних.'}</p>
        : <p className="analytics-number">{index.index.toLocaleString('uk-UA')} зі 100</p>}
      <div className="ax-formula">
        <p>
          <strong>Як розраховано.</strong> Індекс = Σ (бал компонента × вага компонента), тобто сума внесків
          усіх компонентів за шкалою 0–100. Ваги задає версія методики {index.methodology_version}.
        </p>
        <p>Формула з API: <code>{methodology.formula}</code></p>
        {methodology.missing === 'no_index_no_reweighting' && (
          <p>Якщо бал хоча б одного компонента приховано або відсутній, індекс не розраховується, а ваги інших компонентів не перерозподіляються.</p>
        )}
      </div>
      <h3>Складові</h3>
      {index.components.length === 0
        ? <p>Складових поки немає.</p>
        : (
          <div className="ax-table-wrap">
            <table className="ax-table ax-table-stack">
              <caption>Бал, вага і внесок кожного компонента в індекс</caption>
              <thead>
                <tr>
                  <th scope="col">Компонент</th>
                  <th scope="col">Бал</th>
                  <th scope="col">Вага</th>
                  <th scope="col">Внесок = бал × вага</th>
                </tr>
              </thead>
              <tbody>
                {index.components.map(item => {
                  const score = item.status === 'ok' ? item.score : null
                  const contribution = score === null ? null : item.contribution
                  return (
                    <tr key={item.code}>
                      <th scope="row"><span className="dashboard-code">{item.code}</span> {item.name}</th>
                      <td data-label="Бал" className={score === null ? 'ax-muted' : 'ax-num'}>
                        {score === null
                          ? unavailableScore[item.status === 'suppressed' ? 'suppressed' : 'missing']
                          : `${formatNumber(score)} зі 100`}
                      </td>
                      <td data-label="Вага" className="ax-num">{formatWeight(item.weight)}</td>
                      <td data-label="Внесок = бал × вага" className="ax-num">
                        {score === null || contribution === null
                          ? <span className="ax-muted">не враховано</span>
                          : <>{formatNumber(contribution)} <small className="ax-muted">= {formatNumber(score)} × {formatWeight(item.weight)}</small></>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row" colSpan={2}>Разом</th>
                  <td data-label="Сума ваг" className="ax-num">{formatWeight(weightTotal)}</td>
                  <td data-label="Індекс" className="ax-num">
                    {index.status === 'ok' && index.index !== null ? `${formatNumber(index.index)} зі 100` : 'не розраховано'}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      <h3>Обмеження методики</h3>
      <p>Версія: {methodology.version}; статус: {approvalLabel(methodology.approval_status)}.</p>
      {limitations.length === 0
        ? <p>Обмежень не зазначено.</p>
        : <ul className="ax-list">{limitations.map(item => <li key={item}>{localizeBackendText(item)}</li>)}</ul>}
      <ShortHash label="Відбиток конфігурації правил (SHA-256)" value={methodology.config_sha256} />
    </>
  )
}

function RecommendationsPanel({ remote }: { remote: Remote<Recommendations> }) {
  return (
    <section className="dashboard-panel" aria-labelledby="recommendations-heading">
      <h2 id="recommendations-heading">Рекомендації</h2>
      <ModuleState state={remote.state} retry={remote.retry}>{(data: Recommendations) =>
        <RecommendationsContent data={data} />}</ModuleState>
    </section>
  )
}

/** The visible rule set: which rule creates a proposal and in what order proposals are listed. */
export function RuleSetNote() {
  return (
    <div className="ax-rules">
      <p><strong>Правила.</strong> Пропозицію створює лише одне з явних правил:</p>
      <ul>
        {RULE_SET.map(rule => (
          <li key={rule.id}><code>{rule.id}</code> — {rule.title.toLowerCase()}: {rule.condition}.</li>
        ))}
      </ul>
      <p>{PRIORITY_RULE}</p>
    </div>
  )
}

function RecommendationCard({ item, rank }: { item: Recommendation; rank: number }) {
  const explanation = explainRecommendation(item)
  return (
    <li className="ax-card">
      <div className="ax-card-head">
        <span className="ax-rank">Пріоритет {rank}</span>
        <span className="ax-rule-name">{ruleTitle(item.rule_id)} · <code>{item.rule_id}</code></span>
        {item.requires_human_decision && <span className="ax-badge-human">Потребує рішення посадової особи</span>}
      </div>
      <p className="ax-card-text">{item.text}</p>
      <div className="ax-why">
        <p><strong>Чому запропоновано:</strong> {explanation.text}</p>
        {explanation.facts.length > 0 && (explanation.known
          ? (
            <details>
              <summary>Вихідні дані правила</summary>
              <BasisFacts facts={explanation.facts} />
            </details>
          )
          : <BasisFacts facts={explanation.facts} />)}
      </div>
      <p className="ax-card-meta">
        Статус: запропоновано · Відповідальна роль: {item.owner_role ?? 'не призначено'} · Строк: {item.due_date ?? 'не встановлено'}
      </p>
    </li>
  )
}

function BasisFacts({ facts }: { facts: [string, string][] }) {
  return (
    <dl className="ax-facts">
      {facts.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
    </dl>
  )
}

export function RecommendationsContent({ data }: { data: Recommendations }) {
  const groups = groupRecommendations(data.proposals)
  return (
    <>
      <p className="analytics-notice">
        Пропозиції за синтетичною демометодикою {data.methodology_version} (статус: {approvalLabel(data.approval_status)}).
        Потребують рішення людини; не є затвердженим планом.
      </p>
      <RuleSetNote />
      {groups.length === 0
        ? <p>Рекомендацій за поточними правилами немає.</p>
        : groups.map(group => (
          <section key={group.componentCode} className="ax-group" aria-label={`Пропозиції для компонента ${group.componentCode}`}>
            <h3 className="ax-group-title">
              <span className="dashboard-code">{group.componentCode}</span>
              <small>Пропозицій: {group.items.length}</small>
            </h3>
            <ul className="ax-cards">
              {group.items.map(({ item, rank }) => <RecommendationCard key={item.id} item={item} rank={rank} />)}
            </ul>
          </section>
        ))}
      <p className="ax-meta">{persistenceText(data.persistence)}</p>
      <ShortHash label="Відбиток конфігурації правил (SHA-256)" value={data.audit?.config_sha256} />
    </>
  )
}

function ObjectiveComparisonPanel({ remote }: { remote: Remote<Recommendations> }) {
  return (
    <section className="dashboard-panel" aria-labelledby="objective-comparison-heading">
      <h2 id="objective-comparison-heading">Самооцінка vs об’єктивні показники</h2>
      <ModuleState state={remote.state} retry={remote.retry}>{(data: Recommendations) =>
        <ObjectiveComparison items={data.objective_context} />}</ModuleState>
    </section>
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
      <h2 id="comparisons-heading">Порівняльна аналітика</h2>
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
  const period = data.period_comparison
  return (
    <>
      {data.category_comparisons.length === 0
        ? <p>Порівнянь категорій поки немає.</p>
        : (
          <>
            <p className="ax-meta">Сигнал для перегляду ставиться, якщо розрив між двома видимими категоріями — {CATEGORY_GAP_THRESHOLD} п.п. або більше.</p>
            <ul className="ax-list">{data.category_comparisons.map((item, position) => (
              <li key={`${item.component_code}-${item.left_category}-${item.right_category}-${position}`}>
                {item.component_code}: {categoryName(item.left_category)} / {categoryName(item.right_category)} —{' '}
                {item.status === 'ok' && item.gap_points !== null
                  ? `${item.gap_points.toLocaleString('uk-UA')} п.п.${item.flag ? ' · сигнал для перегляду' : ''}`
                  : 'недоступно через приховування або брак даних'}
              </li>
            ))}</ul>
          </>
        )}
      {period && (
        <div className="ax-period">
          <h3>Зіставлення циклів</h3>
          <p>{period.before_assessment.name} → {period.after_assessment.name}:{' '}
            {period.status === 'limited_comparability' && period.change_points !== null
              ? `${formatChange(period.change_points)} п.п. для індексу`
              : 'числова зміна недоступна'}</p>
          {period.components.length === 0
            ? <p>Покомпонентних змін API не передав.</p>
            : (
              <div className="ax-table-wrap">
                <table className="ax-table ax-change-table">
                  <caption>Зміна балу кожного компонента між циклами, п.п.</caption>
                  <thead><tr><th scope="col">Компонент</th><th scope="col">Зміна</th></tr></thead>
                  <tbody>
                    {period.components.map((item, position) => (
                      <tr key={`${item.component_code}-${position}`}>
                        <th scope="row"><span className="dashboard-code">{item.component_code}</span></th>
                        <td className={item.change_points === null ? 'ax-muted' : 'ax-num'}>
                          {item.change_points === null ? 'недоступно' : `${formatChange(item.change_points)} п.п.`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          <strong>Обмежена зіставність</strong>
          <ul className="ax-list">{period.warnings.map(item => <li key={item}>{localizeBackendText(item)}</li>)}</ul>
        </div>
      )}
    </>
  )
}

export function AnalyticsModules({ id, assessments }: { id: number; assessments: Assessment[] }) {
  // One request feeds both the recommendations and the self-assessment vs objective panels.
  const recommendations = useRemote(signal => getRecommendations(id, signal), `recommendations:${id}`)
  return (
    <>
      <IndexPanel id={id} />
      <RecommendationsPanel remote={recommendations} />
      <ObjectiveComparisonPanel remote={recommendations} />
      <ComparisonsPanel id={id} assessments={assessments} />
    </>
  )
}
