import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-official-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { officialTemplates, getOfficialTemplate } = await server.ssrLoadModule('/src/official/catalog.ts')
const { validateOfficialAnswers } = await server.ssrLoadModule('/src/official/validation.ts')
const officialModule = await server.ssrLoadModule('/src/official/OfficialAssessment.tsx')
const OfficialAssessment = officialModule.default

test('versioned official catalog has unique question and option IDs, source and descriptive choices', () => {
  assert.equal(officialTemplates.length, 8)
  for (const template of officialTemplates) {
    const ids = new Set()
    assert.ok(Object.isFrozen(template) && Object.isFrozen(template.questions))
    assert.equal(getOfficialTemplate(template.id, template.version), template)
    for (const question of template.questions) {
      assert.ok(Object.isFrozen(question) && Object.isFrozen(question.options))
      assert.equal(question.kind, 'single_choice')
      assert.equal(question.required, true)
      assert.equal(question.options.length, question.source.section.startsWith('Розділ 3.') && question.source.number === 3 ? 6 : 5)
      assert.equal(question.source.appendix, 'В')
      assert.match(question.source.section, /^Розділ [1-4]\. /)
      assert.ok(!ids.has(question.id))
      ids.add(question.id)
      for (const option of question.options) { assert.ok(!ids.has(option.id)); ids.add(option.id); assert.ok(option.text.length > 20) }
    }
  }
  assert.deepEqual(officialTemplates.map(t => t.questions[0].source.page), [53, 60, 53, 60, 53, 60, 53, 60])
  assert.equal(officialTemplates[1].audience, 'ambiguous')
  assert.equal(officialTemplates[3].audience, 'ambiguous')
  assert.deepEqual(officialTemplates.map(t => t.version), ['1.0.0', '1.0.0', '1.1.0', '1.1.0', '2.0.0', '2.0.0', '2.1.0', '2.1.0'])
  assert.deepEqual(officialTemplates.map(t => t.questions.length), [1, 1, 2, 2, 12, 10, 12, 10])
  assert.deepEqual(officialTemplates.slice(2, 4).map(t => t.questions[1].source.page), [56, 62])
  assert.ok(officialTemplates.slice(2, 6).every(t => t.sourceUrl?.endsWith('.pdf') && t.contentNote?.includes('адаптовано')))
  assert.ok(officialTemplates.slice(6).every(t => t.sourceUrl?.endsWith('.pdf') && t.contentNote?.includes('2.1.0')))
  assert.deepEqual(officialTemplates[0].questions, officialTemplates[2].questions.slice(0, 1))
  assert.deepEqual(officialTemplates[1].questions, officialTemplates[3].questions.slice(0, 1))
  assert.equal(getOfficialTemplate('appendix-v-form-1', '9.9.9'), undefined)
})

test('required answers accept only an option from their own question', () => {
  const template = officialTemplates[0]
  const question = template.questions[0]
  assert.ok(validateOfficialAnswers(template, {})[question.id])
  assert.ok(validateOfficialAnswers(template, { [question.id]: officialTemplates[1].questions[0].options[0].id })[question.id])
  assert.deepEqual(validateOfficialAnswers(template, { [question.id]: question.options[0].id }), {})
})

test('multi-question validation reports every missing or foreign selection', () => {
  const template = officialTemplates[2]
  const [first, second] = template.questions
  assert.deepEqual(Object.keys(validateOfficialAnswers(template, {})), [first.id, second.id])
  assert.ok(validateOfficialAnswers(template, { [first.id]: first.options[0].id, [second.id]: first.options[0].id })[second.id])
  assert.deepEqual(validateOfficialAnswers(template, { [first.id]: first.options[0].id, [second.id]: second.options[4].id }), {})
})

test('complete catalogs match the source order, metadata, sections and choice counts', () => {
  const expected = [
    [[1, 1, 53], [1, 2, 53], [1, 3, 54], [1, 4, 54], [1, 5, 55], [2, 1, 55], [2, 2, 56], [3, 1, 56], [3, 2, 57], [3, 3, 57], [3, 4, 58], [4, 1, 58]],
    [[1, 1, 60], [1, 2, 60], [1, 3, 61], [2, 1, 61], [2, 2, 62], [3, 1, 62], [3, 2, 63], [3, 3, 63], [3, 4, 64], [4, 1, 64]],
  ]
  for (const [formIndex, template] of officialTemplates.slice(4, 6).entries()) {
    assert.deepEqual(template.questions.map(q => [Number(q.source.section[7]), q.source.number, q.source.page]), expected[formIndex])
    assert.deepEqual([...new Set(template.questions.map(q => q.source.section[7]))], ['1', '2', '3', '4'])
    for (const q of template.questions) {
      assert.equal(q.source.form, formIndex + 1)
      assert.equal(q.wording, 'adapted')
      assert.equal(q.kind, 'single_choice')
      assert.ok(!('score' in q) && !('weight' in q))
      assert.ok(q.options.every(o => !('score' in o) && !('weight' in o)))
      assert.equal(q.options.length, q.source.section.startsWith('Розділ 3.') && q.source.number === 3 ? 6 : 5)
    }
  }
  assert.equal(officialTemplates[5].audience, 'ambiguous')
})

test('complete forms require every answer and reject foreign selections', () => {
  for (const template of officialTemplates.slice(4)) {
    assert.equal(Object.keys(validateOfficialAnswers(template, {})).length, template.questions.length)
    const answers = Object.fromEntries(template.questions.map(q => [q.id, q.options[0].id]))
    assert.deepEqual(validateOfficialAnswers(template, answers), {})
    answers[template.questions.at(-1).id] = template.questions[0].options[0].id
    assert.ok(validateOfficialAnswers(template, answers)[template.questions.at(-1).id])
  }
})

test('2.1.0 restores source notes without mutating 2.0.0', () => {
  const f1v2 = getOfficialTemplate('appendix-v-form-1', '2.0.0')
  const f1v21 = getOfficialTemplate('appendix-v-form-1', '2.1.0')
  const f2v2 = getOfficialTemplate('appendix-v-form-2', '2.0.0')
  const f2v21 = getOfficialTemplate('appendix-v-form-2', '2.1.0')
  assert.ok(f1v2 && f1v21 && f2v2 && f2v21)
  assert.equal(f1v2.questions[3].source_duplicate, undefined)
  assert.equal(f1v21.questions[3].source_duplicate, true)
  assert.equal(f1v21.questions[4].source_duplicate, true)
  assert.match(f1v21.questions.find(q => q.id === 'av-f1-accountability-3').options[0].text, /^0% — /)
  assert.doesNotMatch(f1v2.questions.find(q => q.id === 'av-f1-accountability-3').options[0].text, /^0%/)
  for (const template of [f1v21, f2v21]) {
    const maturity = template.questions.at(-1)
    assert.equal(maturity.options.length, 5)
    assert.ok(maturity.options.every(option => option.text.length > 200))
    assert.ok(maturity.options.every(option => !('score' in option) && !('weight' in option)))
  }
  assert.equal(f2v21.audience, 'ambiguous')
})

test('self and expert render distinct submission modes with honest adapted-wording labels', () => {
  const cycles = [{ id: 1, name: 'Цикл', start_date: '2026-01-01', status: 'open', min_group_size: 5 }]
  const self = renderToStaticMarkup(React.createElement(OfficialAssessment, { mode: 'self', cycles }))
  const expert = renderToStaticMarkup(React.createElement(OfficialAssessment, { mode: 'expert', cycles }))
  for (const html of [self, expert]) {
    assert.ok(html.includes('type="radio"'))
    assert.ok(html.includes('Перевірити відповіді'))
    assert.ok(html.includes('Прогрес заповнення'))
    assert.ok(html.includes('адаптоване формулювання'))
    assert.ok(html.includes('адаптованому викладі'))
    assert.doesNotMatch(html, /не зберігаються|демонстраційний перегляд/)
  }
  assert.ok(expert.includes('Експертне оцінювання'))
  assert.ok(expert.includes('Посада або роль експерта'))
  assert.ok(expert.includes('с. 53'))
  assert.ok(self.includes('Офіційна анкета'))
  assert.ok(self.includes('Одноразовий код доступу'))
  assert.ok(self.includes('с. 60'), 'self defaults to form 2 for personnel')
})



