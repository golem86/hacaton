import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { getAssessment, getAssessments, type Assessment } from './api/assessments'
import './style.css'

function App() {
  const [assessments, setAssessments] = useState<Assessment[]>([])
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState('')
  const [listRetry, setListRetry] = useState(0)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [selectedAssessment, setSelectedAssessment] = useState<Assessment | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [detailRetry, setDetailRetry] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setListLoading(true)
    setListError('')

    getAssessments(controller.signal)
      .then(setAssessments)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setListError(error instanceof Error ? error.message : 'Не вдалося завантажити цикли.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setListLoading(false)
      })

    return () => controller.abort()
  }, [listRetry])

  useEffect(() => {
    if (selectedId === null) return

    const controller = new AbortController()
    setDetailLoading(true)
    setDetailError('')

    getAssessment(selectedId, controller.signal)
      .then(setSelectedAssessment)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setDetailError(error instanceof Error ? error.message : 'Не вдалося завантажити цикл.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false)
      })

    return () => controller.abort()
  }, [selectedId, detailRetry])

  function selectAssessment(value: string) {
    setSelectedId(value ? Number(value) : null)
    setSelectedAssessment(null)
    setDetailError('')
  }

  return (
    <main className="page">
      <header>
        <p className="eyebrow">Building Integrity Hackathon 2026</p>
        <h1>Integrity Management Dashboard</h1>
        <p>Цифрове оцінювання системи доброчесності та підтримка управлінських рішень.</p>
      </header>
      <section className="assessment" aria-labelledby="assessment-heading">
        <h2 id="assessment-heading">Цикл оцінювання</h2>
        <p className="demo-note">Демо-доступ через X-Role: manager. Це не автентифікація.</p>

        {listLoading && <p role="status">Завантажуємо цикли оцінювання…</p>}
        {listError && (
          <div role="alert">
            <p>{listError}</p>
            <button type="button" onClick={() => setListRetry((value) => value + 1)}>Спробувати ще раз</button>
          </div>
        )}
        {!listLoading && !listError && assessments.length === 0 && <p>Циклів оцінювання поки немає.</p>}
        {!listLoading && !listError && assessments.length > 0 && (
          <>
            <label htmlFor="assessment-select">Оберіть цикл</label>
            <select
              id="assessment-select"
              value={selectedId ?? ''}
              onChange={(event) => selectAssessment(event.target.value)}
            >
              <option value="">Оберіть цикл оцінювання</option>
              {assessments.map((assessment) => (
                <option key={assessment.id} value={assessment.id}>{assessment.name}</option>
              ))}
            </select>
          </>
        )}

        {detailLoading && <p role="status">Завантажуємо деталі циклу…</p>}
        {detailError && (
          <div role="alert">
            <p>{detailError}</p>
            <button type="button" onClick={() => setDetailRetry((value) => value + 1)}>Спробувати ще раз</button>
          </div>
        )}
        {!detailLoading && !detailError && selectedAssessment && (
          <dl className="details">
            <div><dt>Назва</dt><dd>{selectedAssessment.name}</dd></div>
            <div><dt>Статус</dt><dd>{selectedAssessment.status === 'open' ? 'Відкритий' : 'Закритий'}</dd></div>
            <div><dt>Дата початку</dt><dd>{selectedAssessment.start_date}</dd></div>
            <div><dt>Мінімальний розмір групи</dt><dd>{selectedAssessment.min_group_size}</dd></div>
          </dl>
        )}
      </section>
      <nav aria-label="Основна навігація">
        <ul>
          <li><span>Опитування</span><small>У розробці</small></li>
          <li><span>Аналітика</span><small>У розробці</small></li>
          <li><span>Рекомендації</span><small>У розробці</small></li>
        </ul>
      </nav>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode><App /></StrictMode>,
)
