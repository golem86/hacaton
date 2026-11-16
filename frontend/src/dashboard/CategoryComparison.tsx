import type { ResultCategory, ResultComponent } from './types'
import { barWidth, categoryName, scoreText } from './format'
import './dashboard.css'

interface Props {
  categories: ResultCategory[]
  components: ResultComponent[]
}

export function CategoryComparison({ categories, components }: Props) {
  return (
    <section className="dashboard-panel" aria-labelledby="category-comparison-heading">
      <div className="dashboard-panel-heading">
        <div>
          <p className="dashboard-kicker">Порівняння груп</p>
          <h2 id="category-comparison-heading">За категоріями респондентів</h2>
        </div>
      </div>
      {categories.length === 0 || components.length === 0 ? (
        <p className="dashboard-empty">Даних для порівняння категорій немає.</p>
      ) : (
        <>
          <p className="dashboard-scroll-cue">Прокрутіть таблицю вбік, щоб переглянути всі категорії →</p>
          <div className="dashboard-table-scroll" role="region" aria-label="Порівняння категорій, таблиця з горизонтальним прокручуванням" tabIndex={0}>
          <table className="dashboard-table">
            <caption>Бали компонентів за категоріями, шкала 0–100. Приховані групи не показують бали й кількість відповідей.</caption>
            <thead>
              <tr>
                <th scope="col">Компонент</th>
                {categories.map((category) => (
                  <th scope="col" key={category.category}>
                    {categoryName(category.category)}
                    <small>{category.hidden ? 'Приховано' : category.responses === null ? 'Немає даних' : `${category.responses.toLocaleString('uk-UA')} відповідей`}</small>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {components.map((component) => (
                <tr key={component.code}>
                  <th scope="row"><span className="dashboard-code">{component.code}</span> {component.name}</th>
                  {categories.map((category) => {
                    const cell = component.by_category.find((item) => item.category === category.category)
                    const hidden = category.hidden || cell?.hidden === true
                    return (
                      <td key={category.category} className={hidden ? 'dashboard-hidden' : undefined}>
                        {hidden ? 'Приховано' : cell?.score == null ? 'Немає даних' : (
                          <div className="dashboard-category-score">
                            <span className="dashboard-mini-track" aria-hidden="true"><span style={{ width: barWidth(cell.score) }} /></span>
                            <span>{scoreText(cell.score)}</span>
                          </div>
                        )}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </>
      )}
      {categories.some((category) => category.hidden) && (
        <p className="dashboard-privacy-note">Бали та кількість відповідей малих груп приховано для захисту анонімності.</p>
      )}
    </section>
  )
}
