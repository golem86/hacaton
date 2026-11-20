import { useState } from 'react'
import { getOfficialTemplate, officialTemplates } from './catalog'
import { validateOfficialAnswers, type OfficialAnswers } from './validation'

type Mode = 'self' | 'expert'

export default function OfficialAssessment({ mode }: { mode: Mode }) {
  const [templateKey, setTemplateKey] = useState(`${officialTemplates[0].id}@${officialTemplates[0].version}`)
  const [answers, setAnswers] = useState<OfficialAnswers>({})
  const [index, setIndex] = useState(0)
  const [showErrors, setShowErrors] = useState(false)
  const [review, setReview] = useState(false)
  const [notice, setNotice] = useState('')
  const [id, version] = templateKey.split('@')
  const template = getOfficialTemplate(id, version)
  if (!template) return <section className="v2-card" role="alert">Версію анкети не знайдено.</section>

  const questions = template.questions
  const question = questions[index]
  const errors = validateOfficialAnswers(template, answers)
  const answered = questions.length - Object.keys(errors).length
  const sections = [...new Set(questions.map(item => item.source.section))]
  const selectTemplate = (key: string) => {
    setTemplateKey(key); setAnswers({}); setShowErrors(false); setIndex(0); setReview(false); setNotice('')
  }
  const jump = (next: number) => { setIndex(next); setReview(false); setNotice('') }
  const check = () => {
    setShowErrors(true)
    if (Object.keys(errors).length) {
      setNotice(`Пропущено обов'язкових відповідей: ${Object.keys(errors).length}. Перейдіть до позначених питань.`)
      setReview(false)
    } else {
      setReview(true)
      setNotice('Локальну перевірку завершено. Це лише перегляд: серверне збереження й подання недоступні.')
    }
  }

  return <section className="v2-card official-assessment" aria-label={mode === 'expert' ? 'Експертне оцінювання' : 'Офіційна анкета'}>
    <h2>{mode === 'expert' ? 'Експертне оцінювання · WIP Preview' : 'Офіційна анкета · WIP Preview'}</h2>
    <p>Джерело: Додаток В, друковані с. 53–66. У PDF: Анкета 1 — 12 питань, Анкета 2 — 10 питань. {template.version === '2.0.0' ? 'Ця версія охоплює всі питання відповідної анкети в адаптованому викладі.' : 'Ця версія охоплює лише піднабір питань.'}</p>
    <p role="status">Відповіді перебувають тільки в пам’яті цієї вкладки. Збереження і подання недоступні.</p>
    {mode === 'expert' && <p>Адміністративна сесія відкриває лише preview. Серверної ролі експерта та сховища експертних оцінок ще немає.</p>}
    <label htmlFor="official-template">Шаблон і версія</label>
    <select id="official-template" value={templateKey} onChange={event => selectTemplate(event.target.value)}>
      {officialTemplates.map(item => <option key={`${item.id}@${item.version}`} value={`${item.id}@${item.version}`}>{item.title} · v{item.version}</option>)}
    </select>
    <p>{template.audienceNote}</p>
    {template.contentNote && <p>{template.contentNote}</p>}
    {template.sourceUrl && <p><a href={template.sourceUrl} target="_blank" rel="noreferrer">Офіційне джерело (PDF)</a></p>}
    <div className="official-progress" role="status" aria-live="polite">
      <span>Заповнено {answered} з {questions.length}</span>
      <progress value={answered} max={questions.length} aria-label="Прогрес заповнення" />
    </div>
    <nav className="official-question-nav" aria-label="Питання за розділами">
      {sections.map(section => <div key={section} className="official-section">
        <h3>{section}</h3>
        <div className="official-question-buttons">{questions.map((item, position) => item.source.section === section &&
          <button key={item.id} type="button" aria-current={!review && position === index ? 'step' : undefined}
            aria-label={`Питання ${position + 1}${showErrors && errors[item.id] ? ', відповідь обов’язкова' : ''}`}
            className={showErrors && errors[item.id] ? 'is-missing' : ''} onClick={() => jump(position)}>{position + 1}{answers[item.id] ? ' ✓' : ''}</button>)}</div>
      </div>)}
    </nav>
    {review ? <div className="official-review" aria-label="Перегляд відповідей">
      <h3>Перегляд заповненої форми</h3>
      <p>Цей перегляд не надсилає та не зберігає відповіді.</p>
      {questions.map((item, position) => <div key={item.id} className="official-review-item">
        <strong>{position + 1}. {item.text}</strong>
        <p>{item.options.find(option => option.id === answers[item.id])?.text}</p>
        <button type="button" className="v2-button" onClick={() => jump(position)}>Змінити відповідь {position + 1}</button>
      </div>)}
      <button type="button" className="v2-button" onClick={() => jump(index)}>Повернутися до питань</button>
    </div> : <div aria-live="polite">
      <p>Питання {index + 1} з {questions.length} · {question.source.section} · Додаток {question.source.appendix}, с. {question.source.page}, № {question.source.number}{question.wording === 'adapted' ? ' · адаптоване формулювання' : ''}{question.source_duplicate ? ' · дублікат у джерелі' : ''}</p>
      <fieldset aria-invalid={showErrors && !!errors[question.id]} aria-describedby={showErrors && errors[question.id] ? 'official-question-error' : undefined}>
        <legend>{question.text} <span className="official-required">(обов’язково)</span></legend>
        {question.options.map(option => <label key={option.id} className="official-option"><input type="radio" name={question.id} value={option.id} checked={answers[question.id] === option.id}
          onChange={() => { setAnswers(previous => ({ ...previous, [question.id]: option.id })); setNotice('') }} />{option.text}</label>)}
      </fieldset>
      {showErrors && errors[question.id] && <p id="official-question-error" role="alert">{errors[question.id]}</p>}
      <div className="official-actions">
        <button type="button" className="v2-button" disabled={index === 0} onClick={() => jump(index - 1)}>Назад</button>
        <button type="button" className="v2-button" disabled={index === questions.length - 1} onClick={() => jump(index + 1)}>Далі</button>
        <button type="button" className="v2-button v2-button-primary" onClick={check}>Перевірити відповіді</button>
      </div>
    </div>}
    {notice && <p role="status" aria-live="polite">{notice}</p>}
  </section>
}
