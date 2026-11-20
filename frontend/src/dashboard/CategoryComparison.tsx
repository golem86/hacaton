import { useEffect, useMemo, useRef, useState } from 'react'
import Chart from 'chart.js/auto'
import type { ResultCategory, ResultComponent } from './types'
import { barWidth, categoryName, scoreText } from './format'
import { describeScore, scoreZone, ZoneBadge, zoneColor, ZoneLegend } from './maturity'
import { resultsSuppressed, SuppressionNote, visibleCategories as onlyVisible, visibleCells } from './suppression'
import './dashboard.css'

interface Props {
  categories: ResultCategory[]
  components: ResultComponent[]
  /** Мінімальний розмір групи циклу (k) для примітки про приховані групи. */
  minGroupSize?: number
  /** Прапорець `suppressed` розрізу з відповіді API. */
  suppressed?: boolean
}

const palette = ['#276456', '#4d9587', '#80ad73', '#b49755']

export function CategoryComparison({ categories: rawCategories, components, minGroupSize, suppressed = false }: Props) {
  const [mode, setMode] = useState<'chart' | 'table'>('chart')
  const [selectedCategories, setSelectedCategories] = useState<string[]>([])
  const canvasRef = useRef<HTMLCanvasElement>(null)
  // Сервер не перелічує прихованих груп; елементи старого формату з hidden: true відкидаються повністю.
  const categories = useMemo(() => onlyVisible(rawCategories), [rawCategories])
  const visibleCategories = useMemo(() => categories.filter(category => selectedCategories.includes(category.category)), [categories, selectedCategories])
  const hasSuppressed = suppressed || resultsSuppressed({ categories: rawCategories, components })

  useEffect(() => {
    setSelectedCategories(categories.map(category => category.category))
  }, [categories])

  useEffect(() => {
    const canvas = canvasRef.current
    if (mode !== 'chart' || !canvas || visibleCategories.length === 0 || components.length === 0) return

    const chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: components.map(component => `${component.code} · ${component.name}`),
        datasets: visibleCategories.map((category, index) => ({
          label: categoryName(category.category),
          data: components.map(component => cellFor(component, rawCategories, category.category)?.score ?? null),
          backgroundColor: palette[index % palette.length],
          borderRadius: 3,
          borderSkipped: false,
          maxBarThickness: 16,
        })),
      },
      options: {
        animation: false,
        indexAxis: 'y',
        maintainAspectRatio: false,
        responsive: true,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { min: 0, max: 100, grid: { color: '#e4ece8' }, ticks: { stepSize: 25, color: '#526762' } },
          y: {
            grid: { display: false },
            ticks: {
              color: '#17302f',
              font: { size: 12, weight: 600 },
              callback(value) {
                return this.chart.width < 560 ? components[Number(value)]?.code : this.getLabelForValue(Number(value))
              },
            },
          },
        },
        plugins: {
          legend: { position: 'bottom', labels: { color: '#17302f', usePointStyle: true, pointStyle: 'circle', padding: 16 } },
          tooltip: {
            filter: item => item.raw !== null,
            callbacks: { label: context => ` ${context.dataset.label}: ${Number(context.raw).toLocaleString('uk-UA', { maximumFractionDigits: 1 })} зі 100` },
          },
        },
      },
    })
    return () => chart.destroy()
  }, [components, mode, rawCategories, visibleCategories])

  function toggleCategory(category: string) {
    setSelectedCategories(current => current.includes(category)
      ? current.filter(item => item !== category)
      : [...current, category])
  }

  return (
    <section className="dashboard-panel" aria-labelledby="category-comparison-heading">
      <div className="dashboard-panel-heading">
        <div><p className="dashboard-kicker">Порівняння груп</p><h2 id="category-comparison-heading">За категоріями респондентів</h2></div>
        {categories.length > 0 && components.length > 0 && (
          <div className="view-switch" aria-label="Вигляд порівняння категорій">
            <button type="button" aria-pressed={mode === 'chart'} onClick={() => setMode('chart')}>Графік</button>
            <button type="button" aria-pressed={mode === 'table'} onClick={() => setMode('table')}>Таблиця</button>
          </div>
        )}
      </div>
      {categories.length === 0 || components.length === 0 ? (
        <p className="dashboard-empty">Даних для порівняння категорій немає.</p>
      ) : (
        <>
          <fieldset className="dashboard-category-filters">
            <legend>Показати категорії</legend>
            {categories.map(category => (
              <label key={category.category}>
                <input type="checkbox" checked={selectedCategories.includes(category.category)} onChange={() => toggleCategory(category.category)} />
                <span>{categoryName(category.category)}</span>
              </label>
            ))}
          </fieldset>
          {visibleCategories.length === 0 ? (
            <p className="dashboard-empty">Оберіть щонайменше одну категорію. Групи, приховані сервером, недоступні.</p>
          ) : mode === 'chart' ? (
            <>
              <div className="chart-frame category-chart-frame">
                <canvas ref={canvasRef} role="img" aria-label="Порівняльна діаграма балів компонентів за категоріями респондентів, шкала від 0 до 100" />
                <ul className="sr-only">{components.flatMap(component => visibleCategories.map(category => (
                  <li key={`${component.code}-${category.category}`}>{component.code}, {categoryName(category.category)}: {scoreText(cellFor(component, rawCategories, category.category)?.score ?? null)}</li>
                )))}</ul>
              </div>
              <p className="dashboard-chart-note">Повні назви компонентів доступні в підказках і таблиці. Групи, менші за поріг, сервер не передає.</p>
            </>
          ) : (
            <>
              <p className="dashboard-scroll-cue">Прокрутіть таблицю вбік, щоб переглянути всі категорії →</p>
              <div className="dashboard-table-scroll" role="region" aria-label="Порівняння категорій, таблиця з горизонтальним прокручуванням" tabIndex={0}>
                <table className="dashboard-table">
                  <caption>Бали компонентів за категоріями, шкала 0–100. Групи, менші за поріг, не показано.</caption>
                  <thead><tr><th scope="col">Компонент</th>{visibleCategories.map(category => <th scope="col" key={category.category}>{categoryName(category.category)}<small>{category.responses == null ? 'Немає даних' : `${category.responses.toLocaleString('uk-UA')} відповідей`}</small></th>)}</tr></thead>
                  <tbody>{components.map(component => <tr key={component.code}>
                    <th scope="row"><span className="dashboard-code">{component.code}</span> {component.name}</th>
                    {visibleCategories.map(category => {
                      const cell = cellFor(component, rawCategories, category.category)
                      // Zones are derived only from scores the server sent for visible groups.
                      return <td key={category.category}>
                        {cell?.score == null ? 'Немає даних' : <div className="dashboard-category-score" title={describeScore(cell.score)}><span className="dashboard-mini-track" aria-hidden="true"><span style={{ width: barWidth(cell.score), background: zoneColor(cell.score) }} /></span><span>{scoreText(cell.score)}</span><ZoneBadge zone={scoreZone(cell.score)} short /></div>}
                      </td>
                    })}
                  </tr>)}</tbody>
                </table>
              </div>
              <ZoneLegend note="Зони визначено лише для балів показаних груп." />
            </>
          )}
        </>
      )}
      {hasSuppressed && <SuppressionNote k={minGroupSize} />}
    </section>
  )
}

function cellFor(component: ResultComponent, categories: readonly ResultCategory[], category: string) {
  return visibleCells(component, categories).find(item => item.category === category)
}
