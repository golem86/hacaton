import { useEffect, useRef, useState } from 'react'
import Chart from 'chart.js/auto'
import type { ResultComponent } from './types'
import { scoreText } from './format'
import './dashboard.css'

interface Props {
  components: ResultComponent[]
}

export function ComponentScores({ components }: Props) {
  const [mode, setMode] = useState<'chart' | 'list'>('chart')
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (mode !== 'chart' || !canvasRef.current || components.length === 0) return

    const chart = new Chart(canvasRef.current, {
      type: 'bar',
      data: {
        labels: components.map((component) => `${component.code} · ${component.name}`),
        datasets: [{
          label: 'Бал компонента',
          data: components.map((component) => component.score),
          backgroundColor: components.map((_, index) => index === 0 ? '#276456' : '#4d9587'),
          borderRadius: 5,
          borderSkipped: false,
          maxBarThickness: 27,
        }],
      },
      options: {
        indexAxis: 'y',
        maintainAspectRatio: false,
        responsive: true,
        scales: {
          x: { min: 0, max: 100, grid: { color: '#e8efec' }, ticks: { stepSize: 25, color: '#516663' } },
          y: { grid: { display: false }, ticks: { color: '#17302f', font: { size: 12, weight: 600 } } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            filter: (item) => item.raw !== null,
            callbacks: { label: (context) => ` ${Number(context.raw).toLocaleString('uk-UA', { maximumFractionDigits: 1 })} зі 100` },
          },
        },
      },
    })

    return () => chart.destroy()
  }, [components, mode])

  return (
    <section className="dashboard-panel" aria-labelledby="component-scores-heading">
      <div className="dashboard-panel-heading">
        <div>
          <p className="dashboard-kicker">Агреговані результати</p>
          <h2 id="component-scores-heading">Бали компонентів</h2>
        </div>
        <div className="dashboard-panel-tools">
          <span className="dashboard-scale">Шкала 0–100</span>
          <div className="view-switch" aria-label="Вигляд балів компонентів">
            <button type="button" aria-pressed={mode === 'chart'} onClick={() => setMode('chart')}>Графік</button>
            <button type="button" aria-pressed={mode === 'list'} onClick={() => setMode('list')}>Список</button>
          </div>
        </div>
      </div>
      {components.length === 0 ? (
        <p className="dashboard-empty">Для цього циклу ще немає результатів компонентів.</p>
      ) : mode === 'chart' ? (
        <div className="chart-frame component-chart-frame">
          <canvas ref={canvasRef} role="img" aria-label="Горизонтальна діаграма агрегованих балів компонентів за шкалою від 0 до 100" />
          <ul className="sr-only">
            {components.map((component) => <li key={component.code}>{component.code}, {component.name}: {scoreText(component.score)}</li>)}
          </ul>
        </div>
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
                  <span className="dashboard-score-fill" style={{ width: `${Math.max(0, Math.min(100, component.score))}%` }} />
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
