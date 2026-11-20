import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { roleLabel } from '../api/auth'
import {
  ADMIN_SESSIONS_SERVER_ONLY_MESSAGE, findUserByEmail, getRoleChanges, listUsers, revokeUserSessions,
  ROLE_SERVER_ONLY_HINT, ROLES_SERVER_ONLY_NOTE, SERVER_ACTOR_ID, USER_NOT_FOUND_MESSAGE,
  type AdminUser, type AdminUserMatch, type RoleChange,
} from '../api/users'
import { formatAuditDate } from './AuditTrail'
import { ListPagination, usePagination } from './ListPagination'
import './users.css'

type LoadState<T> = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; data: T }

/** Рядок таблиці: email — замаскований (перелік) або повний (лише результат точного пошуку). */
export interface UserRowData { id: number; name: string; role: string; email: string; created_at: string }

const pluralRules = new Intl.PluralRules('uk-UA')
export function sessionsLabel(count: number) {
  const form = pluralRules.select(count)
  return `${count.toLocaleString('uk-UA')} ${form === 'one' ? 'сесію' : form === 'few' ? 'сесії' : 'сесій'}`
}

function message(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

export const fromListed = (user: AdminUser): UserRowData => ({ id: user.id, name: user.name, role: user.role, email: user.email_masked, created_at: user.created_at })
export const fromMatch = (user: AdminUserMatch): UserRowData => ({ id: user.id, name: user.name, role: user.role, email: user.email, created_at: user.created_at })

export function confirmText(user: UserRowData): string {
  return `Завершити всі сесії користувача «${user.name}» на всіх пристроях? Йому доведеться увійти знову.`
}

/** Підтвердження завершення сесій (єдина дія зміни в цьому розділі). */
export function ConfirmRevoke({ user, busy, onConfirm, onCancel }: { user: UserRowData; busy: boolean; onConfirm: () => void; onCancel: () => void }) {
  const box = useRef<HTMLDivElement>(null)
  // Підтвердження з’являється вгорі розділу: переносимо до нього фокус (і прокрутку), не натискаючи дію.
  useEffect(() => { box.current?.focus() }, [user])
  return (
    <div ref={box} tabIndex={-1} className="users-panel__confirm" role="alertdialog" aria-labelledby="users-confirm-title" aria-describedby="users-confirm-text">
      <strong id="users-confirm-title">Підтвердьте завершення сесій</strong>
      <p id="users-confirm-text">{confirmText(user)}</p>
      <div className="users-panel__confirm-actions">
        <button className="v2-button v2-button-primary" type="button" disabled={busy} onClick={onConfirm}>{busy ? 'Виконуємо…' : 'Завершити сесії'}</button>
        <button className="v2-button v2-button-quiet" type="button" disabled={busy} onClick={onCancel}>Скасувати</button>
      </div>
    </div>
  )
}

/** Таблиця облікових записів: роль лише для читання (її призначає власник сервера), дія — завершення сесій. */
export function UsersTable({ rows, currentUserId, busy, caption, onRevoke }: {
  rows: UserRowData[]
  currentUserId: number
  busy: boolean
  caption: string
  onRevoke: (user: UserRowData) => void
}) {
  return (
    <div className="users-panel__scroll">
      <table className="users-panel__table">
        <caption className="users-panel__sr-only">{caption}</caption>
        <thead><tr><th scope="col">Ім’я</th><th scope="col">Email</th><th scope="col">Роль</th><th scope="col">Створено</th><th scope="col">Дії</th></tr></thead>
        <tbody>
          {rows.map(user => {
            const self = user.id === currentUserId
            return (
              <tr key={user.id} data-self={self || undefined}>
                <th scope="row" data-label="Ім’я"><span>{user.name}{self && <span className="v2-pill users-panel__self">Це ви</span>}</span></th>
                <td data-label="Email" className="users-panel__email">{user.email}</td>
                <td data-label="Роль">
                  <span className="users-panel__role-cell">
                    <span className="users-panel__role" data-role={user.role} title={ROLE_SERVER_ONLY_HINT}>{roleLabel(user.role)}</span>
                    <span className="users-panel__hint">{ROLE_SERVER_ONLY_HINT}</span>
                  </span>
                </td>
                <td data-label="Створено">{formatAuditDate(user.created_at)}</td>
                <td data-label="Дії">
                  {self ? (
                    <span className="users-panel__hint">Щоб завершити власні сесії, скористайтеся «Вийти на всіх пристроях».</span>
                  ) : user.role === 'admin' ? (
                    <span className="users-panel__hint">{ADMIN_SESSIONS_SERVER_ONLY_MESSAGE}</span>
                  ) : (
                    <div className="users-panel__actions">
                      <button className="v2-button v2-button-quiet" type="button" disabled={busy} onClick={() => onRevoke(user)}>Завершити сесії</button>
                    </div>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** Хто змінив роль, якщо це зробила серверна команда власника сервера (actor_user_id = 0). */
export const SERVER_ACTOR_LABEL = 'Власник сервера (серверна команда)'

export function RoleChangeHistory({ changes, users }: { changes: RoleChange[]; users: AdminUser[] }) {
  const names = new Map(users.map(user => [user.id, user.name]))
  const who = (id: number | null) => id === null ? 'Системна дія'
    : id === SERVER_ACTOR_ID ? SERVER_ACTOR_LABEL : names.get(id) ?? `Користувач № ${id}`
  // Історія змін ролей лише зростає: показуємо її сторінками.
  const { current, setPage, setPageSize } = usePagination(changes)
  if (changes.length === 0) return <p className="v2-muted">Змін ролей ще не було.</p>
  return (
    <ListPagination current={current} onPageChange={setPage} onPageSizeChange={setPageSize} name="історії змін ролей">
      <div className="users-panel__scroll">
        <table className="users-panel__table">
          <caption className="users-panel__sr-only">Історія змін ролей: дата, хто змінив, кому, стара й нова роль</caption>
          <thead><tr><th scope="col">Дата і час</th><th scope="col">Хто змінив</th><th scope="col">Кому</th><th scope="col">Зміна</th></tr></thead>
          <tbody>
            {current.items.map(change => (
              <tr key={change.id}>
                <td data-label="Дата і час"><time dateTime={change.changed_at}>{formatAuditDate(change.changed_at)}</time></td>
                <td data-label="Хто змінив">{who(change.actor_user_id)}</td>
                <td data-label="Кому">{who(change.target_user_id)}</td>
                <td data-label="Зміна">{roleLabel(change.old_role)} → {roleLabel(change.new_role)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ListPagination>
  )
}

/** Перелік облікових записів сторінками: та сама таблиця `UsersTable`, але лише рядки поточної сторінки. */
export function PaginatedUsersTable({ rows, ...table }: Parameters<typeof UsersTable>[0]) {
  const { current, setPage, setPageSize } = usePagination(rows)
  return (
    <ListPagination current={current} onPageChange={setPage} onPageSizeChange={setPageSize} name="облікових записів">
      <UsersTable rows={current.items} {...table} />
    </ListPagination>
  )
}

/** Розділ admin «Користувачі й ролі»: перелік, пошук за точним email, завершення сесій, історія ролей. */
export default function UsersPanel({ currentUserId }: { currentUserId: number }) {
  const [users, setUsers] = useState<LoadState<AdminUser[]>>({ status: 'loading' })
  const [history, setHistory] = useState<LoadState<RoleChange[]>>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [pending, setPending] = useState<UserRowData | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error'; text: string; stale?: boolean } | null>(null)
  const [email, setEmail] = useState('')
  const [search, setSearch] = useState<{ status: 'idle' | 'loading' | 'missing' } | { status: 'found'; match: AdminUserMatch } | { status: 'error'; message: string }>({ status: 'idle' })

  useEffect(() => {
    const controller = new AbortController()
    setUsers(current => current.status === 'ready' ? current : { status: 'loading' })
    listUsers(controller.signal)
      .then(data => { if (!controller.signal.aborted) setUsers({ status: 'ready', data }) })
      .catch(error => { if (!controller.signal.aborted) setUsers({ status: 'error', message: message(error, 'Не вдалося завантажити користувачів.') }) })
    getRoleChanges(controller.signal)
      .then(data => { if (!controller.signal.aborted) setHistory({ status: 'ready', data }) })
      .catch(error => { if (!controller.signal.aborted) setHistory({ status: 'error', message: message(error, 'Не вдалося завантажити історію змін ролей.') }) })
    return () => controller.abort()
  }, [attempt])

  const reload = () => setAttempt(value => value + 1)

  async function confirm() {
    if (!pending) return
    const user = pending
    setBusy(true)
    try {
      const revoked = await revokeUserSessions(user.id)
      setNotice({ kind: 'ok', text: revoked > 0 ? `Завершено ${sessionsLabel(revoked)} користувача «${user.name}».` : `Активних сесій у «${user.name}» не було.` })
      reload()
    } catch (error) {
      const status = error instanceof ApiError ? error.status : 0
      const text = status === 404 ? USER_NOT_FOUND_MESSAGE : message(error, 'Дію не виконано.')
      // 404 або admin_role_server_only: ціль могла зникнути чи стати адміністратором на сервері — пропонуємо оновити список.
      setNotice({ kind: 'error', text, stale: status === 404 || status === 403 })
    } finally {
      setPending(null)
      setBusy(false)
    }
  }

  async function submitSearch(event: FormEvent) {
    event.preventDefault()
    setSearch({ status: 'loading' })
    try {
      const match = await findUserByEmail(email)
      setSearch(match ? { status: 'found', match } : { status: 'missing' })
    } catch (error) {
      setSearch({ status: 'error', message: message(error, 'Пошук не виконано.') })
    }
  }

  const requestRevoke = (user: UserRowData) => { setNotice(null); setPending(user) }
  const listed = useMemo(() => users.status === 'ready' ? users.data : [], [users])
  const listedRows = useMemo(() => listed.map(fromListed), [listed])

  return (
    <section className="users-panel" aria-labelledby="users-panel-title">
      <div className="v2-card">
        <div className="v2-section-heading">
          <div><p className="v2-overline">Доступ</p><h2 id="users-panel-title">Користувачі й ролі</h2></div>
          {users.status === 'ready' && <span className="v2-pill">{users.data.length.toLocaleString('uk-UA')} облікових записів</span>}
        </div>
        <p className="v2-muted">
          Ролі: «Користувач» — особистий кабінет; «Адміністратор» — цикли, результати, аналітика, журнал і звіти;
          «Відповідальний за коди доступу» — видача кодів і участь.
        </p>
        <p className="v2-muted"><strong>{ROLES_SERVER_ONLY_NOTE}</strong> Він робить це командою на
          сервері; у вебі ролі не змінюються. Тут можна переглядати користувачів та історію ролей і завершувати сесії
          користувачів і відповідальних за коди (сесії іншого адміністратора — лише власник сервера). Перелік показує
          лише замаскований email.</p>
        {notice && (
          <div className={notice.kind === 'ok' ? 'users-panel__notice' : 'users-panel__notice users-panel__notice--error'} role={notice.kind === 'ok' ? 'status' : 'alert'}>
            <span>{notice.text}</span>
            {notice.stale && <button className="v2-button" type="button" onClick={() => { setNotice(null); reload() }}>Оновити список</button>}
          </div>
        )}
        {pending && <ConfirmRevoke user={pending} busy={busy} onConfirm={() => void confirm()} onCancel={() => setPending(null)} />}
      </div>

      <div className="v2-card">
        <h3>Пошук за точним email</h3>
        <form className="users-panel__search" onSubmit={submitSearch}>
          <label className="users-panel__search-field">Email користувача
            <input type="email" required autoComplete="off" value={email} onChange={event => setEmail(event.target.value)} />
          </label>
          <button className="v2-button" type="submit" disabled={search.status === 'loading'}>{search.status === 'loading' ? 'Шукаємо…' : 'Знайти'}</button>
        </form>
        <p className="users-panel__hint">Повний email показується лише для точного збігу й не зберігається після нового пошуку.</p>
        {search.status === 'missing' && <p className="v2-muted" role="status">Користувача з такою адресою не знайдено.</p>}
        {search.status === 'error' && <p className="users-panel__notice users-panel__notice--error" role="alert">{search.message}</p>}
        {search.status === 'found' && (
          <UsersTable rows={[fromMatch(search.match)]} currentUserId={currentUserId} busy={busy || pending !== null}
            caption="Результат пошуку за точним email" onRevoke={requestRevoke} />
        )}
      </div>

      <div className="v2-card">
        <div className="users-panel__card-head">
          <h3>Облікові записи</h3>
          <button className="v2-button v2-button-quiet" type="button" onClick={reload} disabled={busy}>Оновити</button>
        </div>
        {users.status === 'loading' && <p role="status">Завантажуємо користувачів…</p>}
        {users.status === 'error' && <p className="users-panel__notice users-panel__notice--error" role="alert">{users.message}</p>}
        {users.status === 'ready' && (users.data.length === 0
          ? <p className="v2-muted">Облікових записів немає.</p>
          : <PaginatedUsersTable rows={listedRows} currentUserId={currentUserId} busy={busy || pending !== null}
              caption="Облікові записи: ім’я, замаскований email, роль (лише перегляд), дата створення і дії" onRevoke={requestRevoke} />)}
      </div>

      <div className="v2-card">
        <h3>Історія змін ролей</h3>
        {history.status === 'loading' && <p role="status">Завантажуємо історію…</p>}
        {history.status === 'error' && <p className="users-panel__notice users-panel__notice--error" role="alert">{history.message}</p>}
        {history.status === 'ready' && <RoleChangeHistory changes={history.data} users={listed} />}
      </div>
    </section>
  )
}
