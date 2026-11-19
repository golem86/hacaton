import { useState } from 'react'
import { getOfficialTemplate, officialTemplates } from './catalog'
import { validateOfficialAnswers, type OfficialAnswers } from './validation'

type Mode = 'self' | 'expert'

export default function OfficialAssessment({ mode }: { mode: Mode }) {
  const [templateKey, setTemplateKey] = useState(`${officialTemplates[0].id}@${officialTemplates[0].version}`)
  const [answers, setAnswers] = useState<OfficialAnswers>({})
  const [index, setIndex] = useState(0)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState('')
  const [id, version] = templateKey.split('@')
  const template = getOfficialTemplate(id, version)
  if (!template) return <section className="v2-card" role="alert">Версію анкети не знайдено.</section>
  const question = template.questions[index]
  const selectTemplate = (key: string) => { setTemplateKey(key); setAnswers({}); setErrors({}); setIndex(0); setNotice('') }
  const next = () => {
    const nextErrors = validateOfficialAnswers(template, answers)
    if (nextErrors[question.id]) { setErrors({ [question.id]: nextErrors[question.id] }); setNotice(''); return }
    setErrors({})
    if (index < template.questions.length - 1) setIndex(index + 1)
    else setNotice('Локальну перевірку завершено. Збереження відповідей очікує погодженого API та схеми даних.')
  }
  return <section className="v2-card official-assessment" aria-label={mode === 'expert' ? 'Експертне оцінювання' : 'Офіційна анкета'}>
    <h2>{mode === 'expert' ? 'Експертне оцінювання · попередній перегляд' : 'Офіційна анкета · попередній перегляд'}</h2>
    <p>Джерело: Додаток В, сторінки 53–66. Перенесено перевірений піднабір: одне питання з кожної форми.</p>
    <p role="status">Відповіді залишаються лише в цій вкладці. Збереження і подання недоступні до погодження спільного контракту.</p>
    {mode === 'expert' && <p>Режим експерта доступний лише в адміністративній панелі після серверної перевірки сесії. Окрема роль експерта та збереження експертних оцінок ще не реалізовані.</p>}
    <label htmlFor="official-template">Шаблон і версія</label>
    <select id="official-template" value={templateKey} onChange={event => selectTemplate(event.target.value)}>
      {officialTemplates.map(item => <option key={`${item.id}@${item.version}`} value={`${item.id}@${item.version}`}>{item.title} · v{item.version}</option>)}
    </select>
    <p>{template.audienceNote}</p>
    <p>Питання {index + 1} з {template.questions.length} · {question.source.section} · Додаток {question.source.appendix}, с. {question.source.page}, № {question.source.number}</p>
    <fieldset aria-describedby={errors[question.id] ? 'official-question-error' : undefined}>
      <legend>{question.text}</legend>
      {question.options.map(option => <label key={option.id} className="official-option"><input type="radio" name={question.id} value={option.id} checked={answers[question.id] === option.id} onChange={() => { setAnswers(previous => ({ ...previous, [question.id]: option.id })); setErrors({}); setNotice('') }} />{option.text}</label>)}
    </fieldset>
    {errors[question.id] && <p id="official-question-error" role="alert">{errors[question.id]}</p>}
    <div className="official-actions"><button type="button" className="v2-button" disabled={index === 0} onClick={() => { setIndex(index - 1); setErrors({}); setNotice('') }}>Назад</button><button type="button" className="v2-button v2-button-primary" onClick={next}>{index < template.questions.length - 1 ? 'Далі' : 'Перевірити відповіді'}</button></div>
    {notice && <p role="status">{notice}</p>}
  </section>
}
