import { useEffect, useMemo, useRef, useState } from 'react'
import Chart from 'chart.js/auto'
import type { ResultComponent } from './types'
import { scoreText } from './format'
import './dashboard.css'

interface Props {
  components: ResultComponent[]
}

type SortMode = 'methodology' | 'highest' | 'lowest'

function sortComponents(components: ResultComponent[], mode: SortMode) {
  return [...components].sort((left, right) => {
    if (mode === 'methodology') return left.code.localeCompare(right.code, 'uk')
    if (left.score === null) return right.score === null ? left.code.localeCompare(right.code, 'uk') : 1
    if (right.score === null) return -1
    const difference = mode === 'highest' ? right.score - left.score : left.score - right.score
    return difference || left.code.localeCompare(right.code, 'uk')
  })
}

export function ComponentScores({ components }: Props) {
  const [mode, setMode] = useState<'chart' | 'radar' | 'list'>('chart')
  const [sortMode, setSortMode] = useState<SortMode>('methodology')
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const sorted = useMemo(() => sortComponents(components, sortMode), [components, sortMode])

  useEffect(() => {
    const canvas = canvasRef.current
    if ((mode !== 'chart' && mode !== 'radar') || !canvas || sorted.length === 0) return

    if (mode === 'radar') {
      const chart = new Chart(canvas, {
        type: 'radar',
        data: {
          labels: sorted.map(component => component.code),
          datasets: [{
            label: 'Бал компонента',
            data: sorted.map(component => component.score),
            borderColor: '#276456',
            backgroundColor: 'rgba(77, 149, 135, .18)',
            pointBackgroundColor: '#276456',
            pointBorderColor: '#ffffff',
            pointHoverRadius: 6,
            borderWidth: 2,
            spanGaps: false,
          }],
        },
        options: {
          animation: false,
          maintainAspectRatio: false,
          responsive: true,
          scales: {
            r: {
              min: 0,
              max: 100,
              beginAtZero: true,
              ticks: { stepSize: 25, showLabelBackdrop: false, color: '#526762', backdropColor: 'transparent' },
              grid: { color: '#dbe7e2' },
              angleLines: { color: '#dbe7e2' },
              pointLabels: { color: '#17302f', font: { size: 12, weight: 650 } },
            },
          },
          plugins: {
            legend: { display: false },
            tooltip: {
              filter: item => item.raw !== null,
              callbacks: {
                title: items => {
                  const component = sorted[items[0]?.dataIndex ?? -1]
                  return component ? `${component.code} · ${component.name}` : ''
                },
                label: context => `Бал: ${scoreText(Number(context.raw))}`,
              },
            },
          },
        },
      })
      return () => chart.destroy()
    }

    const chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: sorted.map(component => `${component.code} · ${component.name}`),
        datasets: [{
          label: 'Бал компонента',
          data: sorted.map(component => component.score),
          backgroundColor: sorted.map((_, index) => index === 0 ? '#276456' : '#4d9587'),
          borderRadius: 4,
          borderSkipped: false,
          maxBarThickness: 24,
        }],
      },
      options: {
        animation: false,
        indexAxis: 'y',
        maintainAspectRatio: false,
        responsive: true,
        scales: {
          x: { min: 0, max: 100, grid: { color: '#e4ece8' }, ticks: { stepSize: 25, color: '#526762' } },
          y: {
            grid: { display: false },
            ticks: {
              color: '#17302f',
              font: { size: 12, weight: 600 },
              callback(value) {
                return this.chart.width < 560 ? sorted[Number(value)]?.code : this.getLabelForValue(Number(value))
              },
            },
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            filter: item => item.raw !== null,
            callbacks: { label: context => ` ${Number(context.raw).toLocaleString('uk-UA', { maximumFractionDigits: 1 })} зі 100` },
          },
        },
      },
    })
    return () => chart.destroy()
  }, [mode, sorted])

  return (
    <section className="dashboard-panel" aria-labelledby="component-scores-heading">
      <div className="dashboard-panel-heading">
        <div>
          <p className="dashboard-kicker">Агреговані результати</p>
          <h2 id="component-scores-heading">Бали компонентів</h2>
          <p className="dashboard-panel-description">Сортування показує порядок балів. Повні назви компонентів доступні в підказках і списку.</p>
        </div>
        <div className="dashboard-panel-tools">
          <span className="dashboard-scale">Шкала 0–100</span>
          <div className="view-switch" aria-label="Вигляд балів компонентів">
            <button type="button" aria-pressed={mode === 'chart'} onClick={() => setMode('chart')}>Графік</button>
            <button type="button" aria-pressed={mode === 'radar'} onClick={() => setMode('radar')}>Радар</button>
            <button type="button" aria-pressed={mode === 'list'} onClick={() => setMode('list')}>Список</button>
          </div>
        </div>
      </div>
      {components.length === 0 ? (
        <p className="dashboard-empty">Для цього циклу ще немає результатів компонентів.</p>
      ) : (
        <>
          <label className="dashboard-sort">Сортування
            <select value={sortMode} onChange={event => setSortMode(event.target.value as SortMode)}>
              <option value="methodology">За кодом компонента</option>
              <option value="highest">Найвищі значення спочатку</option>
              <option value="lowest">Найнижчі значення спочатку</option>
            </select>
          </label>
          {mode === 'chart' || mode === 'radar' ? (
            <div className={`chart-frame component-chart-frame${mode === 'radar' ? ' radar-chart-frame' : ''}`}>
              <canvas ref={canvasRef} role="img" aria-label={mode === 'radar' ? 'Радарна діаграма оцінок компонентів C1–C7 за фіксованою шкалою від 0 до 100; повні назви й точні значення доступні у списку нижче та підказці графіка.' : 'Горизонтальна діаграма агрегованих балів компонентів за шкалою від 0 до 100'} />
              <ul className="sr-only">{sorted.map(component => <li key={component.code}>{component.code}, {component.name}: {scoreText(component.score)}</li>)}</ul>
            </div>
          ) : (
            <div className="dashboard-score-list">
              <div className="dashboard-score-axis-row" aria-hidden="true"><span /><div className="dashboard-score-axis"><span>0</span><span>50</span><span>100</span></div><span /></div>
              {sorted.map(component => (
                <div className="dashboard-score-row" key={component.code}>
                  <div className="dashboard-score-label"><span className="dashboard-code">{component.code}</span><span>{component.name}</span></div>
                  <div className="dashboard-score-track" role="img" aria-label={`${component.code}: ${scoreText(component.score)}`}>
                    {component.score !== null && <span className="dashboard-score-fill" style={{ width: `${Math.max(0, Math.min(100, component.score))}%` }} />}
                  </div>
                  <strong className="dashboard-score-value">{scoreText(component.score)}</strong>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
