import { useEffect, useState, type FormEvent } from 'react'
import type { Assessment } from '../api/assessments'
import {
  CRITERION_LABELS, INDICATOR_CRITERIA, confirmObjectiveIndicator, createObjectiveIndicator, criterionLabel, getObjectiveIndicators,
  type ObjectiveIndicator,
} from '../api/annexV'
import { roleLabel } from '../api/auth'
import { INDICATOR_NAME_MAX, PERIOD_MAX, indicatorPayload, validateIndicatorDraft, type IndicatorDraft } from '../official/validation'
import { ConfirmationBadge, Counters, CycleSelect, ENTRY_ROLES_NOTE, useDataCycles, type DataEntryRole } from './ChecklistPanel'
import './annex-v.css'

type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T }
const EMPTY: IndicatorDraft = { criterion: '', name: '', value: '', target: '', period: '' }
const formatPercent = (value: number) => `${new Intl.NumberFormat('uk-UA', { maximumFractionDigits: 1 }).format(value)}%`

export function IndicatorForm({ busy, onSubmit }: { busy: boolean; onSubmit: (draft: IndicatorDraft) => Promise<boolean> }) {
  const [draft, setDraft] = useState<IndicatorDraft>(EMPTY)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const set = (field: keyof IndicatorDraft, value: string) => setDraft(previous => ({ ...previous, [field]: value }))
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const found = validateIndicatorDraft(draft)
    setErrors(found)
    if (Object.keys(found).length) return
    if (await onSubmit(draft)) setDraft(EMPTY)
  }
  const err = (field: string) => errors[field] ? <p id={`indicator-${field}-error`} className="annex-field-error" role="alert">{errors[field]}</p> : null
  const aria = (field: string) => ({ 'aria-invalid': !!errors[field], 'aria-describedby': errors[field] ? `indicator-${field}-error` : undefined })
  return <form className="annex-indicator-form" onSubmit={event => void submit(event)} noValidate aria-labelledby="indicator-form-title">
    <h3 id="indicator-form-title">Додати показник</h3>
    <label className="annex-field" htmlFor="indicator-criterion">Критерій Додатка В
      <select id="indicator-criterion" value={draft.criterion} disabled={busy} onChange={event => set('criterion', event.target.value)} {...aria('criterion')}>
        <option value="">Оберіть критерій</option>
        {INDICATOR_CRITERIA.map(key => <option key={key} value={key}>{criterionLabel(key)}</option>)}
      </select>
      {err('criterion')}
    </label>
    <label className="annex-field annex-wide" htmlFor="indicator-name">Назва показника
      <input id="indicator-name" maxLength={INDICATOR_NAME_MAX} value={draft.name} disabled={busy} placeholder="Наприклад, «Частка персоналу, що пройшов навчання»"
        onChange={event => set('name', event.target.value)} {...aria('name')} />
      {err('name')}
    </label>
    <label className="annex-field" htmlFor="indicator-value">Значення, %
      <input id="indicator-value" inputMode="decimal" value={draft.value} disabled={busy} onChange={event => set('value', event.target.value)} {...aria('value')} />
      {err('value')}
    </label>
    <label className="annex-field" htmlFor="indicator-target">Ціль, %
      <input id="indicator-target" inputMode="decimal" value={draft.target} disabled={busy} onChange={event => set('target', event.target.value)} {...aria('target')} />
      {err('target')}
    </label>
    <label className="annex-field" htmlFor="indicator-period">Період
      <input id="indicator-period" maxLength={PERIOD_MAX} value={draft.period} disabled={busy} placeholder="2026, I півріччя" onChange={event => set('period', event.target.value)} {...aria('period')} />
      {err('period')}
    </label>
    <button type="submit" className="v2-button v2-button-primary" disabled={busy}>{busy ? 'Зберігаємо…' : 'Додати показник'}</button>
  </form>
}

export function IndicatorList({ items, role, busy, messages = {}, onConfirm }: {
  items: ObjectiveIndicator[]
  role: DataEntryRole
  busy: string | null
  messages?: Record<number, { kind: 'error' | 'ok'; text: string }>
  onConfirm: (id: number) => void
}) {
  if (items.length === 0) return <p className="v2-empty" role="status">Для цього циклу показників ще немає.</p>
  return <table className="annex-table">
    <caption className="annex-sr-only">Об’єктивні показники циклу</caption>
    <thead><tr><th scope="col">Показник</th><th scope="col">Критерій</th><th scope="col">Значення / ціль</th><th scope="col">Період</th><th scope="col">Підтвердження</th></tr></thead>
    <tbody>{items.map(item => {
      const message = messages[item.id]
      return <tr key={item.id}>
        <th scope="row" data-label="Показник">{item.name}{item.entered_role && <small className="v2-form-hint">Вніс: {roleLabel(item.entered_role)}</small>}</th>
        <td data-label="Критерій">{Object.hasOwn(CRITERION_LABELS, item.criterion) ? criterionLabel(item.criterion) : item.criterion}</td>
        <td data-label="Значення / ціль"><strong>{formatPercent(item.value)}</strong> / {formatPercent(item.target)}{item.value < item.target && <span className="annex-below"> нижче цілі</span>}</td>
        <td data-label="Період">{item.period}</td>
        <td data-label="Підтвердження">
          <ConfirmationBadge confirmed={item.confirmed} role={item.confirmed_role} />
          {role === 'admin' && !item.confirmed && <button type="button" className="v2-button v2-button-primary annex-confirm" disabled={busy !== null} onClick={() => onConfirm(item.id)}>
            {busy === `confirm:${item.id}` ? 'Підтверджуємо…' : 'Підтвердити'}
          </button>}
          {message && <p className={message.kind === 'error' ? 'annex-field-error' : 'annex-ok'} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</p>}
        </td>
      </tr>
    })}</tbody>
  </table>
}

export function ObjectiveIndicatorsView(props: {
  role: DataEntryRole
  cycles: Load<Assessment[]>
  cycleId: number | null
  onCycle: (id: number | null) => void
  onRetryCycles: () => void
  items: Load<ObjectiveIndicator[]>
  onRetryItems: () => void
  busy: string | null
  formError: string
  messages: Record<number, { kind: 'error' | 'ok'; text: string }>
  onCreate: (draft: IndicatorDraft) => Promise<boolean>
  onConfirm: (id: number) => void
}) {
  const { cycles, items } = props
  const list = items.status === 'ready' ? items.data : []
  return <section className="v2-card annex-panel" aria-labelledby="indicators-title">
    <h2 id="indicators-title">Об’єктивні показники</h2>
    <p className="v2-muted">Кількісні показники (у відсотках) з цільовими значеннями для критеріїв Додатка В. Вони доповнюють самооцінку й експертну оцінку та порівнюються з ціллю лише після підтвердження.</p>
    <p className="official-demo-note annex-roles" role="note">{ENTRY_ROLES_NOTE}</p>
    {cycles.status === 'loading' && <p role="status">Завантажуємо цикли…</p>}
    {cycles.status === 'error' && <div className="v2-inline-error" role="alert"><p>{cycles.message}</p><button type="button" className="v2-button" onClick={props.onRetryCycles}>Спробувати ще раз</button></div>}
    {cycles.status === 'ready' && cycles.data.length === 0 && <p className="v2-empty" role="status">Циклів оцінювання немає.</p>}
    {cycles.status === 'ready' && cycles.data.length > 0 && <>
      <CycleSelect id="indicators-cycle" cycles={cycles.data} value={props.cycleId} onChange={props.onCycle} />
      {props.cycleId !== null && items.status === 'loading' && <p role="status">Завантажуємо показники…</p>}
      {items.status === 'error' && <div className="v2-inline-error" role="alert"><p>{items.message}</p><button type="button" className="v2-button" onClick={props.onRetryItems}>Спробувати ще раз</button></div>}
      {items.status === 'ready' && <>
        <Counters items={[{ label: 'Показників', value: list.length }, { label: 'Підтверджено', value: list.filter(item => item.confirmed).length }]} />
        <IndicatorList items={list} role={props.role} busy={props.busy} messages={props.messages} onConfirm={props.onConfirm} />
        <IndicatorForm key={props.cycleId ?? 0} busy={props.busy === 'create'} onSubmit={props.onCreate} />
        {props.formError && <p className="v2-inline-error" role="alert">{props.formError}</p>}
      </>}
    </>}
  </section>
}

export default function ObjectiveIndicatorsPanel({ role }: { role: DataEntryRole }) {
  const { cycles, cycleId, setCycleId, retry } = useDataCycles(role)
  const [items, setItems] = useState<Load<ObjectiveIndicator[]>>({ status: 'loading' })
  const [busy, setBusy] = useState<string | null>(null)
  const [formError, setFormError] = useState('')
  const [messages, setMessages] = useState<Record<number, { kind: 'error' | 'ok'; text: string }>>({})
  const [reload, setReload] = useState(0)

  useEffect(() => {
    if (cycleId === null) return
    const controller = new AbortController()
    setItems({ status: 'loading' }); setMessages({}); setFormError('')
    getObjectiveIndicators(cycleId, controller.signal).then(data => { if (!controller.signal.aborted) setItems({ status: 'ready', data }) })
      .catch(error => { if (!controller.signal.aborted) setItems({ status: 'error', message: error instanceof Error ? error.message : 'Не вдалося завантажити показники.' }) })
    return () => controller.abort()
  }, [cycleId, reload])

  const create = async (draft: IndicatorDraft) => {
    if (cycleId === null) return false
    setBusy('create'); setFormError('')
    try {
      const created = await createObjectiveIndicator(cycleId, indicatorPayload(draft))
      setItems(previous => previous.status === 'ready' ? { status: 'ready', data: [...previous.data, created] } : previous)
      setMessages(previous => ({ ...previous, [created.id]: { kind: 'ok', text: 'Додано. Показник очікує підтвердження адміністратора.' } }))
      return true
    } catch (error) { setFormError(error instanceof Error ? error.message : 'Показник не збережено.'); return false }
    finally { setBusy(null) }
  }
  const confirm = async (id: number) => {
    setBusy(`confirm:${id}`)
    try {
      const next = await confirmObjectiveIndicator(id)
      setItems(previous => previous.status === 'ready' ? { status: 'ready', data: previous.data.map(item => item.id === id ? next : item) } : previous)
      setMessages(previous => ({ ...previous, [id]: { kind: 'ok', text: 'Підтверджено.' } }))
    } catch (error) { setMessages(previous => ({ ...previous, [id]: { kind: 'error', text: error instanceof Error ? error.message : 'Не підтверджено.' } })) }
    finally { setBusy(null) }
  }

  return <ObjectiveIndicatorsView role={role} cycles={cycles} cycleId={cycleId} onCycle={setCycleId} onRetryCycles={retry} items={items}
    onRetryItems={() => setReload(value => value + 1)} busy={busy} formError={formError} messages={messages} onCreate={create} onConfirm={id => void confirm(id)} />
}
