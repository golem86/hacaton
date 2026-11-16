import './dashboard.css'

const modules = [
  { title: 'Integrity Index', description: 'Очікує затвердженої методики та API індексу.' },
  { title: 'Recommendations', description: 'Очікує API рекомендацій.' },
  { title: 'Comparative Analytics', description: 'Очікує API порівняння циклів.' },
  { title: 'Reporting / PDF / XLSX', description: 'Очікує серверного API звітів та експорту.' },
]

export function PendingModules() {
  return (
    <section className="dashboard-pending" aria-labelledby="pending-heading">
      <div className="dashboard-panel-heading">
        <div>
          <p className="dashboard-kicker">Наступні модулі</p>
          <h2 id="pending-heading">Наступні можливості</h2>
        </div>
      </div>
      <ul>
        {modules.map((module) => (
          <li key={module.title}>
            <strong>{module.title}</strong>
            <span>{module.description}</span>
            <small>Поки недоступно</small>
          </li>
        ))}
      </ul>
    </section>
  )
}
