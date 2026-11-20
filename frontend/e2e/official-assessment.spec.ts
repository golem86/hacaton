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

test('self questionnaire validates selections, explains anonymity and keeps expert view restricted', async ({ page }) => {
  await signIn(page, 'e2e-user@example.test')
  await page.goto('/app/official')
  await expect(page.getByRole('heading', { name: 'Офіційна анкета (Додаток В)' })).toBeVisible()
  await expect(page.getByText(/не пов’язується з вашим обліковим записом/)).toBeVisible()
  await expect(page.getByText(/не зберігаються/)).toHaveCount(0)
  await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
  await expect(page.getByRole('alert')).toContainText('Оберіть один варіант')
  await page.locator('#official-form').selectOption('1')
  await expect(page.getByText(/Заголовок на с. 53/)).toBeVisible()
  await expect(page.locator('.official-question-buttons button')).toHaveCount(12)
  await page.locator('#official-form').selectOption('2')
  await expect(page.getByText(/Заголовок с. 60/)).toBeVisible()
  await page.goto('/admin/expert')
  await expect(page.getByRole('heading', { name: 'Доступ обмежено' })).toBeVisible()
})

test('verified admin sees the expert form with a position field and a save action after review', async ({ page }) => {
  await signIn(page, 'e2e-admin@example.test')
  await page.goto('/admin/expert')
  await expect(page.getByRole('heading', { name: 'Експертне оцінювання (Додаток В, анкета 1)' })).toBeVisible()
  await expect(page.getByLabel('Посада або роль експерта')).toBeVisible()
  await expect(page.locator('.official-question-buttons button')).toHaveCount(12)
  await expect(page.locator('.official-section')).toHaveCount(4)
  await expect(page.getByText(/не зберігаються/)).toHaveCount(0)
  for (let i = 0; i < 12; i++) {
    await page.locator('.official-question-buttons button').nth(i).click()
    await page.locator('.official-option input').first().check()
  }
  await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
  await expect(page.getByRole('heading', { name: 'Перегляд заповненої форми' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Зберегти експертну оцінку' })).toBeVisible()
})

test('multi-question form keeps choices across navigation', async ({ page }) => {
  await signIn(page, 'e2e-user@example.test')
  await page.goto('/app/official')
  await expect(page.getByRole('progressbar', { name: 'Прогрес заповнення' })).toHaveAttribute('value', '0')
  await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
  await expect(page.getByRole('status').last()).toContainText("Пропущено обов'язкових відповідей: 10")
  await page.locator('.official-option input').first().check()
  await page.getByRole('button', { name: 'Далі' }).click()
  await expect(page.getByText(/Розділ 1\. Культура/).first()).toBeVisible()
  await page.locator('.official-option input').last().check()
  await page.getByRole('button', { name: 'Назад' }).click()
  await expect(page.locator('.official-option input').first()).toBeChecked()
  await expect(page.getByRole('progressbar', { name: 'Прогрес заповнення' })).toHaveAttribute('value', '2')
})

test('complete catalogs navigate four sections, validate all answers and review before submit', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page, 'e2e-user@example.test')
  await page.goto('/app/official')
  for (const [form, count] of [[1, 12], [2, 10]] as const) {
    await page.locator('#official-form').selectOption(String(form))
    await expect(page.getByText(/Ця версія охоплює всі питання відповідної анкети в адаптованому викладі/)).toBeVisible()
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
    await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
    await expect(page.locator('.official-review-item')).toHaveCount(count)
    await expect(page.getByRole('button', { name: 'Надіслати анкету' })).toBeVisible()
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  expect(overflow).toBe(false)
})
