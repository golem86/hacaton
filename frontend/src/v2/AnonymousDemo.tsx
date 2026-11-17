import { useEffect, useMemo, useState } from 'react'
import { getAnonymousSurveys, submitAnonymousAnswers, type AnonymousSurvey } from '../api/v2Anonymous'

function submissionId() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `anonymous-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function AnonymousDemo() {
  const [survey, setSurvey] = useState<AnonymousSurvey | null>(null)
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [busy, setBusy] = useState(false)
  const answered = survey ? Object.keys(answers).length : 0
  const average = useMemo(() => {
    const values = Object.values(answers)
    return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
  }, [answers])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    getAnonymousSurveys(controller.signal)
      .then((items) => setSurvey(items[0] ?? null))
      .catch((nextError: unknown) => { if (!controller.signal.aborted) setError(nextError instanceof Error ? nextError.message : 'Не вдалося завантажити опитування.') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])

  async function submit() {
    if (!survey || answered !== survey.questions.length) return
    setBusy(true)
    setError('')
    try {
      await submitAnonymousAnswers(survey.id, submissionId(), answers)
      setSubmitted(true)
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : 'Не вдалося відправити анонімні відповіді.')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <section className="v2-card" role="status">Завантажуємо анонімне опитування…</section>
  if (error && !survey) return <section className="v2-card" role="alert"><div className="v2-empty"><strong>Опитування недоступне</strong><p className="v2-muted">{error}</p></div></section>
  if (!survey) return <section className="v2-card"><div className="v2-empty"><strong>Опитувань немає</strong><p className="v2-muted">Спробуйте пізніше.</p></div></section>

  return <section className="v2-card"><div className="v2-section-heading"><div><p className="v2-overline">Окремий режим</p><h2>{survey.name}</h2></div><span className="v2-pill v2-pill-warm">Без профілю</span></div><div className="v2-privacy-banner"><strong>Відповіді не пов’язані з користувачем</strong><span>Відповіді зберігаються в окремому анонімному сховищі та не додаються до особистої історії.</span></div><div className="v2-anonymous-list">{survey.questions.map((question, index) => <div className="v2-anonymous-question" key={question.id}><div><span className="v2-question-index">0{index + 1}</span><strong>{question.prompt}</strong></div><div className="v2-inline-scale">{[1, 2, 3, 4, 5].map((value) => <button type="button" className={answers[question.id] === value ? 'is-selected' : ''} key={value} onClick={() => setAnswers((current) => ({ ...current, [question.id]: value }))}>{value}</button>)}</div></div>)}</div><div className="v2-anonymous-footer"><span className="v2-muted">Заповнено {answered} з {survey.questions.length}</span><button className="v2-button" type="button" disabled={busy || submitted || answered < survey.questions.length} onClick={() => void submit()}>{submitted ? 'Відповіді надіслано' : busy ? 'Надсилаємо…' : 'Завершити анонімно'}</button></div>{error && <p className="v2-auth-error" role="alert">{error}</p>}{submitted && <div className="v2-success" role="status"><strong>Дякуємо за відповіді.</strong><span>Середнє значення цієї сесії: {average?.toFixed(1)} / 5. Результат не додано до особистої історії.</span></div>}</section>
}
