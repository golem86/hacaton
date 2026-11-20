import { useEffect, useState } from 'react'
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
    return <section className="v2-card"><div className="v2-section-heading"><div><p className="v2-overline">Особисті тестування</p><h2>Доступні тестування</h2></div><span className="v2-pill">Особистий простір</span></div><div className="v2-test-list">{assessments.map((assessment, index) => { const draft = attempts.find((attempt) => attempt.assessment_id === assessment.id && attempt.status === 'draft'); return <article className="v2-test-item" key={assessment.id}><div><span className="v2-test-number">0{index + 1}</span><h3>{assessment.name}</h3><p className="v2-muted">{assessment.duration}</p><p className="v2-deadline">{assessment.status === 'open' ? `Доступне до ${formatDeadline(assessment.closes_at)}` : `Недоступне · період ${formatDeadline(assessment.opens_at)} — ${formatDeadline(assessment.closes_at)}`}</p></div><button className="v2-button" disabled={assessment.status !== 'open'} type="button" onClick={() => void startAttempt(assessment.id)}>{draft ? 'Продовжити' : assessment.status === 'open' ? 'Розпочати' : 'Недоступне'}</button></article> })}</div></section>
  }

  if (view === 'attempt') {
    const question = questions[questionIndex]
    const selected = question && activeAttempt ? activeAttempt.answers[question.id] : undefined
    return <section className="v2-card"><div className="v2-section-heading"><div><p className="v2-overline">Проходження тестування</p><h2>{activeAttempt?.assessment_name ?? 'Немає активної спроби'}</h2></div>{activeAttempt && <Progress answered={answered} total={questions.length} />}</div>{activeAttempt && question ? <><div className="v2-question-meta"><span>{question.component}</span><span>{question.hint}</span></div><h3 className="v2-question">{question.prompt}</h3><div className="v2-scale">{[1, 2, 3, 4, 5].map((value) => <button type="button" className={selected === value ? 'v2-scale-option is-selected' : 'v2-scale-option'} key={value} onClick={() => void updateAnswer(value)}><strong>{value}</strong><span>{value === 1 ? 'Зовсім ні' : value === 5 ? 'Повністю' : ''}</span></button>)}</div><div className="v2-attempt-actions"><button className="v2-button v2-button-quiet" type="button" disabled={questionIndex === 0} onClick={() => setQuestionIndex((value) => value - 1)}>Назад</button>{questionIndex < questions.length - 1 ? <button className="v2-button" type="button" onClick={() => setQuestionIndex((value) => value + 1)}>Далі</button> : <button className="v2-button v2-button-primary" type="button" onClick={() => void finishAttempt()}>Завершити тестування</button>}</div><p className="v2-inline-note" role="status">{notice || 'Чернетка зберігається у серверному сховищі.'}</p></> : <div className="v2-empty"><p>Активної чернетки немає.</p><button className="v2-button" type="button" onClick={() => void startAttempt(assessments[0]?.id)}>Розпочати тестування</button></div>}</section>
  }

  if (view === 'history') {
    const completed = attempts.filter((attempt) => attempt.status === 'completed')
    return <section className="v2-card"><div className="v2-section-heading"><div><p className="v2-overline">Історія проходжень</p><h2>Завершені проходження</h2></div><span className="v2-pill">{completed.length} записів</span></div>{completed.length ? <div className="v2-history-list">{completed.map((attempt) => <article className="v2-history-item" key={attempt.id}><div><strong>{attempt.assessment_name}</strong><p className="v2-muted">{attempt.completed_at ? formatDate(attempt.completed_at) : 'Чернетка'}</p></div><span className="v2-score-chip">{averageAnswer(attempt)?.toFixed(1) ?? '—'} / 5</span></article>)}</div> : <div className="v2-empty"><strong>Історія поки порожня</strong><p className="v2-muted">Завершіть тестування, щоб побачити запис.</p></div>}</section>
  }

  if (view === 'stats') {
    return <section className="v2-card"><div className="v2-section-heading"><div><p className="v2-overline">Персональна статистика</p><h2>Персональний прогрес</h2></div><span className="v2-pill">Без Integrity Index</span></div><div className="v2-stat-grid"><div><span>Завершено тестів</span><strong>{stats?.completed_tests ?? 0}</strong></div><div><span>Відповідей</span><strong>{stats?.responses_total ?? 0}</strong></div><div><span>Середня відповідь</span><strong>{stats?.average_response?.toFixed(1) ?? '—'}<small> / 5</small></strong></div></div><p className="v2-muted">Показано лише фактичні відповіді та прогрес. Офіційний індекс доброчесності не розраховується без затвердженої методики.</p>{latest && <div className="v2-component-mini">{(assessments.find((assessment) => assessment.id === latest.assessment_id)?.questions ?? []).map((question) => <div key={question.id}><span>{question.component}</span><div className="v2-mini-track"><i style={{ width: `${(latest.answers[question.id] ?? 0) * 20}%` }} /></div><strong>{latest.answers[question.id] ?? '—'}</strong></div>)}</div>}</section>
  }

  if (view === 'unit-results') {
    return <section className="v2-card v2-unit-results-blocked" aria-labelledby="unit-results-heading">
      <div className="v2-section-heading"><div><p className="v2-overline">Захищені агрегати</p><h2 id="unit-results-heading">Результати підрозділу</h2></div><span className="v2-pill v2-pill-warm">Очікує API-контракт</span></div>
      <div className="v2-blocked-banner" role="status"><strong>Функція наразі заблокована</strong><p>Backend не надає користувачу підтверджений підрозділ і захищені агреговані результати підрозділу. Цей екран не завантажує та не показує організаційні, персональні чи індивідуальні відповіді.</p></div>
      <p className="v2-muted">Потрібне окреме погодження контракту №5 і серверна перевірка ролі, членства в підрозділі та мінімального розміру групи.</p>
    </section>
  }

  return <section className="v2-content-grid"><div className="v2-card v2-welcome-card"><p className="v2-overline">Особистий кабінет</p><h2>Контролюйте власний прогрес</h2><p className="v2-muted">Проходьте персональні тестування, зберігайте чернетки та переглядайте власну історію у захищеному персональному сховищі.</p><div className="v2-card-actions"><button className="v2-button v2-button-primary" type="button" onClick={() => void startAttempt(assessments[0]?.id)}>Розпочати тестування</button><span className="v2-muted">{activeAttempt ? 'Є збережена чернетка' : 'Чернеток немає'}</span></div></div><div className="v2-card"><p className="v2-overline">Швидкий огляд</p><div className="v2-stat-grid v2-stat-grid-compact"><div><span>Прогрес</span><strong>{activeAttempt ? `${Math.round((answered / (questions.length || 1)) * 100)}%` : '—'}</strong></div><div><span>Історія</span><strong>{attempts.filter((attempt) => attempt.status === 'completed').length}</strong></div></div><p className="v2-muted">{notice || 'Оберіть розділ у меню, щоб продовжити.'}</p></div></section>
}
