import type { ResultComponent } from './types'
import { barWidth, scoreText } from './format'
import './dashboard.css'

interface Props {
  components: ResultComponent[]
}

export function ComponentScores({ components }: Props) {
  return (
    <section className="dashboard-panel" aria-labelledby="component-scores-heading">
      <div className="dashboard-panel-heading">
        <div>
          <p className="dashboard-kicker">Агреговані результати</p>
          <h2 id="component-scores-heading">Бали компонентів</h2>
        </div>
        <span className="dashboard-scale">Шкала 0 · 50 · 100</span>
      </div>
      {components.length === 0 ? (
        <p className="dashboard-empty">Для цього циклу ще немає результатів компонентів.</p>
      ) : (
        <div className="dashboard-score-list">
          <div className="dashboard-score-axis-row" aria-hidden="true">
            <span />
            <div className="dashboard-score-axis"><span>0</span><span>50</span><span>100</span></div>
            <span />
          </div>
          {components.map((component) => (
            <div className="dashboard-score-row" key={component.code}>
              <div className="dashboard-score-label">
                <span className="dashboard-code">{component.code}</span>
                <span>{component.name}</span>
              </div>
              <div className="dashboard-score-track" aria-hidden="true">
                {component.score !== null && (
                  <span className="dashboard-score-fill" style={{ width: barWidth(component.score) }} />
                )}
              </div>
              <strong className="dashboard-score-value">{scoreText(component.score)}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
