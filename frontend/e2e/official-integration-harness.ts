// Тільки для E2E: рендерить повні анкети 2.1.0 з продуктового каталогу і надсилає їх
// у синтетичний API прототипу (backend/prototypes/official_e2e_server.py). Не входить у збірку.
import { getOfficialTemplate, officialTemplates } from '../src/official/catalog'

const E2E_VERSION = '2.1.0'
const select = document.querySelector<HTMLSelectElement>('#template')!
const form = document.querySelector<HTMLFormElement>('#questionnaire')!
const note = document.querySelector<HTMLParagraphElement>('#template-note')!
const result = document.querySelector<HTMLParagraphElement>('#result')!
const submit = document.querySelector<HTMLButtonElement>('#submit')!

for (const template of officialTemplates.filter(item => item.version === E2E_VERSION)) {
  const option = document.createElement('option')
  option.value = `${template.id}@${template.version}`
  option.textContent = `${template.title} · v${template.version}`
  select.append(option)
}
select.value = `appendix-v-form-1@${E2E_VERSION}`

function renderForm() {
  const [templateId, version] = select.value.split('@')
  const template = getOfficialTemplate(templateId, version)
  form.replaceChildren()
  result.textContent = ''
  delete result.dataset.status
  if (!template) return
  note.textContent = `${template.questions.length} питань. Синтетична категорія задається лише тестовим циклом; Анкета 2 не маршрутизується в продукті.`
  for (const [index, question] of template.questions.entries()) {
    const fieldset = document.createElement('fieldset')
    const legend = document.createElement('legend')
    legend.textContent = `${index + 1}. ${question.text} (обов’язково)`
    fieldset.append(legend)
    for (const option of question.options) {
      const label = document.createElement('label')
      const input = document.createElement('input')
      input.type = 'radio'
      input.name = question.id
      input.value = option.id
      input.required = true
      label.append(input, document.createTextNode(option.text))
      fieldset.append(label)
    }
    form.append(fieldset)
  }
}

select.addEventListener('change', renderForm)
submit.addEventListener('click', async () => {
  const [templateId, version] = select.value.split('@')
  const template = getOfficialTemplate(templateId, version)
  if (!template || !form.reportValidity()) {
    result.textContent = 'Заповніть усі обов’язкові відповіді.'
    return
  }
  const values = new FormData(form)
  const answers = template.questions.map(question => ({
    question_id: question.id,
    option_id: String(values.get(question.id) ?? ''),
  }))
  const formNumber = template.id.endsWith('1') ? 1 : 2
  const cycleId = formNumber
  const category = formNumber === 1 ? 'synthetic-working-group' : 'synthetic-ambiguous-review'
  const code = formNumber === 1 ? 'e2e-only-form1-2.1' : 'e2e-only-form2-2.1'
  submit.disabled = true
  result.textContent = 'Зберігаємо тільки в синтетичній тестовій SQLite…'
  try {
    const response = await fetch(`/prototype-test-api/cycles/${cycleId}/official-submissions`, {
      method: 'POST',
      credentials: 'omit',
      cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template_id: template.id, version: template.version, category, code, answers }),
    })
    result.textContent = response.status === 201
      ? 'Подання підтверджено тестовим API.'
      : 'Тестовий API відхилив подання.'
    result.dataset.status = String(response.status)
  } catch {
    result.textContent = 'Тестове API недоступне.'
    result.dataset.status = 'network-error'
  } finally {
    submit.disabled = false
  }
})

renderForm()
