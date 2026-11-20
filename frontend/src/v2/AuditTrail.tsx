import { useMemo, useState } from 'react'
import type { AuditEvent } from '../api/admin'
import { ListPagination, usePagination } from './ListPagination'
import './audit-trail.css'

/**
 * Людські назви дій журналу. Коди збігаються з allowlist ALLOWED_ACTIONS у backend/app/audit.py
 * та місцями запису: routes/assessments.py, routes/v2_auth.py і v2_bootstrap_admin.py.
 * Невідомий код показується як є.
 */
export const AUDIT_ACTION_LABELS: Readonly<Record<string, string>> = {
  'assessment.create': 'Створення циклу оцінювання',
  'assessment.activate': 'Відкриття циклу для участі',
  'assessment.close': 'Закриття циклу оцінювання',
  'tokens.issue': 'Видача кодів доступу',
  'auth.login': 'Вхід до системи (2FA)',
  'auth.logout': 'Вихід із системи',
  'auth.logout_all': 'Вихід на всіх пристроях',
  'auth.password_reset': 'Скидання пароля',
  'auth.2fa_lockout': 'Блокування 2FA після невдалих кодів',
  'user.role_change': 'Зміна ролі користувача',
  'user.sessions_revoke': 'Завершення сесій користувача',
  'user.create_admin': 'Створення адміністратора',
  'tracker.accepted': 'Рекомендацію прийнято до виконання',
  'tracker.rejected': 'Рекомендацію відхилено',
  'tracker.in_progress': 'Захід розпочато',
  'tracker.completed': 'Захід виконано',
  'tracker.verified': 'Результат заходу перевірено',
  'annex_v.expert_create': 'Внесено експертну оцінку (Додаток В)',
  'checklist.update': 'Оновлено пункт чеклиста Додатка Б',
  'checklist.confirm': 'Підтверджено пункт чеклиста Додатка Б',
  'objective.create': 'Внесено об’єктивний показник',
  'objective.confirm': 'Підтверджено об’єктивний показник',
  'report.narrative': 'Чернетка тексту звіту (локальна ШІ)',
}

/** Ролі виконавця: сесійні ролі V2 (admin, user, data_officer) і демонстраційні ролі V1 з backend/app/roles.py. */
export const ACTOR_ROLE_LABELS: Readonly<Record<string, string>> = {
  admin: 'Адміністратор',
  user: 'Користувач',
  manager: 'Керівник',
  auditor: 'Аудитор',
  anticorruption: 'Уповноважений з антикорупції',
  data_officer: 'Відповідальний за коди доступу',
  server: 'Власник сервера (серверна команда)',
  expert: 'Експерт',
  respondent: 'Респондент',
}

const ACTION_KINDS: Readonly<Record<string, string>> = {
  'assessment.create': 'cycle',
  'assessment.activate': 'cycle',
  'assessment.close': 'cycle',
  'tokens.issue': 'codes',
  'auth.login': 'access',
  'auth.logout': 'access',
  'auth.logout_all': 'access',
  'auth.password_reset': 'access',
  'auth.2fa_lockout': 'access',
  'user.role_change': 'account',
  'user.sessions_revoke': 'account',
  'user.create_admin': 'account',
  'tracker.accepted': 'tracker',
  'tracker.rejected': 'tracker',
  'tracker.in_progress': 'tracker',
  'tracker.completed': 'tracker',
  'tracker.verified': 'tracker',
  'annex_v.expert_create': 'maturity',
  'checklist.update': 'maturity',
  'checklist.confirm': 'maturity',
  'objective.create': 'maturity',
  'objective.confirm': 'maturity',
  'report.narrative': 'cycle',
}

const ALL = 'all'
const NO_CYCLE = 'none'
const pluralRules = new Intl.PluralRules('uk-UA')

function plural(count: number, one: string, few: string, many: string) {
  const form = pluralRules.select(count)
  return form === 'one' ? one : form === 'many' ? many : few
}

function lookup(map: Readonly<Record<string, string>>, key: string) {
  return Object.hasOwn(map, key) ? map[key] : undefined
}

export function auditActionLabel(action: string) {
  return lookup(AUDIT_ACTION_LABELS, action) ?? action
}

export function actorRoleLabel(role: string) {
  return lookup(ACTOR_ROLE_LABELS, role) ?? role
}

/** Дата і час у форматі uk-UA (наприклад, 20.11.2026, 14:05:07). Некоректне значення показується як є. */
export function formatAuditDate(value: string, timeZone?: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('uk-UA', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone,
  }).format(date)
}

/** Службові лічильники details (лише числа, без кодів і відповідей) у стислому вигляді. */
export function formatAuditDetails(action: string, details: Record<string, number> | null | undefined) {
  return Object.entries(details ?? {}).map(([key, value]) => {
    if (typeof value !== 'number') return `${key}: ${String(value)}`
    const amount = value.toLocaleString('uk-UA')
    if (key === 'count' && action === 'tokens.issue') return `${amount} ${plural(value, 'код', 'коди', 'кодів')}`
    if (key === 'count') return `Кількість: ${amount}`
    if (key === 'revoked') return `Завершено сесій: ${amount}`
    if (key === 'target_user_id') return `Користувач № ${value}`
    return `${key}: ${amount}`
  })
}

export function auditCycleLabel(assessmentId: number | null) {
  return assessmentId == null ? '—' : `№ ${assessmentId}`
}

/** Фільтр журналу: тип дії й цикл (`all` — без обмеження, `none` — події без циклу). */
export function filterAuditEvents(events: readonly AuditEvent[], action: string, cycle: string) {
  return events.filter(event => (action === ALL || event.action === action)
    && (cycle === ALL || (cycle === NO_CYCLE ? event.assessment_id == null : String(event.assessment_id) === cycle)))
}

/** Ключ скидання пагінації: будь-яка зміна фільтрів повертає журнал на першу сторінку. */
export function auditFilterKey(action: string, cycle: string) {
  return JSON.stringify([action, cycle])
}

function recordsLabel(count: number) {
  return `${count.toLocaleString('uk-UA')} ${plural(count, 'запис', 'записи', 'записів')}`
}

export default function AuditTrail({ events, error }: { events: AuditEvent[]; error: string }) {
  const [action, setAction] = useState(ALL)
  const [cycle, setCycle] = useState(ALL)

  const actionOptions = useMemo(() => [...new Set(events.map(event => event.action))]
    .sort((left, right) => auditActionLabel(left).localeCompare(auditActionLabel(right), 'uk')), [events])
  const cycleOptions = useMemo(() => [...new Set(events.flatMap(event => event.assessment_id == null ? [] : [event.assessment_id]))]
    .sort((left, right) => right - left), [events])
  const hasEventsWithoutCycle = events.some(event => event.assessment_id == null)
  const filtered = useMemo(() => filterAuditEvents(events, action, cycle), [events, action, cycle])
  // Пагінація після фільтрів; зміна фільтра повертає на першу сторінку.
  const { current, setPage, setPageSize } = usePagination(filtered, { resetKey: auditFilterKey(action, cycle) })
  const filtersActive = action !== ALL || cycle !== ALL
  const resetFilters = () => { setAction(ALL); setCycle(ALL) }

  return (
    <section className="v2-card audit-trail" aria-labelledby="audit-trail-title">
      <div className="v2-section-heading">
        <div>
          <p className="v2-overline">Підзвітність</p>
          <h2 id="audit-trail-title">Журнал дій користувачів</h2>
        </div>
        {events.length > 0 && <span className="v2-pill">{recordsLabel(events.length)}</span>}
      </div>
      <p className="audit-trail__note">
        Журнал фіксує дію, роль виконавця, час і цикл. Зміст анонімних відповідей, коди доступу та імена до нього не потрапляють.
      </p>

      {error && (
        <div className="audit-trail__error" role="alert">
          <strong>Не вдалося завантажити дані</strong>
          <p>{error}</p>
        </div>
      )}

      {events.length === 0 ? (!error && (
        <div className="v2-empty audit-trail__empty" role="status">
          <strong>Записів поки немає</strong>
          <p>Тут з’являться створення, відкриття й закриття циклів, видача кодів доступу та входи до системи.</p>
        </div>
      )) : (
        <>
          <div className="audit-trail__filters" role="group" aria-label="Фільтри журналу">
            <div className="audit-trail__filter">
              <label htmlFor="audit-filter-action">Тип дії</label>
              <select id="audit-filter-action" value={action} onChange={event => setAction(event.target.value)}>
                <option value={ALL}>Усі дії</option>
                {actionOptions.map(item => <option key={item} value={item}>{auditActionLabel(item)}</option>)}
              </select>
            </div>
            <div className="audit-trail__filter">
              <label htmlFor="audit-filter-cycle">Цикл</label>
              <select id="audit-filter-cycle" value={cycle} onChange={event => setCycle(event.target.value)}>
                <option value={ALL}>Усі цикли</option>
                {cycleOptions.map(item => <option key={item} value={String(item)}>Цикл {auditCycleLabel(item)}</option>)}
                {hasEventsWithoutCycle && <option value={NO_CYCLE}>Без циклу (входи, облікові записи)</option>}
              </select>
            </div>
            {filtersActive && <button className="v2-button v2-button-quiet" type="button" onClick={resetFilters}>Скинути фільтри</button>}
          </div>
          {filtersActive && <p className="audit-trail__count" aria-live="polite">За фільтрами: {filtered.length.toLocaleString('uk-UA')} з {recordsLabel(events.length)}</p>}

          {filtered.length === 0 ? (
            <div className="v2-empty audit-trail__empty" role="status">
              <strong>Немає записів за обраними фільтрами</strong>
              <p>Змініть тип дії або цикл, щоб побачити інші записи.</p>
            </div>
          ) : (
            <ListPagination current={current} onPageChange={setPage} onPageSizeChange={setPageSize} name="журналу дій">
              <div className="audit-trail__scroll">
                <table className="audit-trail__table">
                  <caption className="audit-trail__sr-only">Журнал дій: дата і час, дія, роль виконавця, цикл і службові лічильники</caption>
                  <thead>
                    <tr><th scope="col">Дата і час</th><th scope="col">Дія</th><th scope="col">Роль</th><th scope="col">Цикл</th><th scope="col">Деталі</th></tr>
                  </thead>
                  <tbody>
                    {current.items.map(event => {
                      const details = formatAuditDetails(event.action, event.details)
                      return (
                        <tr key={event.id}>
                          <td data-label="Дата і час"><time className="audit-trail__time" dateTime={event.created_at}>{formatAuditDate(event.created_at)}</time></td>
                          <td data-label="Дія"><span className="audit-trail__action" data-kind={lookup(ACTION_KINDS, event.action) ?? 'other'} title={event.action}>{auditActionLabel(event.action)}</span></td>
                          <td data-label="Роль">{actorRoleLabel(event.actor_role)}</td>
                          <td data-label="Цикл" className="audit-trail__cycle">{auditCycleLabel(event.assessment_id)}</td>
                          <td data-label="Деталі" className="audit-trail__details">{details.length ? details.join(' · ') : '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </ListPagination>
          )}
        </>
      )}
    </section>
  )
}
