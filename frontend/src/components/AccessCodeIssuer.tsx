import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import type { Assessment } from '../api/assessments'
import { DEFAULT_CODE_EXPIRY_DAYS, issueAccessTokens, MAX_CODE_EXPIRY_DAYS, MAX_CODES_PER_REQUEST } from '../api/admin'
import { ALL_CATEGORIES, categoryLabel, type Category } from './categories'
import './AssessmentManager.css'
import './access-codes.css'

/** Видані коди в пам’яті сторінки. Сервер зберігає лише хеші, тому повторно ці коди не показати. */
export interface IssuedCodes {
  assessmentId: number
  assessmentName: string
  category: string
  expiresDays: number
  issuedAt: string
  tokens: string[]
}

export const ONE_TIME_WARNING = 'Коди показано лише один раз. Сервер зберігає тільки їхні хеші, тому повторно показати ці коди неможливо. Завантажте або надрукуйте їх зараз і передайте респондентам окремо.'

const dateFormat = new Intl.DateTimeFormat('uk-UA', { day: '2-digit', month: '2-digit', year: 'numeric' })
const dateTimeFormat = new Intl.DateTimeFormat('uk-UA', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })

export function codesExpiryDate(issued: Pick<IssuedCodes, 'issuedAt' | 'expiresDays'>): string {
  const start = new Date(issued.issuedAt)
  if (Number.isNaN(start.getTime())) return '—'
  return dateFormat.format(new Date(start.getTime() + issued.expiresDays * 86_400_000))
}

function issuedAtText(issuedAt: string) {
  const date = new Date(issuedAt)
  return Number.isNaN(date.getTime()) ? issuedAt : dateTimeFormat.format(date)
}

/** Текст файлу з кодами (UTF-8, по одному коду в рядку після заголовка). */
export function codesFileText(issued: IssuedCodes): string {
  return [
    'Integrity Management — одноразові коди доступу',
    `Цикл: ${issued.assessmentName} (№ ${issued.assessmentId})`,
    `Категорія: ${categoryLabel(issued.category)}`,
    `Строк дії: ${issued.expiresDays} дн. (орієнтовно до ${codesExpiryDate(issued)})`,
    `Видано: ${issuedAtText(issued.issuedAt)}`,
    `Кількість: ${issued.tokens.length}`,
    'Кожен код можна використати лише один раз. Передавайте коди респондентам окремо.',
    '',
    ...issued.tokens,
    '',
  ].join('\r\n')
}

/** Ім’я файлу без персональних даних: лише номер циклу, категорія і час видачі. */
export function codesFileName(issued: Pick<IssuedCodes, 'assessmentId' | 'category' | 'issuedAt'>): string {
  const stamp = issued.issuedAt.replace(/[^0-9]/g, '').slice(0, 12) || 'codes'
  const category = /^[a-z_]+$/.test(issued.category) ? issued.category : 'category'
  return `access-codes-cycle-${issued.assessmentId}-${category}-${stamp}.txt`
}

function downloadCodes(issued: IssuedCodes) {
  const url = URL.createObjectURL(new Blob([codesFileText(issued)], { type: 'text/plain;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = codesFileName(issued)
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function printCodes() {
  const cleanup = () => {
    document.body.classList.remove('access-codes-printing')
    window.removeEventListener('afterprint', cleanup)
  }
  document.body.classList.add('access-codes-printing')
  window.addEventListener('afterprint', cleanup)
  window.print()
}

export function validateIssueInput(count: number, expiresDays: number): string {
  if (!Number.isInteger(count) || count < 1 || count > MAX_CODES_PER_REQUEST) return `Кількість кодів — ціле число від 1 до ${MAX_CODES_PER_REQUEST}.`
  if (!Number.isInteger(expiresDays) || expiresDays < 1 || expiresDays > MAX_CODE_EXPIRY_DAYS) return `Строк дії — ціле число днів від 1 до ${MAX_CODE_EXPIRY_DAYS}.`
  return ''
}

/** Одноразовий показ виданих кодів із завантаженням і друком. */
export function IssuedCodesView({ issued, onDismiss }: { issued: IssuedCodes; onDismiss: () => void }) {
  const [confirmDismiss, setConfirmDismiss] = useState(false)
  return (
    <div className="cycle-manager__issued access-codes" role="status">
      <p className="access-codes__warning" role="alert"><strong>Увага.</strong> {ONE_TIME_WARNING}</p>
      <dl className="access-codes__facts">
        <div><dt>Цикл</dt><dd>{issued.assessmentName}</dd></div>
        <div><dt>Категорія</dt><dd>{categoryLabel(issued.category)}</dd></div>
        <div><dt>Кодів</dt><dd>{issued.tokens.length.toLocaleString('uk-UA')}</dd></div>
        <div><dt>Строк дії</dt><dd>{issued.expiresDays} дн. (до {codesExpiryDate(issued)})</dd></div>
      </dl>
      <textarea aria-label="Видані коди" readOnly value={issued.tokens.join('\n')} rows={Math.min(Math.max(issued.tokens.length, 3), 12)} />
      <div className="access-codes__actions">
        <button className="v2-button v2-button-primary" type="button" onClick={() => downloadCodes(issued)}>Завантажити файл .txt</button>
        <button className="v2-button" type="button" onClick={printCodes}>Надрукувати</button>
        {confirmDismiss ? (
          <span className="access-codes__confirm" role="group" aria-label="Підтвердження приховування кодів">
            <span>Коди зникнуть назавжди. Ви їх зберегли?</span>
            <button className="v2-button" type="button" onClick={onDismiss}>Так, сховати</button>
            <button className="v2-button v2-button-quiet" type="button" onClick={() => setConfirmDismiss(false)}>Скасувати</button>
          </span>
        ) : (
          <button className="v2-button v2-button-quiet" type="button" onClick={() => setConfirmDismiss(true)}>Сховати коди</button>
        )}
      </div>
      {/* Аркуш для друку живе поза #root, щоб під час друку сховати решту сторінки (див. access-codes.css). */}
      {typeof document !== 'undefined' && createPortal(<PrintSheet issued={issued} />, document.body)}
    </div>
  )
}

export function PrintSheet({ issued }: { issued: IssuedCodes }) {
  return (
    <div className="access-codes-sheet" aria-hidden="true">
      <h2>Одноразові коди доступу</h2>
      <p>{issued.assessmentName} · {categoryLabel(issued.category)} · діють до {codesExpiryDate(issued)}</p>
      <ol>{issued.tokens.map(token => <li key={token}><code>{token}</code></li>)}</ol>
      <p>Кожен код можна використати лише один раз.</p>
    </div>
  )
}

/**
 * Видача кодів для відкритого циклу (роль data_officer): кількість, категорія, строк дії.
 * Поки видані коди показано, нову видачу заблоковано, щоб коди не загубилися.
 */
export function AccessCodeIssuer({ cycle, issued, onIssued, onDismiss }: {
  cycle: Pick<Assessment, 'id' | 'name' | 'status' | 'categories'>
  issued: IssuedCodes | null
  onIssued: (codes: IssuedCodes) => void
  onDismiss: () => void
}) {
  const categories = useMemo(() => (cycle.categories?.length ? cycle.categories : ALL_CATEGORIES) as Category[], [cycle.categories])
  const [category, setCategory] = useState<Category>(categories[0])
  const [count, setCount] = useState(10)
  const [expiresDays, setExpiresDays] = useState(DEFAULT_CODE_EXPIRY_DAYS)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const shown = issued !== null && issued.assessmentId === cycle.id

  useEffect(() => { if (!categories.includes(category)) setCategory(categories[0]) }, [categories, category])

  // Попередження браузера, якщо сторінку закривають до збереження показаних кодів.
  useEffect(() => {
    if (!shown) return
    const onBeforeUnload = (event: BeforeUnloadEvent) => { event.preventDefault() }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [shown])

  async function submit(event: FormEvent) {
    event.preventDefault()
    const invalid = validateIssueInput(count, expiresDays)
    if (invalid) { setError(invalid); return }
    setBusy(true); setError('')
    try {
      const result = await issueAccessTokens(cycle.id, count, category, expiresDays)
      if (!Array.isArray(result.tokens) || !result.tokens.every(token => typeof token === 'string')) throw new Error('API повернув некоректну відповідь з кодами.')
      onIssued({ assessmentId: cycle.id, assessmentName: cycle.name, category, expiresDays, issuedAt: new Date().toISOString(), tokens: result.tokens })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Коди не видано.')
    } finally {
      setBusy(false)
    }
  }

  if (cycle.status !== 'open') {
    return <p className="cycle-manager__empty">Коди видаються лише для відкритого циклу.</p>
  }

  return (
    <section className="cycle-manager__codes" aria-labelledby={`cycle-codes-title-${cycle.id}`}>
      <h4 id={`cycle-codes-title-${cycle.id}`}>Коди доступу</h4>
      <form className="access-codes__form" onSubmit={submit}>
        <div className="cycle-manager__fields">
          <label className="cycle-manager__field">Категорія кодів
            <select value={category} onChange={e => setCategory(e.target.value as Category)} disabled={busy || shown}>
              {categories.map(item => <option key={item} value={item}>{categoryLabel(item)}</option>)}
            </select>
          </label>
          <label className="cycle-manager__field">Кількість кодів
            <input type="number" min={1} max={MAX_CODES_PER_REQUEST} step={1} required value={count} onChange={e => setCount(Number(e.target.value))} disabled={busy || shown} />
          </label>
          <label className="cycle-manager__field">Строк дії, днів
            <input type="number" min={1} max={MAX_CODE_EXPIRY_DAYS} step={1} required value={expiresDays} onChange={e => setExpiresDays(Number(e.target.value))} disabled={busy || shown} />
          </label>
        </div>
        <button className="v2-button v2-button-primary" disabled={busy || shown} type="submit">{busy ? 'Видаємо…' : 'Видати коди'}</button>
        <p className="access-codes__hint">{shown ? 'Спершу збережіть і сховайте видані коди — потім можна видати нові.' : 'Коди буде показано лише один раз: одразу збережіть файл або надрукуйте їх.'}</p>
      </form>
      {error && <p className="cycle-manager__error" role="alert">{error}</p>}
      {shown && issued && <IssuedCodesView issued={issued} onDismiss={onDismiss} />}
    </section>
  )
}
