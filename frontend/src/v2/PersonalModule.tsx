import { useEffect, useId, useRef, useState } from 'react'
import {
  completePersonalAttempt,
  createPersonalAttempt,
  getPersonalAssessments,
  getPersonalAttempts,
  getPersonalStats,
  savePersonalDraft,
  type PersonalAssessment,
  type PersonalAttempt,
  type PersonalStats,
} from '../api/v2User'
import { TestListFilterPanel, TestListPageSize, TestListPagination } from './TestListControls'
import {
  DEFAULT_FILTERS,
  DEFAULT_PAGE_SIZE,
  DEFAULT_SORT,
  activeFilterCount,
  availabilityOf,
  filterTests,
  paginate,
  parseStoredState,
  shownLabel,
  sortTests,
  type Availability,
  type SortKey,
  type StoredListState,
  type TestListFilters,
} from './testList'

export type PersonalView = 'profile' | 'available' | 'attempt' | 'history' | 'stats' | 'unit-results'

interface Props {
  view: PersonalView
  userId: number
  userName: string
  onStart: () => void
  onFinish: () => void
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('uk-UA', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function formatDeadline(value: string) {
  return new Intl.DateTimeFormat('uk-UA', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

/** Порядковий номер тестування у списку: 01, 02, …, 10, 11. */
export function formatTestNumber(index: number) {
  return String(index + 1).padStart(2, '0')
}

/** Середня відповідь з одним знаком після коми за українським форматом (3,5). */
export function formatAverage(value: number | null | undefined) {
  return value == null ? '—' : value.toLocaleString('uk-UA', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
}

const pluralRules = new Intl.PluralRules('uk-UA')

export function recordsLabel(count: number) {
  const form = pluralRules.select(count)
  return `${count} ${form === 'one' ? 'запис' : form === 'many' ? 'записів' : 'записи'}`
}

function averageAnswer(attempt: PersonalAttempt): number | null {
  const values = Object.values(attempt.answers)
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
}

function Progress({ answered, total }: { answered: number; total: number }) {
  const percent = total ? Math.round((answered / total) * 100) : 0
  return (
    <div className="v2-progress" aria-label={`Прогрес ${percent}%`}>
      <div className="v2-progress-track"><span style={{ width: `${percent}%` }} /></div>
      <span>{answered} з {total} · {percent}%</span>
    </div>
  )
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="v2-empty" role="alert"><strong>Не вдалося завантажити дані</strong><p className="v2-muted">{message}</p><button className="v2-button" type="button" onClick={onRetry}>Спробувати ще раз</button></div>
}

const TEST_LIST_STORAGE_KEY = 'v2-personal-test-list'

function readTestListState(): StoredListState | null {
  try {
    return parseStoredState(globalThis.sessionStorage?.getItem(TEST_LIST_STORAGE_KEY))
  } catch {
    return null // приватний режим або заблоковане сховище: працюємо з типовими значеннями
  }
}

function writeTestListState(state: StoredListState) {
  try {
    globalThis.sessionStorage?.setItem(TEST_LIST_STORAGE_KEY, JSON.stringify(state))
  } catch {
    // Збереження фільтрів — лише зручність; без сховища список працює так само.
  }
}

const AVAILABILITY_PILL: Readonly<Record<Availability, { label: string; className: string }>> = {
  open: { label: 'Доступне зараз', className: 'v2-pill' },
  upcoming: { label: 'Заплановано', className: 'v2-pill v2-pill-warm' },
  closed: { label: 'Завершено', className: 'v2-pill test-list__pill-closed' },
}

function formatListDate(value: string, timeZone?: string) {
  const time = Date.parse(value)
  return Number.isNaN(time) ? '—' : new Intl.DateTimeFormat('uk-UA', { dateStyle: 'medium', timeZone }).format(time)
}

function formatListDateTime(value: string, timeZone?: string) {
  const time = Date.parse(value)
  return Number.isNaN(time) ? '—' : new Intl.DateTimeFormat('uk-UA', { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(time)
}

export interface AvailableTestsProps {
  assessments: PersonalAssessment[]
  attempts: PersonalAttempt[]
  onStart: (assessmentId: string) => void
  /** Для тестів: фіксований «зараз» (мс) і часовий пояс дат; у застосунку — поточний час і пояс браузера. */
  now?: number
  timeZone?: string
  /** Для тестів: початковий стан замість sessionStorage. */
  initialState?: Partial<StoredListState>
}

/** «Мої тестування»: пошук, фільтри, сортування й пагінація поверх каталогу з /v2/user/assessments. */
export function AvailableTests({ assessments, attempts, onStart, now, timeZone, initialState }: AvailableTestsProps) {
  const [stored] = useState(() => initialState ?? readTestListState())
  const [filters, setFilters] = useState<TestListFilters>(() => ({ ...DEFAULT_FILTERS, ...stored?.filters }))
  const [sort, setSort] = useState<SortKey>(stored?.sort ?? DEFAULT_SORT)
  const [pageSize, setPageSize] = useState(stored?.pageSize ?? DEFAULT_PAGE_SIZE)
  const [page, setPage] = useState(stored?.page ?? 1)
  const [filtersExpanded, setFiltersExpanded] = useState(false)
  const headingId = useId()
  const listTopRef = useRef<HTMLDivElement>(null)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const pageChangedByUser = useRef(false)

  const currentNow = now ?? Date.now()
  const activeCount = activeFilterCount(filters)
  const current = paginate(sortTests(filterTests(assessments, filters, { timeZone }), sort, { now: currentNow }), page, pageSize)

  useEffect(() => {
    writeTestListState({ filters, sort, pageSize, page: current.page })
  }, [filters, sort, pageSize, current.page])

  useEffect(() => {
    if (!pageChangedByUser.current) return
    pageChangedByUser.current = false
    const reduceMotion = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    listTopRef.current?.scrollIntoView({ block: 'start', behavior: reduceMotion ? 'auto' : 'smooth' })
    headingRef.current?.focus({ preventScroll: true })
  }, [current.page])

  function updateFilters(patch: Partial<TestListFilters>) {
    setFilters((value) => ({ ...value, ...patch }))
    setPage(1)
  }
  function resetFilters() {
    setFilters({ ...DEFAULT_FILTERS })
    setPage(1)
  }
  function goToPage(next: number) {
    pageChangedByUser.current = next !== current.page
    setPage(next)
  }

  return (
    <section className="v2-card test-list" aria-labelledby={`${headingId}-title`}>
      <div className="v2-section-heading"><div><p className="v2-overline">Особисті тестування</p><h2 id={`${headingId}-title`}>Доступні тестування</h2></div><span className="v2-pill">Особистий простір</span></div>
      <TestListFilterPanel
        filters={filters}
        sort={sort}
        activeCount={activeCount}
        expanded={filtersExpanded}
        onToggle={() => setFiltersExpanded((value) => !value)}
        onChange={updateFilters}
        onSortChange={(next) => { setSort(next); setPage(1) }}
        onReset={resetFilters}
      />
      <div className="test-list__summary" ref={listTopRef}>
        <h3 className="test-list__heading" id={`${headingId}-list`} ref={headingRef} tabIndex={-1}>
          Список тестувань{current.pageCount > 1 && <span> · сторінка {current.page} з {current.pageCount}</span>}
        </h3>
        <p className="test-list__count" role="status">{current.total ? shownLabel(current) : 'Нічого не знайдено'}{activeCount > 0 && ` · усього ${assessments.length}`}</p>
        <TestListPageSize pageSize={current.pageSize} onChange={(size) => { setPageSize(size); setPage(1) }} />
      </div>
      {current.total ? (
        <ol className="v2-test-list test-list__items" aria-labelledby={`${headingId}-list`} start={current.start}>
          {current.items.map((assessment, index) => {
            const draft = attempts.find((attempt) => attempt.assessment_id === assessment.id && attempt.status === 'draft')
            const pill = AVAILABILITY_PILL[availabilityOf(assessment, currentNow)]
            const titleId = `${headingId}-${assessment.id}`
            return (
              <li key={assessment.id}>
                <article className="v2-test-item test-list__item" aria-labelledby={titleId}>
                  <div className="test-list__item-main">
                    <div className="test-list__item-top"><span className="v2-test-number">{formatTestNumber(current.start - 1 + index)}</span><span className={pill.className}>{pill.label}</span></div>
                    <h4 id={titleId}>{assessment.name}</h4>
                    <p className="v2-muted">{assessment.duration}</p>
                    <dl className="test-list__meta">
                      <div><dt>Створено</dt><dd><time dateTime={assessment.created_at}>{formatListDate(assessment.created_at, timeZone)}</time></dd></div>
                      <div><dt>Відкриття</dt><dd><time dateTime={assessment.opens_at}>{formatListDateTime(assessment.opens_at, timeZone)}</time></dd></div>
                      <div><dt>Дедлайн</dt><dd><time dateTime={assessment.closes_at}>{formatListDateTime(assessment.closes_at, timeZone)}</time></dd></div>
                    </dl>
                  </div>
                  <button className="v2-button" disabled={assessment.status !== 'open'} type="button" aria-describedby={titleId} onClick={() => onStart(assessment.id)}>{draft ? 'Продовжити' : assessment.status === 'open' ? 'Розпочати' : 'Недоступне'}</button>
                </article>
              </li>
            )
          })}
        </ol>
      ) : (
        <div className="v2-empty test-list__empty">
          <strong>Нічого не знайдено за цими умовами</strong>
          <p className="v2-muted">{assessments.length ? 'Змініть пошуковий запит чи діапазон дат або скиньте фільтри.' : 'Тестувань поки немає.'}</p>
          {activeCount > 0 && <button className="v2-button" type="button" onClick={resetFilters}>Скинути фільтри</button>}
        </div>
      )}
      <TestListPagination page={current.page} pageCount={current.pageCount} onPageChange={goToPage} />
    </section>
  )
}

export function PersonalModule({ view, userName, onStart, onFinish }: Props) {
  const [assessments, setAssessments] = useState<PersonalAssessment[]>([])
  const [attempts, setAttempts] = useState<PersonalAttempt[]>([])
  const [stats, setStats] = useState<PersonalStats | null>(null)
  const [activeAttempt, setActiveAttempt] = useState<PersonalAttempt | null>(null)
  const [questionIndex, setQuestionIndex] = useState(0)
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)

  useEffect(() => {
    if (view === 'unit-results') {
      setLoading(false)
      setError('')
      return
    }
    const controller = new AbortController()
    setLoading(true)
    setError('')
    Promise.all([getPersonalAssessments(controller.signal), getPersonalAttempts(controller.signal), getPersonalStats(controller.signal)])
      .then(([nextAssessments, nextAttempts, nextStats]) => {
        setAssessments(nextAssessments)
        setAttempts(nextAttempts)
        setStats(nextStats)
        setActiveAttempt(nextAttempts.find((attempt) => attempt.status === 'draft') ?? null)
      })
      .catch((nextError: unknown) => {
        if (!controller.signal.aborted) setError(nextError instanceof Error ? nextError.message : 'Не вдалося завантажити персональні дані.')
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [retry, view])

  const activeAssessment = activeAttempt ? assessments.find((assessment) => assessment.id === activeAttempt.assessment_id) : null
  const questions = activeAssessment?.questions ?? []
  const answered = activeAttempt ? Object.keys(activeAttempt.answers).length : 0
  const latest = attempts.find((attempt) => attempt.status === 'completed')
  async function startAttempt(assessmentId: string) {
    const assessment = assessments.find((item) => item.id === assessmentId)
    if (!assessment || assessment.status !== 'open') {
      if (assessment) setNotice(`Тестування недоступне. Період: ${formatDeadline(assessment.opens_at)} — ${formatDeadline(assessment.closes_at)}.`)
      return
    }
    const existing = attempts.find((attempt) => attempt.assessment_id === assessment.id && attempt.status === 'draft')
    try {
      const next = existing ?? await createPersonalAttempt({ assessment_id: assessment.id })
      setActiveAttempt(next)
      setQuestionIndex(0)
      setAttempts((current) => existing ? current : [next, ...current])
      setNotice(existing ? 'Чернетку відновлено.' : 'Нове тестування розпочато.')
      onStart()
    } catch (nextError) {
      setNotice(nextError instanceof Error ? nextError.message : 'Не вдалося розпочати тестування.')
    }
  }

  async function updateAnswer(value: number) {
    if (!activeAttempt || !activeAssessment) return
    const question = questions[questionIndex]
    if (!question) return
    const next = { ...activeAttempt, answers: { ...activeAttempt.answers, [question.id]: value } }
    setActiveAttempt(next)
    setAttempts((current) => current.map((attempt) => attempt.id === next.id ? next : attempt))
    setNotice('Відповідь збережено.')
    try {
      await savePersonalDraft(next.id, { assessment_id: next.assessment_id, answers: next.answers })
    } catch (nextError) {
      setNotice(nextError instanceof Error ? nextError.message : 'Не вдалося зберегти чернетку.')
    }
  }

  async function finishAttempt() {
    if (!activeAttempt || !activeAssessment) return
    if (answered < questions.length) {
      setNotice('Дайте відповідь на всі запитання, щоб завершити спробу.')
      return
    }
    try {
      const completed = await completePersonalAttempt(activeAttempt.id, { answers: activeAttempt.answers })
      setAttempts((current) => current.map((attempt) => attempt.id === completed.id ? completed : attempt))
      setActiveAttempt(null)
      setNotice('Тестування завершено. Результат додано до особистої історії.')
      onFinish()
      try {
        setStats(await getPersonalStats())
      } catch {
        // Завершення вже збережено сервером; оновлення KPI повториться під час наступного відкриття.
      }
    } catch (nextError) {
      setNotice(nextError instanceof Error ? nextError.message : 'Не вдалося завершити тестування.')
    }
  }

  if (loading) return <section className="v2-card" role="status">Завантажуємо персональні дані…</section>
  if (error) return <ErrorState message={error} onRetry={() => setRetry((value) => value + 1)} />

  if (view === 'profile') {
    return <section className="v2-content-grid"><div className="v2-card v2-profile-card"><span className="v2-avatar">{userName.trim().slice(0, 2).toUpperCase() || 'IM'}</span><div><p className="v2-overline">Особистий профіль</p><h2>{userName}</h2><p className="v2-muted">Ваш персональний простір для проходження тестувань і перегляду результатів.</p></div><span className="v2-pill">Особистий профіль</span></div><div className="v2-card"><p className="v2-overline">Конфіденційність</p><h3>Персональні та анонімні дані розділені</h3><p className="v2-muted">Анонімні відповіді не пов’язуються з профілем або особистою історією. Чернетки й результати зберігаються в окремому серверному сховищі.</p></div></section>
  }

  if (view === 'available') {
    return <AvailableTests assessments={assessments} attempts={attempts} onStart={(assessmentId) => void startAttempt(assessmentId)} />
  }

  if (view === 'attempt') {
    const question = questions[questionIndex]
    const selected = question && activeAttempt ? activeAttempt.answers[question.id] : undefined
    return <section className="v2-card"><div className="v2-section-heading"><div><p className="v2-overline">Проходження тестування</p><h2>{activeAttempt?.assessment_name ?? 'Немає активної спроби'}</h2></div>{activeAttempt && <Progress answered={answered} total={questions.length} />}</div>{activeAttempt && question ? <><div className="v2-question-meta"><span>{question.component}</span><span>{question.hint}</span></div><h3 className="v2-question">{question.prompt}</h3><div className="v2-scale">{[1, 2, 3, 4, 5].map((value) => <button type="button" className={selected === value ? 'v2-scale-option is-selected' : 'v2-scale-option'} key={value} onClick={() => void updateAnswer(value)}><strong>{value}</strong><span>{value === 1 ? 'Зовсім ні' : value === 5 ? 'Повністю' : ''}</span></button>)}</div><div className="v2-attempt-actions"><button className="v2-button v2-button-quiet" type="button" disabled={questionIndex === 0} onClick={() => setQuestionIndex((value) => value - 1)}>Назад</button>{questionIndex < questions.length - 1 ? <button className="v2-button" type="button" onClick={() => setQuestionIndex((value) => value + 1)}>Далі</button> : <button className="v2-button v2-button-primary" type="button" onClick={() => void finishAttempt()}>Завершити тестування</button>}</div><p className="v2-inline-note" role="status">{notice || 'Чернетка зберігається у серверному сховищі.'}</p></> : <div className="v2-empty"><p>Активної чернетки немає.</p><button className="v2-button" type="button" onClick={() => void startAttempt(assessments[0]?.id)}>Розпочати тестування</button></div>}</section>
  }

  if (view === 'history') {
    const completed = attempts.filter((attempt) => attempt.status === 'completed')
    return <section className="v2-card"><div className="v2-section-heading"><div><p className="v2-overline">Історія проходжень</p><h2>Завершені проходження</h2></div><span className="v2-pill">{recordsLabel(completed.length)}</span></div>{completed.length ? <div className="v2-history-list">{completed.map((attempt) => <article className="v2-history-item" key={attempt.id}><div><strong>{attempt.assessment_name}</strong><p className="v2-muted">{attempt.completed_at ? formatDate(attempt.completed_at) : 'Чернетка'}</p></div><span className="v2-score-chip">{formatAverage(averageAnswer(attempt))} / 5</span></article>)}</div> : <div className="v2-empty"><strong>Історія поки порожня</strong><p className="v2-muted">Завершіть тестування, щоб побачити запис.</p></div>}</section>
  }

  if (view === 'stats') {
    return <section className="v2-card"><div className="v2-section-heading"><div><p className="v2-overline">Персональна статистика</p><h2>Персональний прогрес</h2></div><span className="v2-pill">Без індексу доброчесності</span></div><div className="v2-stat-grid"><div><span>Завершено тестів</span><strong>{stats?.completed_tests ?? 0}</strong></div><div><span>Відповідей</span><strong>{stats?.responses_total ?? 0}</strong></div><div><span>Середня відповідь</span><strong>{formatAverage(stats?.average_response)}<small> / 5</small></strong></div></div><p className="v2-muted">Показано лише фактичні відповіді та прогрес. Офіційний індекс доброчесності не розраховується без затвердженої методики.</p>{latest && <div className="v2-component-mini">{(assessments.find((assessment) => assessment.id === latest.assessment_id)?.questions ?? []).map((question) => <div key={question.id}><span>{question.component}</span><div className="v2-mini-track"><i style={{ width: `${(latest.answers[question.id] ?? 0) * 20}%` }} /></div><strong>{latest.answers[question.id] ?? '—'}</strong></div>)}</div>}</section>
  }

  if (view === 'unit-results') {
    return <section className="v2-card v2-unit-results-blocked" aria-labelledby="unit-results-heading">
      <div className="v2-section-heading"><div><p className="v2-overline">Захищені агрегати</p><h2 id="unit-results-heading">Результати підрозділу</h2></div><span className="v2-pill v2-pill-warm">Очікує погодження</span></div>
      <div className="v2-blocked-banner" role="status"><strong>Функція наразі заблокована</strong><p>Сервер поки не надає користувачу підтверджений підрозділ і захищені агреговані результати підрозділу. Цей екран не завантажує та не показує організаційні, персональні чи індивідуальні відповіді.</p></div>
      <p className="v2-muted">Потрібне окреме погодження контракту №5 і серверна перевірка ролі, членства в підрозділі та мінімального розміру групи.</p>
    </section>
  }

  return <section className="v2-content-grid"><div className="v2-card v2-welcome-card"><p className="v2-overline">Особистий кабінет</p><h2>Контролюйте власний прогрес</h2><p className="v2-muted">Проходьте персональні тестування, зберігайте чернетки та переглядайте власну історію у захищеному персональному сховищі.</p><div className="v2-card-actions"><button className="v2-button v2-button-primary" type="button" onClick={() => void startAttempt(assessments[0]?.id)}>Розпочати тестування</button><span className="v2-muted">{activeAttempt ? 'Є збережена чернетка' : 'Чернеток немає'}</span></div></div><div className="v2-card"><p className="v2-overline">Швидкий огляд</p><div className="v2-stat-grid v2-stat-grid-compact"><div><span>Прогрес</span><strong>{activeAttempt ? `${Math.round((answered / (questions.length || 1)) * 100)}%` : '—'}</strong></div><div><span>Історія</span><strong>{attempts.filter((attempt) => attempt.status === 'completed').length}</strong></div></div><p className="v2-muted">{notice || 'Оберіть розділ у меню, щоб продовжити.'}</p></div></section>
}
