import type { AssessmentResults } from './types'
import { resultsSuppressed, suppressionNoteText, visibleCategories } from './suppression'
import './dashboard.css'

interface Props {
  results: AssessmentResults
}

export function DashboardSummary({ results }: Props) {
  const scoredComponents = results.components.filter((component) => component.score !== null).length
  // Hidden groups are not listed by the server, so only the visible count is known.
  const shownCategories = visibleCategories(results.categories).length
  const suppressed = resultsSuppressed(results)

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
        <span>Показаних категорій</span>
        <strong>{shownCategories}</strong>
        <small>{suppressed ? suppressionNoteText(results.min_group_size) : 'Усі групи досягли порогу'}</small>
      </div>
    </section>
  )
}
