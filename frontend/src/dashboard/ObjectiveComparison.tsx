import type { ObjectiveContextItem } from '../api/analytics'
import {
  REVIEW_RULE, localizeBackendText, objectiveReview, objectiveValueText, surveyScoreText,
} from './explain'
import './dashboard.css'
import './analytics-explain.css'

/**
 * Self-assessment next to objective indicators (objective_context from the
 * recommendations response). Context only: no numeric gap is computed.
 */
export function ObjectiveComparison({ items }: { items: ObjectiveContextItem[] | undefined }) {
  if (items === undefined) {
    return <p className="dashboard-empty">API не передав об’єктивного контексту для цього циклу, тому зіставлення недоступне.</p>
  }
  const rows = items.map(item => ({ item, review: objectiveReview(item) }))
  const flagged = rows.filter(row => row.review.needsReview).length
  const types = [...new Set(items.map(item => item.comparison_type ?? 'context_only'))]
  const reasons = [...new Set(items.flatMap(item => item.reason ? [localizeBackendText(item.reason)] : []))]

  return (
    <>
      <p className="analytics-notice">
        Порівняння контекстне (тип: {types.length > 0 ? types.join(', ') : 'context_only'}). Самооцінка — бал 0–100
        з опитування, а об’єктивні показники мають інші одиниці виміру, тому числовий розрив автоматично
        не обчислюється. Розбіжність — сигнал для перегляду посадовою особою, а не доказ порушень.
      </p>
      <p className="ax-rule"><strong>Правило позначки.</strong> {REVIEW_RULE}</p>
      {items.length === 0 ? (
        <p className="dashboard-empty">Об’єктивних показників для зіставлення немає.</p>
      ) : (
        <>
          <p className="ax-summary">Позначено «Потребує перевірки»: {flagged} з {items.length}.</p>
          <div className="ax-table-wrap">
            <table className="ax-table ax-table-stack ax-objective-table">
              <caption>Самооцінка компонента поруч з об’єктивним показником того самого циклу</caption>
              <thead>
                <tr>
                  <th scope="col">Компонент</th>
                  <th scope="col">Самооцінка</th>
                  <th scope="col">Об’єктивний показник</th>
                  <th scope="col">Значення</th>
                  <th scope="col">Статус показника</th>
                  <th scope="col">Перевірка</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ item, review }, index) => (
                  <tr key={`${item.component_code}-${item.name}-${index}`} className={review.needsReview ? 'ax-row-flagged' : undefined}>
                    <th scope="row"><span className="dashboard-code">{item.component_code}</span></th>
                    <td data-label="Самооцінка" className={item.survey_score === null ? 'ax-muted' : 'ax-num'}>
                      {surveyScoreText(item.survey_score)}
                    </td>
                    <td data-label="Об’єктивний показник">{item.name}</td>
                    <td data-label="Значення" className={item.objective_value === null ? 'ax-muted' : 'ax-num'}>
                      {objectiveValueText(item)}
                    </td>
                    <td data-label="Статус показника">
                      <span className={`dashboard-badge ${item.status === 'ok' ? 'dashboard-badge-confirmed' : 'dashboard-badge-pending'}`}>
                        {item.status === 'ok' ? 'Підтверджено' : 'Не підтверджено'}
                      </span>
                    </td>
                    <td data-label="Перевірка" className="ax-wide">
                      {review.needsReview ? (
                        <>
                          <span className="ax-flag">Потребує перевірки</span>
                          <span className="ax-reasons">Причина: {review.reasons.join('; ')}.</span>
                        </>
                      ) : <span className="ax-muted">Без позначки</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {reasons.length > 0 && (
        <p className="ax-meta">Чому числовий розрив не рахується: {reasons.join(' ')}</p>
      )}
    </>
  )
}
