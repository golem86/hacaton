import { useEffect, useState, type FormEvent } from 'react'
import { getRecommendations, type Recommendation, type Recommendations } from '../api/analytics'
import { getAssessments, type Assessment } from '../api/assessments'
import { ApiError } from '../api/client'
import {
  EVIDENCE_MAX, EVIDENCE_MAX_ITEMS, OVERDUE_RULE, OWNER_MAX, OWNER_MIN, REASON_MAX, RULE_LABELS, STATUS_LABELS,
  countActions, decideRecommendation, getTracker, isOverdue, laterClosedAssessments, localDateIso, ownerProblem,
  parseEvidence, transitionAction, transitionLabel,
  type DecisionInput, type Tracker, type TrackerAction, type TransitionInput, type TransitionTarget,
} from '../api/tracker'
import './tracker.css'

export type LoadState<T> =
  | { status: 'loading' }
  | { status: 'error'; message: string; code?: number }
  | { status: 'ready'; data: T }

const DEMO_OFF = 'Пропозиції недоступні: модуль рекомендацій (синтетична демометодика) не ввімкнений у конфігурації сервера. Уже ухвалені рішення й статуси нижче доступні.'
const NO_RETRY = new Set([401, 403, 503])

function failure(error: unknown, fallback: string): { status: 'error'; message: string; code?: number } {
  return {
    status: 'error',
    message: error instanceof Error && error.message ? error.message : fallback,
    code: error instanceof ApiError ? error.status : undefined,
  }
}

function errorText(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const [year, month, day] = value.slice(0, 10).split('-')
  return day && month && year ? `${day}.${month}.${year}` : value
}

function statusLabel(status: string): string {
  return status === 'proposed' ? 'Запропоновано' : STATUS_LABELS[status as keyof typeof STATUS_LABELS] ?? status
}

function roleLabel(role: string): string {
  return role === 'admin' ? 'адміністратор' : role
}

export default function TrackerPanel() {
  const [cycles, setCycles] = useState<LoadState<Assessment[]>>({ status: 'loading' })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    getAssessments(controller.signal).then(list => {
      if (controller.signal.aborted) return
      const closed = list.filter(cycle => cycle.status === 'closed')
        .sort((left, right) => right.start_date.localeCompare(left.start_date))
      setCycles({ status: 'ready', data: closed })
      setSelectedId(current => current ?? closed[0]?.id ?? null)
    }).catch(error => {
      if (!controller.signal.aborted) setCycles(failure(error, 'Не вдалося завантажити список циклів.'))
    })
    return () => controller.abort()
  }, [attempt])

  const closed = cycles.status === 'ready' ? cycles.data : []
  const selected = closed.find(cycle => cycle.id === selectedId) ?? null

  return (
    <section className="v2-card tracker" aria-labelledby="tracker-title">
      <header className="tracker-header">
        <h2 id="tracker-title">Трекер рекомендацій</h2>
        <p className="v2-muted">Від пропозиції до дії: рішення, відповідальний, строк, контроль виконання і перевірка результату наступним оцінюванням.</p>
      </header>
      <HumanDecisionNotice />
      {cycles.status === 'loading' && <p role="status">Завантажуємо цикли оцінювання…</p>}
      {cycles.status === 'error' && (
        <div className="tracker-state" role="alert">
          <p>{cycles.message}</p>
          <button type="button" className="v2-button" onClick={() => { setCycles({ status: 'loading' }); setAttempt(value => value + 1) }}>Спробувати ще раз</button>
        </div>
      )}
      {cycles.status === 'ready' && closed.length === 0 && (
        <p className="v2-empty">Закритих циклів ще немає. Рекомендації формуються лише після закриття оцінювання.</p>
      )}
      {closed.length > 0 && (
        <label className="cycle-select">Закритий цикл
          <select value={selectedId ?? ''} onChange={event => setSelectedId(Number(event.target.value))}>
            {closed.map(cycle => <option key={cycle.id} value={cycle.id}>{cycle.name}</option>)}
          </select>
        </label>
      )}
      {selected && <TrackerCycle key={selected.id} assessment={selected} closed={closed} />}
    </section>
  )
}

export function HumanDecisionNotice() {
  return (
    <div className="tracker-notice" role="note">
      <strong>Рішення ухвалює посадова особа, а не система.</strong>
      <p>Система лише пропонує заходи за прозорими правилами синтетичної демометодики. Прийняти чи відхилити пропозицію, призначити відповідального (посаду або підрозділ) і строк, підтвердити виконання може лише уповноважений адміністратор. Кожну дію записано в журнал дій.</p>
    </div>
  )
}

function TrackerCycle({ assessment, closed }: { assessment: Assessment; closed: Assessment[] }) {
  const [tracker, setTracker] = useState<LoadState<Tracker>>({ status: 'loading' })
  const [proposals, setProposals] = useState<LoadState<Recommendations>>({ status: 'loading' })
  const [trackerVersion, setTrackerVersion] = useState(0)
  const [proposalAttempt, setProposalAttempt] = useState(0)
  const [notice, setNotice] = useState('')
  const today = localDateIso()

  useEffect(() => {
    const controller = new AbortController()
    getTracker(assessment.id, controller.signal).then(data => {
      if (!controller.signal.aborted) setTracker({ status: 'ready', data })
    }).catch(error => {
      if (!controller.signal.aborted) setTracker(failure(error, 'Не вдалося завантажити рішення циклу.'))
    })
    return () => controller.abort()
  }, [assessment.id, trackerVersion])

  useEffect(() => {
    const controller = new AbortController()
    getRecommendations(assessment.id, controller.signal).then(data => {
      if (!controller.signal.aborted) setProposals({ status: 'ready', data })
    }).catch(error => {
      if (controller.signal.aborted) return
      const state = failure(error, 'Не вдалося завантажити пропозиції.')
      setProposals(state.code === 503 ? { ...state, message: DEMO_OFF } : state)
    })
    return () => controller.abort()
  }, [assessment.id, proposalAttempt])

  const actions = tracker.status === 'ready' ? tracker.data.actions : []
  const decided = tracker.status === 'ready' ? new Set(actions.map(action => action.recommendation_id)) : null

  async function decide(input: DecisionInput) {
    await decideRecommendation(assessment.id, input)
    setNotice(input.decision === 'accepted'
      ? 'Рішення збережено: пропозицію прийнято, захід додано до таблиці.'
      : 'Рішення збережено: пропозицію відхилено з обґрунтуванням.')
    setTrackerVersion(value => value + 1)
  }

  async function move(action: TrackerAction, input: TransitionInput) {
    await transitionAction(action.id, input)
    setNotice(`Статус заходу ${action.component_code} змінено на «${STATUS_LABELS[input.status]}».`)
    setTrackerVersion(value => value + 1)
  }

  return (
    <div className="tracker-cycle">
      {tracker.status === 'ready' && <TrackerCounters actions={actions} today={today} />}
      <p className="tracker-rule"><span aria-hidden="true">⚑</span> {OVERDUE_RULE} Стан на {formatDate(today)}.</p>
      {notice && <p className="v2-success" role="status">{notice}</p>}
      <ProposalsSection state={proposals} decided={decided} today={today} onDecide={decide}
        onRetry={() => { setProposals({ status: 'loading' }); setProposalAttempt(value => value + 1) }} />
      <ActionsSection state={tracker} today={today} current={assessment} closed={closed} onTransition={move}
        onRetry={() => { setTracker({ status: 'loading' }); setTrackerVersion(value => value + 1) }} />
    </div>
  )
}

export function TrackerCounters({ actions, today }: { actions: TrackerAction[]; today: string }) {
  const counts = countActions(actions, today)
  const items: { label: string; value: number; hint?: string; alert?: boolean }[] = [
    { label: 'Прийнято', value: counts.accepted, hint: 'усього прийнятих рішень' },
    { label: 'В роботі', value: counts.inProgress },
    { label: 'Виконано', value: counts.completed, hint: 'очікує перевірки' },
    { label: 'Перевірено', value: counts.verified, hint: 'наступним оцінюванням' },
    { label: 'Прострочено', value: counts.overdue, alert: counts.overdue > 0 },
  ]
  return (
    <dl className="tracker-counters" aria-label="Підсумок виконання рекомендацій">
      {items.map(item => (
        <div key={item.label} className={item.alert ? 'is-alert' : undefined}>
          <dt>{item.label}</dt><dd>{item.value}</dd>{item.hint && <small>{item.hint}</small>}
        </div>
      ))}
    </dl>
  )
}

export function ProposalsSection({ state, decided, today, onDecide, onRetry }: {
  state: LoadState<Recommendations>; decided: Set<string> | null; today: string
  onDecide: (input: DecisionInput) => Promise<void>; onRetry: () => void
}) {
  return (
    <section className="tracker-section" aria-labelledby="tracker-proposals-title">
      <div className="tracker-section__head">
        <h3 id="tracker-proposals-title">Пропозиції</h3>
        <span className="v2-pill v2-pill-warm">Очікують рішення посадової особи</span>
      </div>
      {state.status === 'error' ? (
        <div className="tracker-state" role="alert">
          <p>{state.message}</p>
          {!NO_RETRY.has(state.code ?? 0) && <button type="button" className="v2-button" onClick={onRetry}>Спробувати ще раз</button>}
        </div>
      ) : state.status === 'loading' || decided === null ? (
        <p role="status">Завантажуємо пропозиції…</p>
      ) : (
        <ProposalsList proposals={state.data.proposals} decided={decided} today={today} onDecide={onDecide} />
      )}
    </section>
  )
}

export function ProposalsList({ proposals, decided, today, onDecide }: {
  proposals: Recommendation[]; decided: Set<string>; today: string; onDecide: (input: DecisionInput) => Promise<void>
}) {
  const pending = proposals.filter(proposal => !decided.has(proposal.id))
  if (proposals.length === 0) {
    return <p className="v2-empty">За правилами методики для цього циклу пропозицій немає.</p>
  }
  if (pending.length === 0) {
    return <p className="v2-empty">Усі пропозиції цього циклу вже розглянуто: рішення — у таблиці нижче.</p>
  }
  return (
    <ul className="tracker-proposals">
      {pending.map(proposal => <ProposalItem key={proposal.id} proposal={proposal} today={today} onDecide={onDecide} />)}
    </ul>
  )
}

function ProposalItem({ proposal, today, onDecide }: {
  proposal: Recommendation; today: string; onDecide: (input: DecisionInput) => Promise<void>
}) {
  const [mode, setMode] = useState<'accepted' | 'rejected' | null>(null)
  return (
    <li className="tracker-proposal">
      <div className="tracker-proposal__meta">
        <span className="v2-pill">{proposal.component_code}</span>
        <span>{RULE_LABELS[proposal.rule_id] ?? proposal.rule_id}</span>
      </div>
      <p className="tracker-proposal__text">{proposal.text}</p>
      {mode === null ? (
        <div className="tracker-buttons">
          <button type="button" className="v2-button v2-button-primary" onClick={() => setMode('accepted')}>Прийняти</button>
          <button type="button" className="v2-button" onClick={() => setMode('rejected')}>Відхилити</button>
        </div>
      ) : (
        <DecisionForm proposal={proposal} decision={mode} today={today} onSubmit={onDecide} onCancel={() => setMode(null)} />
      )}
    </li>
  )
}

export function DecisionForm({ proposal, decision, today, onSubmit, onCancel }: {
  proposal: Recommendation; decision: 'accepted' | 'rejected'; today: string
  onSubmit: (input: DecisionInput) => Promise<void>; onCancel: () => void
}) {
  const [owner, setOwner] = useState('')
  const [due, setDue] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const accepted = decision === 'accepted'

  async function submit(event: FormEvent) {
    event.preventDefault()
    let problem: string | null = null
    if (accepted) {
      problem = ownerProblem(owner)
        ?? (!due ? 'Вкажіть строк виконання.' : due < today ? 'Строк не може бути раніше за сьогодні.' : null)
    }
    if (!problem && !reason.trim()) problem = 'Вкажіть обґрунтування рішення.'
    if (problem) { setError(problem); return }
    setError('')
    setBusy(true)
    try {
      await onSubmit(accepted
        ? { recommendation_id: proposal.id, decision: 'accepted', owner, due_date: due, reason }
        : { recommendation_id: proposal.id, decision: 'rejected', reason })
    } catch (failed) {
      setError(errorText(failed, 'Не вдалося зберегти рішення.'))
      setBusy(false)
    }
  }

  return (
    <form className="tracker-form" onSubmit={submit} noValidate
      aria-label={accepted ? 'Прийняття пропозиції' : 'Відхилення пропозиції'}>
      {accepted && (
        <div className="tracker-form__grid">
          <label>Відповідальний (посада або підрозділ, не ПІБ)
            <input value={owner} onChange={event => setOwner(event.target.value)} required
              minLength={OWNER_MIN} maxLength={OWNER_MAX} autoComplete="off" placeholder="Напр.: Навчальний відділ" />
            <small>{OWNER_MIN}–{OWNER_MAX} символів. Не вказуйте прізвище, ім’я, email чи телефон.</small>
          </label>
          <label>Строк виконання
            <input type="date" value={due} min={today} onChange={event => setDue(event.target.value)} required />
            <small>Не раніше за сьогодні ({formatDate(today)}).</small>
          </label>
        </div>
      )}
      <label>{accepted ? 'Обґрунтування рішення' : 'Обґрунтування відхилення'}
        <textarea value={reason} onChange={event => setReason(event.target.value)} required maxLength={REASON_MAX} rows={3} />
        <small>Обов’язково: чому посадова особа ухвалює це рішення. Без персональних даних.</small>
      </label>
      {error && <p className="v2-inline-error" role="alert">{error}</p>}
      <div className="tracker-buttons">
        <button type="submit" className="v2-button v2-button-primary" disabled={busy}>
          {busy ? 'Зберігаємо…' : accepted ? 'Підтвердити прийняття' : 'Підтвердити відхилення'}
        </button>
        <button type="button" className="v2-button v2-button-quiet" onClick={onCancel} disabled={busy}>Скасувати</button>
      </div>
    </form>
  )
}

export function ActionsSection({ state, today, current, closed, onTransition, onRetry }: {
  state: LoadState<Tracker>; today: string; current: Assessment; closed: Assessment[]
  onTransition: (action: TrackerAction, input: TransitionInput) => Promise<void>; onRetry: () => void
}) {
  return (
    <section className="tracker-section" aria-labelledby="tracker-actions-title">
      <div className="tracker-section__head">
        <h3 id="tracker-actions-title">Прийняті заходи</h3>
        <span className="v2-pill">Контроль виконання</span>
      </div>
      {state.status === 'loading' && <p role="status">Завантажуємо рішення…</p>}
      {state.status === 'error' && (
        <div className="tracker-state" role="alert">
          <p>{state.message}</p>
          {!NO_RETRY.has(state.code ?? 0) && <button type="button" className="v2-button" onClick={onRetry}>Спробувати ще раз</button>}
        </div>
      )}
      {state.status === 'ready' && (
        <>
          <ActionsTable actions={state.data.actions} today={today} current={current} closed={closed} onTransition={onTransition} />
          <RejectedList actions={state.data.actions} />
        </>
      )}
    </section>
  )
}

export function ActionsTable({ actions, today, current, closed, onTransition }: {
  actions: TrackerAction[]; today: string; current: Assessment; closed: Assessment[]
  onTransition: (action: TrackerAction, input: TransitionInput) => Promise<void>
}) {
  const accepted = actions.filter(action => action.status !== 'rejected')
  if (accepted.length === 0) {
    return <p className="v2-empty">Прийнятих заходів ще немає. Прийміть пропозицію вище, щоб призначити відповідального і строк.</p>
  }
  const verifiers = laterClosedAssessments(closed, current)
  const names = new Map(closed.map(cycle => [cycle.id, cycle.name]))
  return (
    <div className="tracker-table-wrap">
      <table className="tracker-table">
        <thead>
          <tr>
            <th scope="col">Компонент</th><th scope="col">Рекомендація</th><th scope="col">Відповідальний</th>
            <th scope="col">Строк</th><th scope="col">Статус</th><th scope="col">Дії</th>
          </tr>
        </thead>
        <tbody>
          {accepted.map(action => (
            <ActionRow key={action.id} action={action} today={today} verifiers={verifiers} names={names} onTransition={onTransition} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ActionRow({ action, today, verifiers, names, onTransition }: {
  action: TrackerAction; today: string; verifiers: Assessment[]; names: Map<number, string>
  onTransition: (action: TrackerAction, input: TransitionInput) => Promise<void>
}) {
  const [target, setTarget] = useState<TransitionTarget | null>(null)
  const overdue = isOverdue(action, today)
  const verifiedBy = action.verified_in_assessment_id === null ? null
    : names.get(action.verified_in_assessment_id) ?? `№${action.verified_in_assessment_id}`
  return (
    <>
      <tr className={overdue ? 'is-overdue' : undefined}>
        <td data-label="Компонент"><span className="v2-pill">{action.component_code}</span></td>
        <td data-label="Рекомендація">
          <p className="tracker-text">{action.text}</p>
          <ActionHistory action={action} />
        </td>
        <td data-label="Відповідальний">{action.owner ?? '—'}</td>
        <td data-label="Строк">
          <span>{formatDate(action.due_date)}</span>
          {overdue && <span className="tracker-badge">Прострочено</span>}
        </td>
        <td data-label="Статус">
          <span className={`tracker-status tracker-status--${action.status}`}>{STATUS_LABELS[action.status]}</span>
          {verifiedBy && <small className="tracker-cell-note">циклом {verifiedBy}</small>}
        </td>
        <td data-label="Дії">
          {action.allowed_transitions.length > 0 ? (
            <div className="tracker-buttons tracker-buttons--compact">
              {action.allowed_transitions.map(to => (
                <button key={to} type="button" className={to === target ? 'v2-button v2-button-primary' : 'v2-button'}
                  aria-expanded={to === target} onClick={() => setTarget(to)}>
                  {transitionLabel(action.status, to)}
                </button>
              ))}
            </div>
          ) : <span className="v2-muted">Завершено</span>}
        </td>
      </tr>
      {target && (
        <tr className="tracker-form-row">
          <td colSpan={6}>
            <TransitionForm key={target} action={action} target={target} verifiers={verifiers}
              onSubmit={async input => { await onTransition(action, input); setTarget(null) }}
              onCancel={() => setTarget(null)} />
          </td>
        </tr>
      )}
    </>
  )
}

function ActionHistory({ action }: { action: TrackerAction }) {
  return (
    <details className="tracker-history">
      <summary>Історія рішень ({action.history.length})</summary>
      <ol>
        {action.history.map((entry, index) => (
          <li key={`${entry.at}-${index}`}>
            <strong>{formatDate(entry.on_date)} · {statusLabel(entry.from_status)} → {statusLabel(entry.to_status)}</strong>
            <span>Роль: {roleLabel(entry.actor_role)}. {entry.reason}</span>
            {entry.evidence_refs.length > 0 && <span>Докази: {entry.evidence_refs.join('; ')}</span>}
          </li>
        ))}
      </ol>
    </details>
  )
}

export function TransitionForm({ action, target, verifiers, onSubmit, onCancel }: {
  action: TrackerAction; target: TransitionTarget; verifiers: Assessment[]
  onSubmit: (input: TransitionInput) => Promise<void>; onCancel: () => void
}) {
  const [reason, setReason] = useState('')
  const [evidence, setEvidence] = useState('')
  const [verifier, setVerifier] = useState<number | null>(verifiers[0]?.id ?? null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const needsEvidence = target === 'completed' || target === 'verified'
  const missingVerifier = target === 'verified' && verifiers.length === 0

  async function submit(event: FormEvent) {
    event.preventDefault()
    const refs = parseEvidence(evidence)
    let problem: string | null = null
    if (!reason.trim()) problem = 'Вкажіть обґрунтування зміни статусу.'
    else if (needsEvidence && refs.length === 0) problem = 'Додайте щонайменше одне посилання на доказ (наказ, протокол, звіт).'
    else if (refs.length > EVIDENCE_MAX_ITEMS) problem = `Не більше ${EVIDENCE_MAX_ITEMS} посилань на докази.`
    else if (refs.some(ref => ref.length > EVIDENCE_MAX)) problem = `Кожне посилання — до ${EVIDENCE_MAX} символів.`
    else if (target === 'verified' && verifier === null) problem = 'Оберіть оцінювання, яке перевірило результат.'
    if (problem) { setError(problem); return }
    setError('')
    setBusy(true)
    try {
      await onSubmit({ status: target, reason, evidence_refs: refs,
        verified_in_assessment_id: target === 'verified' && verifier !== null ? verifier : undefined })
    } catch (failed) {
      setError(errorText(failed, 'Не вдалося змінити статус.'))
      setBusy(false)
    }
  }

  return (
    <form className="tracker-form" onSubmit={submit} noValidate aria-label="Зміна статусу заходу">
      <p className="tracker-form__title">
        {transitionLabel(action.status, target)}: «{STATUS_LABELS[action.status]}» → «{STATUS_LABELS[target]}»
      </p>
      {target === 'verified' && (missingVerifier ? (
        <p className="v2-inline-error" role="alert">Немає пізнішого закритого циклу з тією самою анкетою. Результат перевіряє наступне оцінювання — підтвердьте після його закриття.</p>
      ) : (
        <label>Оцінювання, яке перевірило результат
          <select value={verifier ?? ''} onChange={event => setVerifier(Number(event.target.value) || null)}>
            {verifiers.map(cycle => <option key={cycle.id} value={cycle.id}>{cycle.name} (з {formatDate(cycle.start_date)})</option>)}
          </select>
          <small>Лише пізніші закриті цикли з тією самою версією анкети.</small>
        </label>
      ))}
      <label>Обґрунтування
        <textarea value={reason} onChange={event => setReason(event.target.value)} required maxLength={REASON_MAX} rows={2} />
      </label>
      <label>Докази {needsEvidence ? '(обов’язково)' : '(за потреби)'}
        <textarea value={evidence} onChange={event => setEvidence(event.target.value)} rows={2}
          placeholder={'Наказ №… від …\nПротокол засідання …'} />
        <small>По одному посиланню в рядку: до {EVIDENCE_MAX_ITEMS} посилань, кожне до {EVIDENCE_MAX} символів.</small>
      </label>
      {error && <p className="v2-inline-error" role="alert">{error}</p>}
      <div className="tracker-buttons">
        <button type="submit" className="v2-button v2-button-primary" disabled={busy || missingVerifier}>
          {busy ? 'Зберігаємо…' : 'Зберегти статус'}
        </button>
        <button type="button" className="v2-button v2-button-quiet" onClick={onCancel} disabled={busy}>Скасувати</button>
      </div>
    </form>
  )
}

export function RejectedList({ actions }: { actions: TrackerAction[] }) {
  const rejected = actions.filter(action => action.status === 'rejected')
  if (rejected.length === 0) return null
  return (
    <details className="tracker-rejected">
      <summary>Відхилені пропозиції ({rejected.length})</summary>
      <ul>
        {rejected.map(action => (
          <li key={action.id}>
            <span className="v2-pill">{action.component_code}</span>
            <span>{action.text}</span>
            <small>Обґрунтування відхилення: {action.decision_reason}</small>
          </li>
        ))}
      </ul>
    </details>
  )
}
