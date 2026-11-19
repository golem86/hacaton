import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-official-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { officialTemplates, getOfficialTemplate } = await server.ssrLoadModule('/src/official/catalog.ts')
const { validateOfficialAnswers } = await server.ssrLoadModule('/src/official/validation.ts')
const OfficialAssessment = (await server.ssrLoadModule('/src/official/OfficialAssessment.tsx')).default

test('versioned official catalog has unique question and option IDs, source and descriptive choices', () => {
  assert.equal(officialTemplates.length, 2)
  const ids = new Set()
  for (const template of officialTemplates) {
    assert.equal(getOfficialTemplate(template.id, template.version), template)
    for (const question of template.questions) {
      assert.equal(question.kind, 'single_choice')
      assert.equal(question.required, true)
      assert.equal(question.options.length, 5)
      assert.equal(question.source.appendix, 'В')
      assert.equal(question.source.section, 'Розділ 1. Культура.')
      assert.ok(!ids.has(question.id))
      ids.add(question.id)
      for (const option of question.options) { assert.ok(!ids.has(option.id)); ids.add(option.id); assert.ok(option.text.length > 20) }
    }
  }
  assert.deepEqual(officialTemplates.map(t => t.questions[0].source.page), [53, 60])
  assert.equal(officialTemplates[1].audience, 'ambiguous')
  assert.equal(getOfficialTemplate('appendix-v-form-1', '9.9.9'), undefined)
})

test('required answers accept only an option from their own question', () => {
  const template = officialTemplates[0]
  const question = template.questions[0]
  assert.ok(validateOfficialAnswers(template, {})[question.id])
  assert.ok(validateOfficialAnswers(template, { [question.id]: officialTemplates[1].questions[0].options[0].id })[question.id])
  assert.deepEqual(validateOfficialAnswers(template, { [question.id]: question.options[0].id }), {})
})

test('self and expert render distinct preview modes without a submit action', () => {
  const self = renderToStaticMarkup(React.createElement(OfficialAssessment, { mode: 'self' }))
  const expert = renderToStaticMarkup(React.createElement(OfficialAssessment, { mode: 'expert' }))
  for (const html of [self, expert]) {
    assert.ok(html.includes('Шаблон і версія'))
    assert.ok(html.includes('type="radio"'))
    assert.ok(html.includes('с. 53'))
    assert.ok(html.includes('Перевірити відповіді'))
    assert.ok(html.includes('Збереження і подання недоступні'))
    assert.ok(!html.includes('type="submit"'))
  }
  assert.ok(expert.includes('Експертне оцінювання'))
  assert.ok(self.includes('Офіційна анкета'))
})
