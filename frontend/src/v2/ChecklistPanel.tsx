import { useEffect, useState } from 'react'
import { getManagedAssessments, type Assessment } from '../api/assessments'
import {
  CHECKLIST_STATUSES, CHECKLIST_STATUS_LABELS, confirmChecklistItem, criterionLabel, getChecklist, updateChecklistItem,
  type ChecklistItem, type ChecklistStatus,
} from '../api/annexV'
import { roleLabel } from '../api/auth'
import { EVIDENCE_MAX, validateChecklistEntry } from '../official/validation'
import { ListPagination, usePagination } from './ListPagination'
import './annex-v.css'

export type DataEntryRole = 'admin' | 'data_officer'
type Load<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T }

export const ENTRY_ROLES_NOTE = 'Хто вносить і хто підтверджує: дані вносить Відповідальний за коди доступу (data_officer) або адміністратор; підтверджує лише адміністратор, і не той самий користувач, що вніс запис (принцип «чотирьох очей»). Будь-яка зміна знімає підтвердження. У розрахунку зрілості враховуються лише підтверджені записи.'

const statusLabel = (cycle: Assessment) => cycle.status === 'open' ? 'відкритий' : cycle.status === 'closed' ? 'закритий' : 'чернетка'

/** Цикл за замовчуванням: перший відкритий, інакше останній за датою початку. */
export function defaultDataCycle(list: Assessment[]): number | null {
  const open = list.find(cycle => cycle.status === 'open')
  if (open) return open.id
  return [...list].sort((a, b) => a.start_date.localeCompare(b.start_date) || a.id - b.id).at(-1)?.id ?? null
}

/** Перелік циклів для внесення даних (без чернеток для data_officer) і вибір циклу. */
export function useDataCycles(role: DataEntryRole) {
  const [cycles, setCycles] = useState<Load<Assessment[]>>({ status: 'loading' })
  const [cycleId, setCycleId] = useState<number | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setCycles({ status: 'loading' })
    getManagedAssessments(controller.signal).then(list => {
      if (controller.signal.aborted) return
      const available = role === 'admin' ? list : list.filter(cycle => cycle.status !== 'draft')
      setCycles({ status: 'ready', data: available })
      setCycleId(current => current !== null && available.some(cycle => cycle.id === current) ? current : defaultDataCycle(available))
    }).catch(error => { if (!controller.signal.aborted) setCycles({ status: 'error', message: error instanceof Error ? error.message : 'Не вдалося завантажити цикли.' }) })
    return () => controller.abort()
  }, [role, attempt])
  return { cycles, cycleId, setCycleId, retry: () => setAttempt(value => value + 1) }
}

export function CycleSelect({ id, cycles, value, onChange }: { id: string; cycles: Assessment[]; value: number | null; onChange: (id: number | null) => void }) {
  return <label className="annex-field annex-cycle" htmlFor={id}>Цикл оцінювання
    <select id={id} value={value ?? ''} onChange={event => onChange(Number(event.target.value) || null)}>
      {value === null && <option value="">Оберіть цикл</option>}
      {cycles.map(cycle => <option key={cycle.id} value={cycle.id}>{cycle.name} · {statusLabel(cycle)}</option>)}
    </select>
  </label>
}

/** Бейдж стану підтвердження: «Не підтверджено» або «Підтверджено (роль)». */
export function ConfirmationBadge({ confirmed, role }: { confirmed: boolean; role: string | null }) {
  return confirmed
    ? <span className="annex-badge annex-badge-confirmed">Підтверджено{role ? ` (${roleLabel(role)})` : ''}</span>
    : <span className="annex-badge annex-badge-pending">Не підтверджено</span>
}

export interface ChecklistCounters { entered: number; confirmed: number; total: number }
export function checklistCounters(items: ChecklistItem[]): ChecklistCounters {
  return { entered: items.filter(item => item.status !== null).length, confirmed: items.filter(item => item.confirmed).length, total: items.length }
}

export function Counters({ items }: { items: { label: string; value: number }[] }) {
  return <dl className="annex-counters" aria-label="Лічильники">
    {items.map(item => <div key={item.label}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}
  </dl>
}

type Draft = { status: string; evidence: string }
const draftOf = (item: ChecklistItem): Draft => ({ status: item.status ?? '', evidence: item.evidence ?? '' })

export interface ChecklistTableProps {
  items: ChecklistItem[]
  role: DataEntryRole
  busy: string | null
  messages?: Record<string, { kind: 'error' | 'ok'; text: string }>
  onSave: (code: string, status: ChecklistStatus, evidence: string) => void
  onConfirm: (code: string) => void
  /** Зміна ключа (наприклад, id циклу) повертає таблицю на першу сторінку. */
  resetKey?: string
}

/**
 * Таблиця пунктів; на вузьких екранах рядки стають картками (без горизонтальної прокрутки).
 * Пункти поділено на сторінки (пагінація вгорі й унизу); незбережені чернетки не губляться між сторінками.
 */
export function ChecklistTable({ items, role, busy, messages = {}, onSave, onConfirm, resetKey = '' }: ChecklistTableProps) {
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [errors, setErrors] = useState<Record<string, Record<string, string>>>({})
  const { current: page, setPage, setPageSize } = usePagination(items, { resetKey })
  if (items.length === 0) return <p className="v2-empty" role="status">Для цього циклу пункти чеклиста ще не сформовано.</p>
  const draft = (item: ChecklistItem) => drafts[item.code] ?? draftOf(item)
  const change = (item: ChecklistItem, patch: Partial<Draft>) => setDrafts(previous => ({ ...previous, [item.code]: { ...draft(item), ...patch } }))
  const save = (item: ChecklistItem) => {
    const current = draft(item)
    const found = validateChecklistEntry(current)
    setErrors(previous => ({ ...previous, [item.code]: found }))
    if (Object.keys(found).length) return
    onSave(item.code, current.status as ChecklistStatus, current.evidence.trim())
  }
  return <ListPagination current={page} onPageChange={setPage} onPageSizeChange={setPageSize} name="чеклиста Додатка Б"><table className="annex-table">
    <caption className="annex-sr-only">Пункти чеклиста Додатка Б</caption>
    <thead><tr><th scope="col">Код</th><th scope="col">Критерій</th><th scope="col">Пункт</th><th scope="col">Джерело</th><th scope="col">Статус і доказ</th><th scope="col">Підтвердження</th></tr></thead>
    <tbody>{page.items.map(item => {
      const current = draft(item)
      const rowErrors = errors[item.code] ?? {}
      const dirty = current.status !== (item.status ?? '') || current.evidence.trim() !== (item.evidence ?? '')
      const prefix = `checklist-${item.code.replace(/[^\w-]/g, '_')}`
      const message = messages[item.code]
      return <tr key={item.code}>
        <th scope="row" data-label="Код"><code>{item.code}</code></th>
        <td data-label="Критерій">{criterionLabel(item.criterion)}</td>
        <td data-label="Пункт" className="annex-text">{item.text}</td>
        <td data-label="Джерело">{item.source}</td>
        <td data-label="Статус і доказ" className="annex-entry">
          <fieldset className="annex-status" aria-describedby={rowErrors.status ? `${prefix}-status-error` : undefined}>
            <legend className="annex-sr-only">Статус пункту {item.code}</legend>
            {CHECKLIST_STATUSES.map(status => <label key={status} className="annex-choice">
              <input type="radio" name={`${prefix}-status`} value={status} checked={current.status === status} disabled={busy !== null} onChange={() => change(item, { status })} />
              {CHECKLIST_STATUS_LABELS[status]}
            </label>)}
          </fieldset>
          {rowErrors.status && <p id={`${prefix}-status-error`} className="annex-field-error" role="alert">{rowErrors.status}</p>}
          <label className="annex-field" htmlFor={`${prefix}-evidence`}>Доказ (документ, наказ, посилання)
            <textarea id={`${prefix}-evidence`} rows={2} maxLength={EVIDENCE_MAX} value={current.evidence} disabled={busy !== null}
              aria-invalid={!!rowErrors.evidence} onChange={event => change(item, { evidence: event.target.value })} />
          </label>
          {rowErrors.evidence && <p className="annex-field-error" role="alert">{rowErrors.evidence}</p>}
          <button type="button" className="v2-button" disabled={busy !== null || !dirty} onClick={() => save(item)}>
            {busy === `save:${item.code}` ? 'Зберігаємо…' : 'Зберегти'}
          </button>
          {item.entered_role && <small className="v2-form-hint">Вніс: {roleLabel(item.entered_role)}{item.entered_at ? ` · ${item.entered_at.slice(0, 10)}` : ''}</small>}
        </td>
        <td data-label="Підтвердження">
          <ConfirmationBadge confirmed={item.confirmed} role={item.confirmed_role} />
          {role === 'admin' && !item.confirmed && item.status !== null &&
            <button type="button" className="v2-button v2-button-primary annex-confirm" disabled={busy !== null || dirty} onClick={() => onConfirm(item.code)}>
              {busy === `confirm:${item.code}` ? 'Підтверджуємо…' : 'Підтвердити'}
            </button>}
          {role === 'admin' && !item.confirmed && dirty && <small className="v2-form-hint">Спершу збережіть зміни.</small>}
          {message && <p className={message.kind === 'error' ? 'annex-field-error' : 'annex-ok'} role={message.kind === 'error' ? 'alert' : 'status'}>{message.text}</p>}
        </td>
      </tr>
    })}</tbody>
  </table></ListPagination>
}

export default function ChecklistPanel({ role }: { role: DataEntryRole }) {
  const { cycles, cycleId, setCycleId, retry } = useDataCycles(role)
  const [items, setItems] = useState<Load<ChecklistItem[]>>({ status: 'loading' })
  const [busy, setBusy] = useState<string | null>(null)
  const [messages, setMessages] = useState<Record<string, { kind: 'error' | 'ok'; text: string }>>({})
  const [reload, setReload] = useState(0)

  useEffect(() => {
    if (cycleId === null) return
    const controller = new AbortController()
    setItems({ status: 'loading' }); setMessages({})
    getChecklist(cycleId, controller.signal).then(data => { if (!controller.signal.aborted) setItems({ status: 'ready', data }) })
      .catch(error => { if (!controller.signal.aborted) setItems({ status: 'error', message: error instanceof Error ? error.message : 'Не вдалося завантажити чеклист.' }) })
    return () => controller.abort()
  }, [cycleId, reload])

  const replace = (next: ChecklistItem) => setItems(previous => previous.status === 'ready'
    ? { status: 'ready', data: previous.data.map(item => item.code === next.code ? next : item) } : previous)
  const run = async (key: string, code: string, action: () => Promise<ChecklistItem>, ok: string) => {
    setBusy(key); setMessages(previous => { const rest = { ...previous }; delete rest[code]; return rest })
    try { replace(await action()); setMessages(previous => ({ ...previous, [code]: { kind: 'ok', text: ok } })) }
    catch (error) { setMessages(previous => ({ ...previous, [code]: { kind: 'error', text: error instanceof Error ? error.message : 'Дію не виконано.' } })) }
    finally { setBusy(null) }
  }

  return <ChecklistView role={role} cycles={cycles} cycleId={cycleId} onCycle={setCycleId} onRetryCycles={retry} items={items}
    onRetryItems={() => setReload(value => value + 1)} busy={busy} messages={messages}
    onSave={(code, status, evidence) => cycleId !== null && void run(`save:${code}`, code,
      () => updateChecklistItem(cycleId, code, evidence ? { status, evidence } : { status }), 'Збережено. Запис очікує підтвердження адміністратора.')}
    onConfirm={code => cycleId !== null && void run(`confirm:${code}`, code, () => confirmChecklistItem(cycleId, code), 'Підтверджено.')} />
}

/** Представлення панелі без завантаження (для тестів і повторного використання). */
export function ChecklistView(props: {
  role: DataEntryRole
  cycles: Load<Assessment[]>
  cycleId: number | null
  onCycle: (id: number | null) => void
  onRetryCycles: () => void
  items: Load<ChecklistItem[]>
  onRetryItems: () => void
  busy: string | null
  messages: Record<string, { kind: 'error' | 'ok'; text: string }>
  onSave: ChecklistTableProps['onSave']
  onConfirm: ChecklistTableProps['onConfirm']
}) {
  const { cycles, items } = props
  const counters = items.status === 'ready' ? checklistCounters(items.data) : null
  return <section className="v2-card annex-panel" aria-labelledby="checklist-title">
    <h2 id="checklist-title">Чеклист Додатка Б</h2>
    <p className="v2-muted">Пункти чеклиста (адаптовано за Додатком Б) для кожного критерію Додатка В. Статус: «Так», «Частково» або «Ні» з коротким доказом.</p>
    <p className="official-demo-note annex-roles" role="note">{ENTRY_ROLES_NOTE}</p>
    {cycles.status === 'loading' && <p role="status">Завантажуємо цикли…</p>}
    {cycles.status === 'error' && <div className="v2-inline-error" role="alert"><p>{cycles.message}</p><button type="button" className="v2-button" onClick={props.onRetryCycles}>Спробувати ще раз</button></div>}
    {cycles.status === 'ready' && cycles.data.length === 0 && <p className="v2-empty" role="status">Циклів оцінювання немає.</p>}
    {cycles.status === 'ready' && cycles.data.length > 0 && <>
      <CycleSelect id="checklist-cycle" cycles={cycles.data} value={props.cycleId} onChange={props.onCycle} />
      {props.cycleId !== null && items.status === 'loading' && <p role="status">Завантажуємо чеклист…</p>}
      {items.status === 'error' && <div className="v2-inline-error" role="alert"><p>{items.message}</p><button type="button" className="v2-button" onClick={props.onRetryItems}>Спробувати ще раз</button></div>}
      {counters && <Counters items={[{ label: 'Внесено', value: counters.entered }, { label: 'Підтверджено', value: counters.confirmed }, { label: 'Усього пунктів', value: counters.total }]} />}
      {items.status === 'ready' && <ChecklistTable key={props.cycleId ?? 0} resetKey={String(props.cycleId ?? '')} items={items.data} role={props.role} busy={props.busy} messages={props.messages} onSave={props.onSave} onConfirm={props.onConfirm} />}
    </>}
  </section>
}
