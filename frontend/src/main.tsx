import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

function App() {
  return (
    <main className="page">
      <header>
        <p className="eyebrow">Building Integrity Hackathon 2026</p>
        <h1>Симулятор етичних дилем</h1>
        <p>Спільна стартова сторінка проєкту. Розділи з’являться після інтеграції модулів команди.</p>
      </header>
      <nav aria-label="Основна навігація">
        <ul>
          <li><span>Опитування</span><small>У розробці</small></li>
          <li><span>Аналітика</span><small>У розробці</small></li>
          <li><span>Рекомендації</span><small>У розробці</small></li>
        </ul>
      </nav>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode><App /></StrictMode>,
)
