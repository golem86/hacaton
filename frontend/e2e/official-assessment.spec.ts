import { expect, test, type Page } from '@playwright/test'

const api = process.env.V2_E2E_API_URL || 'http://127.0.0.1:8018'
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
  await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
  await expect(page.getByRole('alert')).toContainText('Оберіть один варіант')
  await page.locator('.official-option input').first().check()
  await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
  await expect(page.getByRole('heading', { name: 'Перегляд заповненої форми' })).toBeVisible()
  await page.getByLabel('Шаблон і версія').selectOption('appendix-v-form-2@1.0.0')
  await expect(page.getByText(/Заголовок на с. 60/)).toBeVisible()
  await page.goto('/admin/expert')
  await expect(page.getByRole('heading', { name: 'Доступ обмежено' })).toBeVisible()
})

test('verified admin sees expert preview with no submission control', async ({ page }) => {
  await signIn(page, 'e2e-admin@example.test')
  await page.goto('/admin/expert')
  await expect(page.getByRole('heading', { name: /Експертне оцінювання — демонстраційний перегляд/ })).toBeVisible()
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
