import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { getAssessment, getAssessments, type Assessment } from './api/assessments'
import {
  CategoryComparison,
  ComponentScores,
  DashboardSummary,
  ObjectiveIndicators,
  PendingModules,
  type AssessmentResults,
} from './dashboard'
import { loadResults } from './dashboard/loadResults'
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
  const [results, setResults] = useState<AssessmentResults | null>(null)
  const [resultsLoading, setResultsLoading] = useState(false)
  const [resultsError, setResultsError] = useState('')
  const [resultsRetry, setResultsRetry] = useState(0)

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
    setSelectedAssessment(null)
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

  useEffect(() => {
    setResults(null)
    setResultsError('')
    setResultsLoading(false)

    if (!selectedAssessment || selectedAssessment.id !== selectedId || selectedAssessment.status !== 'closed') return

    setResultsLoading(true)
    return loadResults(selectedAssessment.id, setResults, setResultsError, () => setResultsLoading(false))
  }, [selectedAssessment, selectedId, resultsRetry])

  function selectAssessment(value: string) {
    setSelectedId(value ? Number(value) : null)
    setSelectedAssessment(null)
    setDetailError('')
    setResults(null)
    setResultsError('')
  }

  return (
    <main className="page">
      <header className="page-header">
        <p className="eyebrow">Integrity Management Dashboard · Building Integrity Hackathon 2026</p>
        <h1>Панель доброчесності</h1>
        <p>Огляд результатів оцінювання для управлінських рішень. Оберіть цикл, щоб побачити доступні агреговані дані.</p>
      </header>
      <section className="assessment" aria-labelledby="assessment-heading">
        <div className="assessment-heading-row">
          <div>
            <p className="section-kicker">Контекст огляду</p>
            <h2 id="assessment-heading">Цикл оцінювання</h2>
          </div>
          {selectedAssessment && (
            <span className={`cycle-badge ${selectedAssessment.status === 'open' ? 'cycle-badge-open' : ''}`}>
              {selectedAssessment.status === 'closed' ? 'Цикл закрито' : 'Цикл відкрито'}
            </span>
          )}
        </div>

        {listLoading && <p role="status">Завантажуємо цикли оцінювання…</p>}
        {listError && (
          <div role="alert">
            <p>{listError}</p>
            <button type="button" onClick={() => setListRetry((value) => value + 1)}>Спробувати ще раз</button>
          </div>
        )}
        {!listLoading && !listError && assessments.length === 0 && <p>Циклів оцінювання поки немає.</p>}
        {!listLoading && !listError && assessments.length > 0 && (
          <div className="assessment-select-wrap">
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
          </div>
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
        <p className="demo-note">Демо-доступ через X-Role: manager. Це не автентифікація.</p>
      </section>
      <section className="dashboard-content" aria-labelledby="dashboard-heading">
        <div className="dashboard-intro">
          <div>
            <p className="section-kicker">Executive Dashboard</p>
            <h2 id="dashboard-heading">Результати циклу</h2>
            <p>Бали компонентів, доступні порівняння та об’єктивні показники. Індивідуальні відповіді не відображаються.</p>
          </div>
        </div>

        {selectedId === null && <p className="dashboard-state dashboard-state-empty">Оберіть цикл оцінювання, щоб переглянути доступні дані.</p>}
        {detailLoading && <p className="dashboard-state" role="status">Перевіряємо стан циклу…</p>}
        {!detailLoading && !detailError && selectedAssessment?.status === 'open' && (
          <div className="dashboard-state dashboard-state-open" role="status">
            <strong>Цикл оцінювання ще триває</strong>
            <p>Результати стануть доступними після його закриття. До того часу агреговані бали не відображаються.</p>
          </div>
        )}
        {resultsLoading && <p className="dashboard-state" role="status">Завантажуємо агреговані результати…</p>}
        {resultsError && (
          <div className="dashboard-state dashboard-state-error" role="alert">
            <p>{resultsError}</p>
            <button type="button" onClick={() => setResultsRetry((value) => value + 1)}>Спробувати ще раз</button>
          </div>
        )}
        {!detailLoading && !detailError && !resultsLoading && !resultsError && results && selectedAssessment?.id === results.assessment.id && (
          <>
            <DashboardSummary results={results} />
            <ComponentScores components={results.components} />
            <CategoryComparison categories={results.categories} components={results.components} />
            <ObjectiveIndicators components={results.components} />
          </>
        )}
      </section>
      <PendingModules />
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode><App /></StrictMode>,
)
