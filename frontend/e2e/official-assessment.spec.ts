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
  await expect(page.getByRole('heading', { name: /Офіційна анкета · попередній перегляд/ })).toBeVisible()
  await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
  await expect(page.getByRole('alert')).toContainText('Оберіть один варіант')
  await page.locator('.official-option input').first().check()
  await page.getByRole('button', { name: 'Перевірити відповіді' }).click()
  await expect(page.getByText('Локальну перевірку завершено.')).toBeVisible()
  await page.getByLabel('Шаблон і версія').selectOption('appendix-v-form-2@1.0.0')
  await expect(page.getByText(/Заголовок на с. 60/)).toBeVisible()
  await page.goto('/admin/expert')
  await expect(page.getByRole('heading', { name: 'Доступ обмежено' })).toBeVisible()
})

test('verified admin sees expert preview with no submission control', async ({ page }) => {
  await signIn(page, 'e2e-admin@example.test')
  await page.goto('/admin/expert')
  await expect(page.getByRole('heading', { name: /Експертне оцінювання · попередній перегляд/ })).toBeVisible()
  await expect(page.getByText(/Збереження і подання недоступні/)).toBeVisible()
  await expect(page.locator('.official-assessment button[type="submit"]')).toHaveCount(0)
})
