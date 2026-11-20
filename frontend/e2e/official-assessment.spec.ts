import { expect, test, type Page } from '@playwright/test'

const api = process.env.V2_E2E_API_URL || 'http://127.0.0.1:8018'
const questionnaireAPI = process.env.V2_E2E_QUESTIONNAIRE_API_URL || 'http://127.0.0.1:8020'
const password = process.env.V2_E2E_TEST_PASSWORD || 'E2E-Only-Local-Synthetic-2026!'

async function signIn(page: Page, email: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Пароль').fill(password)
  await page.getByRole('button', { name: 'Увійти' }).click()
  await expect(page.getByRole('heading', { name: 'Підтвердження входу' })).toBeVisible()
  const mail = await page.request.get(`${api}/v2/auth/dev-mail/latest`)
  expect(mail.status()).toBe(200)
  const body = (await mail.json() as { body: string }).body
  const code = body?.match(/\b\d{6}\b/)?.[0]
  expect(code).toBeTruthy()
  await page.getByLabel('Код підтвердження').fill(code!)
  await page.getByRole('button', { name: 'Підтвердити' }).click()
  await expect(page).toHaveURL(email.includes('admin') ? /\/admin/ : /\/app/)
}

test('self preview validates selections and keeps expert view restricted', async ({ page }) => {
  await signIn(page, 'e2e-user@example.test')
  await page.goto('/app/official')
  await expect(page.getByRole('heading', { name: /Офіційна анкета \(Додаток В\) — демонстраційний перегляд/ })).toBeVisible()
  // За замовчуванням — повна 2.1.0 (12 питань), без позначки часткової версії.
  await expect(page.getByLabel('Шаблон і версія')).toHaveValue('appendix-v-form-1@2.1.0')
  await expect(page.locator('.official-question-buttons button')).toHaveCount(12)
  await expect(page.locator('.official-partial-note')).toHaveCount(0)
  await page.getByLabel('Шаблон і версія').selectOption('appendix-v-form-1@1.0.0')
  await expect(page.locator('.official-partial-note')).toContainText('Часткова версія 1.0.0: 1 з 12 питань')
  await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
  await expect(page.getByRole('alert')).toContainText('Оберіть один варіант')
  await page.locator('.official-option input').first().check()
  await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
  await expect(page.getByRole('heading', { name: 'Перегляд заповненої форми' })).toBeVisible()
  await page.getByLabel('Шаблон і версія').selectOption('appendix-v-form-2@1.0.0')
  await expect(page.getByText(/Заголовок на с. 60/)).toBeVisible()
  await expect(page.locator('.official-partial-note')).toContainText('Часткова версія 1.0.0: 1 з 10 питань')
  await page.goto('/admin/expert')
  await expect(page.getByRole('heading', { name: 'Доступ обмежено' })).toBeVisible()
})

test('verified admin sees expert preview with no submission control', async ({ page }) => {
  await signIn(page, 'e2e-admin@example.test')
  await page.goto('/admin/expert')
  await expect(page.getByRole('heading', { name: /Експертне оцінювання — демонстраційний перегляд/ })).toBeVisible()
  await expect(page.getByLabel('Шаблон і версія')).toHaveValue('appendix-v-form-1@2.1.0')
  await expect(page.locator('.official-question-buttons button')).toHaveCount(12)
  await page.getByLabel('Шаблон і версія').selectOption('appendix-v-form-2@2.0.0')
  await expect(page.locator('.official-question-buttons button')).toHaveCount(10)
  await expect(page.locator('.official-section')).toHaveCount(4)
  await expect(page.getByText(/Категорію має визначити №5/)).toBeVisible()
  await expect(page.getByText(/відповіді не зберігаються на сервері/)).toBeVisible()
  await expect(page.locator('.official-assessment button[type="submit"]')).toHaveCount(0)
})

test('multi-question preview keeps choices across navigation and never submits', async ({ page }) => {
  await signIn(page, 'e2e-user@example.test')
  await page.goto('/app/official')
  await page.getByLabel('Шаблон і версія').selectOption('appendix-v-form-1@1.1.0')
  await expect(page.getByRole('progressbar', { name: 'Прогрес заповнення' })).toHaveAttribute('value', '0')
  await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
  await expect(page.getByRole('status').last()).toContainText("Пропущено обов'язкових відповідей: 2")
  await page.locator('.official-option input').first().check()
  await page.getByRole('button', { name: 'Далі' }).click()
  await expect(page.getByText(/Розділ 2\. Система/).first()).toBeVisible()
  await page.locator('.official-option input').last().check()
  await page.getByRole('button', { name: 'Назад' }).click()
  await expect(page.locator('.official-option input').first()).toBeChecked()
  await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
  await expect(page.getByRole('heading', { name: 'Перегляд заповненої форми' })).toBeVisible()
  await expect(page.locator('.official-assessment button[type="submit"]')).toHaveCount(0)
  await page.getByLabel('Шаблон і версія').selectOption('appendix-v-form-2@1.1.0')
  await expect(page.getByRole('progressbar', { name: 'Прогрес заповнення' })).toHaveAttribute('value', '0')
  await expect(page.getByText(/Заголовок на с. 60/)).toBeVisible()
})

test('complete catalogs navigate four sections, validate all answers and review locally', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page, 'e2e-user@example.test')
  await page.goto('/app/official')
  for (const [form, count] of [[1, 12], [2, 10]] as const) {
    await page.getByLabel('Шаблон і версія').selectOption(`appendix-v-form-${form}@2.0.0`)
    await expect(page.getByText('Ця версія охоплює всі питання відповідної анкети в адаптованому викладі.')).toBeVisible()
    await expect(page.locator('.official-section')).toHaveCount(4)
    await expect(page.locator('.official-question-buttons button')).toHaveCount(count)
    await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
    await expect(page.getByRole('status').last()).toContainText(`Пропущено обов'язкових відповідей: ${count}`)
    for (let i = 0; i < count; i++) {
      await page.locator('.official-question-buttons button').nth(i).click()
      const first = page.locator('.official-option input').first()
      if (i === 0) { await first.focus(); await page.keyboard.press('Space') }
      else await first.check()
    }
    await expect(page.getByRole('progressbar', { name: 'Прогрес заповнення' })).toHaveAttribute('value', String(count))
    await page.locator('.official-question-buttons button').first().click()
    await expect(page.locator('.official-option input').first()).toBeChecked()
    await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
    await expect(page.locator('.official-review-item')).toHaveCount(count)
    await expect(page.locator('.official-assessment button[type="submit"]')).toHaveCount(0)
  }
  await page.getByLabel('Шаблон і версія').selectOption('appendix-v-form-1@2.1.0')
  await page.locator('.official-question-buttons button').nth(3).click()
  await expect(page.getByText(/дублікат у джерелі/)).toBeVisible()
  await page.locator('.official-question-buttons button').nth(9).click()
  await expect(page.locator('.official-option').first()).toContainText(/^0% —/)
  await page.locator('.official-question-buttons button').last().click()
  await expect(page.locator('.official-option')).toHaveCount(5)
  await expect(page.locator('.official-option').last()).toContainText(/зовнішній аудит усієї системи/)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  expect(overflow).toBe(false)
})

// Прототип офіційного подання: обидві повні форми 2.1.0 зберігаються в синтетичній schema-5 SQLite
// (коди — лише SHA-256 у access_tokens.token_hash), без cookies/Authorization у запиті подання.
test('synthetic browser submission persists both 2.1.0 forms without session credentials', async ({ page }) => {
  await signIn(page, 'e2e-user@example.test')
  const observedHeaders: Record<string, string>[] = []
  page.on('request', request => {
    if (request.url().includes('/prototype-test-api/cycles/')) observedHeaders.push(request.headers())
  })
  await page.goto('/e2e/official-integration-harness.html')
  await expect(page.getByRole('heading', { name: /Тільки тест/ })).toBeVisible()

  for (const [form, answerCount] of [[1, 12], [2, 10]] as const) {
    await page.locator('#template').selectOption(`appendix-v-form-${form}@2.1.0`)
    const groups = page.locator('#questionnaire fieldset')
    await expect(groups).toHaveCount(answerCount)
    for (let i = 0; i < answerCount; i++) await groups.nth(i).locator('input').first().check()
    await page.getByRole('button', { name: 'Надіслати синтетичне подання' }).click()
    const result = page.locator('#result')
    await expect(result).toHaveAttribute('data-status', '201')
    await expect(result).toContainText('підтверджено тестовим API')

    const persisted = await page.request.get(`${questionnaireAPI}/_e2e/verify/${form}`)
    expect(persisted.status()).toBe(200)
    expect(await persisted.json()).toEqual({
      schema_version: 5,
      binding: [`appendix-v-form-${form}`, '2.1.0'],
      response: [`appendix-v-form-${form}`, '2.1.0', form === 1 ? 'synthetic-working-group' : 'synthetic-ambiguous-review'],
      response_sets: 1,
      official_answers: answerCount,
      code_used: true,
      plaintext_codes_stored: 0,
      numeric_answers: 1,
      respondent_link_columns: [],
    })
    const sent = observedHeaders.at(-1) ?? {}
    expect(Object.keys(sent).some(name => ['cookie', 'authorization'].includes(name.toLowerCase()))).toBe(false)
    if (form === 1) {
      await page.getByRole('button', { name: 'Надіслати синтетичне подання' }).click()
      await expect(result).toHaveAttribute('data-status', '403')
      const replayState = await (await page.request.get(`${questionnaireAPI}/_e2e/verify/${form}`)).json()
      expect(replayState.response_sets).toBe(1)
      expect(replayState.official_answers).toBe(answerCount)
    }
  }
})
