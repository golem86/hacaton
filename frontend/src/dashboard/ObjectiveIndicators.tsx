import type { ResultComponent } from './types'
import './dashboard.css'

interface Props {
  components: ResultComponent[]
}

export function ObjectiveIndicators({ components }: Props) {
  const withIndicators = components.filter((component) => component.objective_indicators.length > 0)

  return (
    <section className="dashboard-panel" aria-labelledby="objective-indicators-heading">
      <div className="dashboard-panel-heading">
        <div>
          <p className="dashboard-kicker">Об’єктивні дані</p>
          <h2 id="objective-indicators-heading">Показники циклу</h2>
        </div>
      </div>
      {withIndicators.length === 0 ? (
        <p className="dashboard-empty">Об’єктивних показників для цього циклу немає.</p>
      ) : (
        <div className="dashboard-indicator-groups">
          {withIndicators.map((component) => (
            <section key={component.code} aria-label={`${component.code}: ${component.name}`}>
              <h3><span className="dashboard-code">{component.code}</span> {component.name}</h3>
              <dl className="dashboard-indicators">
                {component.objective_indicators.map((indicator, index) => (
                  <div key={`${indicator.name}-${index}`}>
                    <dt>{indicator.name}</dt>
                    <dd>
                      <strong>{indicator.value.toLocaleString('uk-UA', { maximumFractionDigits: 1 })}{/%\s*$/.test(indicator.name) ? '%' : ''}</strong>
                      <span className={indicator.confirmed ? 'dashboard-badge dashboard-badge-confirmed' : 'dashboard-badge dashboard-badge-pending'}>
                        {indicator.confirmed ? 'Підтверджено' : 'Не підтверджено'}
                      </span>
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      )}
    </section>
  )
}
