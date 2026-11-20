import type { AssessmentResults } from './types'
import './dashboard.css'

interface Props {
  results: AssessmentResults
}

export function DashboardSummary({ results }: Props) {
  const scoredComponents = results.components.filter((component) => component.score !== null).length
  const visibleCategories = results.categories.filter((category) => !category.hidden).length

  return (
    <section className="dashboard-summary" aria-label="Ключові агреговані показники">
      <div className="dashboard-kpi dashboard-kpi-primary">
        <span>Відповідей у циклі</span>
        <strong>{results.responses_total === null ? 'Приховано' : results.responses_total.toLocaleString('uk-UA')}</strong>
        <small>{results.responses_total === null ? 'Підсумок не показано через мінімальний розмір групи' : 'Лише агрегований підсумок'}</small>
      </div>
      <div className="dashboard-kpi">
        <span>Компонентів із балом</span>
        <strong>{scoredComponents} <small>з {results.components.length}</small></strong>
        <small>Бали за шкалою 0–100</small>
      </div>
      <div className="dashboard-kpi">
        <span>Доступних категорій</span>
        <strong>{visibleCategories} <small>з {results.categories.length}</small></strong>
        <small>Малі групи приховано</small>
      </div>
    </section>
  )
}
