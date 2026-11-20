import { useEffect, useMemo, useRef, useState } from 'react'
import Chart from 'chart.js/auto'
import type { ResultCategory, ResultComponent } from './types'
import { barWidth, categoryName, scoreText } from './format'
import './dashboard.css'

interface Props {
  categories: ResultCategory[]
  components: ResultComponent[]
}

const palette = ['#276456', '#4d9587', '#80ad73', '#b49755']

export function CategoryComparison({ categories, components }: Props) {
  const [mode, setMode] = useState<'chart' | 'table'>('chart')
  const [selectedCategories, setSelectedCategories] = useState<string[]>([])
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const visibleCategories = useMemo(() => categories.filter(category => selectedCategories.includes(category.category)), [categories, selectedCategories])
  const hasSuppressed = categories.some(category => category.hidden
    || components.some(component => component.by_category.some(cell => cell.category === category.category && cell.hidden)))

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
          data: components.map(component => {
            const cell = component.by_category.find(item => item.category === category.category)
            return category.hidden || cell?.hidden === true ? null : cell?.score ?? null
          }),
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
  }, [components, mode, visibleCategories])

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
                {category.hidden && <small>Приховано</small>}
              </label>
            ))}
          </fieldset>
          {visibleCategories.length === 0 ? (
            <p className="dashboard-empty">Оберіть щонайменше одну категорію. Приховані сервером дані залишаються недоступними.</p>
          ) : mode === 'chart' ? (
            <>
              <div className="chart-frame category-chart-frame">
                <canvas ref={canvasRef} role="img" aria-label="Порівняльна діаграма балів компонентів за категоріями респондентів, шкала від 0 до 100" />
                <ul className="sr-only">{components.flatMap(component => visibleCategories.map(category => {
                  const cell = component.by_category.find(item => item.category === category.category)
                  const hidden = category.hidden || cell?.hidden === true
                  return <li key={`${component.code}-${category.category}`}>{component.code}, {categoryName(category.category)}: {hidden ? 'Приховано' : scoreText(cell?.score ?? null)}</li>
                }))}</ul>
              </div>
              <p className="dashboard-chart-note">Повні назви компонентів доступні в підказках і таблиці. Бали прихованих груп не показано.</p>
            </>
          ) : (
            <>
              <p className="dashboard-scroll-cue">Прокрутіть таблицю вбік, щоб переглянути всі категорії →</p>
              <div className="dashboard-table-scroll" role="region" aria-label="Порівняння категорій, таблиця з горизонтальним прокручуванням" tabIndex={0}>
                <table className="dashboard-table">
                  <caption>Бали компонентів за категоріями, шкала 0–100. Приховані групи не показують бали й кількість відповідей.</caption>
                  <thead><tr><th scope="col">Компонент</th>{visibleCategories.map(category => <th scope="col" key={category.category}>{categoryName(category.category)}<small>{category.hidden ? 'Приховано' : category.responses === null ? 'Немає даних' : `${category.responses.toLocaleString('uk-UA')} відповідей`}</small></th>)}</tr></thead>
                  <tbody>{components.map(component => <tr key={component.code}>
                    <th scope="row"><span className="dashboard-code">{component.code}</span> {component.name}</th>
                    {visibleCategories.map(category => {
                      const cell = component.by_category.find(item => item.category === category.category)
                      const hidden = category.hidden || cell?.hidden === true
                      return <td key={category.category} className={hidden ? 'dashboard-hidden' : undefined}>
                        {hidden ? 'Приховано' : cell?.score == null ? 'Немає даних' : <div className="dashboard-category-score"><span className="dashboard-mini-track" aria-hidden="true"><span style={{ width: barWidth(cell.score) }} /></span><span>{scoreText(cell.score)}</span></div>}
                      </td>
                    })}
                  </tr>)}</tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
      {hasSuppressed && <p className="dashboard-privacy-note">Бали та кількість відповідей малих груп приховано для захисту анонімності.</p>}
    </section>
  )
}
