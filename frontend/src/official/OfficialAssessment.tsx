import { useState } from 'react'
import { getOfficialTemplate, officialTemplates, type OfficialTemplate } from './catalog'
import { validateOfficialAnswers, type OfficialAnswers } from './validation'

type Mode = 'self' | 'expert'

/** Робочі позначки з каталогу (WIP Preview, preview) не показуємо користувачу; сам каталог не змінюється. */
export function presentableText(text: string) {
  return text.replace(/\s*Це WIP Preview без серверного збереження\./g, '').replace(/\bpreview\b/gi, 'перегляд')
}

/** 1.x — часткові версії (піднабір питань); повні версії анкети починаються з 2.0.0. */
export function isPartialVersion(version: string) {
  return Number.parseInt(version, 10) < 2
}

const keyOf = (template: Pick<OfficialTemplate, 'id' | 'version'>) => `${template.id}@${template.version}`
/** У списку: новіша версія вище, у межах версії — Анкета 1, потім Анкета 2. */
const newestFirst = (a: OfficialTemplate, b: OfficialTemplate) =>
  b.version.localeCompare(a.version, undefined, { numeric: true }) || a.id.localeCompare(b.id)
const fullTemplates = officialTemplates.filter(template => !isPartialVersion(template.version)).sort(newestFirst)
const partialTemplates = officialTemplates.filter(template => isPartialVersion(template.version)).sort(newestFirst)

/** За замовчуванням — найновіша повна версія першої анкети (зараз 2.1.0), а не частковий 1.0.0. */
export const defaultTemplateKey = keyOf(
  fullTemplates.find(template => template.id === officialTemplates[0].id) ?? officialTemplates[0])

/** Кількість питань у повній версії тієї самої анкети — для позначки покриття часткової версії. */
function fullQuestionCount(id: string) {
  return fullTemplates.find(template => template.id === id)?.questions.length
}

export default function OfficialAssessment({ mode }: { mode: Mode }) {
  const [templateKey, setTemplateKey] = useState(defaultTemplateKey)
  const [answers, setAnswers] = useState<OfficialAnswers>({})
  const [index, setIndex] = useState(0)
  const [showErrors, setShowErrors] = useState(false)
  const [review, setReview] = useState(false)
  const [notice, setNotice] = useState('')
  const [id, version] = templateKey.split('@')
  const template = getOfficialTemplate(id, version)
  if (!template) return <section className="v2-card" role="alert">Версію анкети не знайдено.</section>

  const questions = template.questions
  const partial = isPartialVersion(template.version)
  const fullCount = fullQuestionCount(template.id)
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
      setNotice('Перевірку завершено: усі обов’язкові відповіді заповнено. У цій версії відповіді не надсилаються і не зберігаються на сервері.')
    }
  }

  return <section className="v2-card official-assessment" aria-label={mode === 'expert' ? 'Експертне оцінювання' : 'Офіційна анкета'}>
    <h2>{mode === 'expert' ? 'Експертне оцінювання — демонстраційний перегляд' : 'Офіційна анкета (Додаток В) — демонстраційний перегляд'}</h2>
    <p>Джерело: Додаток В, друковані с. 53–66. У PDF: Анкета 1 — 12 питань, Анкета 2 — 10 питань. {partial ? 'Ця версія охоплює лише піднабір питань.' : 'Ця версія охоплює всі питання відповідної анкети в адаптованому викладі.'}</p>
    <p className="official-demo-note" role="status">У цій версії відповіді не зберігаються на сервері — перегляд призначений для демонстрації структури анкети.</p>
    {mode === 'expert' && <p className="official-demo-note">Окрема роль експерта та сховище експертних оцінок у цій версії не передбачені: адміністратор переглядає структуру експертної анкети.</p>}
    <label htmlFor="official-template">Шаблон і версія</label>
    <select id="official-template" value={templateKey} onChange={event => selectTemplate(event.target.value)}>
      <optgroup label="Повні версії">
        {fullTemplates.map(item => <option key={keyOf(item)} value={keyOf(item)}>{presentableText(item.title)} · v{item.version}</option>)}
      </optgroup>
      <optgroup label="Часткові версії (1.x)">
        {partialTemplates.map(item => <option key={keyOf(item)} value={keyOf(item)}>{presentableText(item.title)} · v{item.version} · часткова версія</option>)}
      </optgroup>
    </select>
    {partial && <p className="official-partial-note" role="note">
      <strong>Часткова версія {template.version}</strong>: {questions.length} з {fullCount ?? '?'} питань анкети. Для повного перегляду оберіть версію 2.1.0.
    </p>}
    <p>{template.audienceNote}</p>
    {template.contentNote && <p>{presentableText(template.contentNote)}</p>}
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
