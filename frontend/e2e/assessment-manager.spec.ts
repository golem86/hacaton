import { expect, test, type Page } from '@playwright/test'

const api = process.env.V2_E2E_API_URL || 'http://127.0.0.1:8018'
const adminEmail = process.env.V2_E2E_ADMIN_EMAIL || 'e2e-admin@example.test'
const officerEmail = process.env.V2_E2E_OFFICER_EMAIL || 'e2e-officer@example.test'
const password = process.env.V2_E2E_TEST_PASSWORD || 'E2E-Only-Local-Synthetic-2026!'

async function signIn(page: Page, email: string, home: RegExp) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Пароль').fill(password)
  await page.getByRole('button', { name: 'Увійти' }).click()
  await expect(page.getByRole('heading', { name: 'Підтвердження входу' })).toBeVisible()
  const mail = await page.request.get(`${api}/v2/auth/dev-mail/latest`)
  expect(mail.status()).toBe(200)
  const body = (await mail.json() as { body: string }).body
  const code = body.match(/\b\d{6}\b/)?.[0]
  expect(code).toBeTruthy()
  await page.getByLabel('Код підтвердження').fill(code!)
  await page.getByRole('button', { name: 'Підтвердити' }).click()
  await expect(page).toHaveURL(home)
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Вийти', exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
}

// Рішення власника: адміністратор має права data_officer — бачить форму видачі кодів; тут коди видає відповідальний.
test('адміністратор створює цикл, відповідальний видає код, респондент подає анонімну анкету', async ({ page, playwright }) => {
  await signIn(page, adminEmail, /\/admin/)
  await page.getByRole('button', { name: 'Цикли оцінювання' }).click()
  const uniqueName = `Синтетичний E2E ${Date.now()}`
  await page.getByLabel('Назва').fill(uniqueName)
  await page.getByLabel('Початок').fill(new Date().toISOString().slice(0, 10))
  await page.getByLabel('Мінімальний розмір групи').fill('5')
  await page.getByRole('button', { name: 'Створити чернетку' }).click()
  await expect(page.getByText('Статус: Чернетка')).toBeVisible()
  await page.getByRole('button', { name: 'Активувати' }).click()
  await expect(page.getByText('Статус: Відкритий')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Видати коди' })).toBeVisible()
  await expect(page.getByText('Кожна видача фіксується в журналі дій')).toBeVisible()
  await signOut(page)

  await signIn(page, officerEmail, /\/officer/)
  await page.getByRole('button', { name: new RegExp(uniqueName) }).click()
  await page.getByLabel('Категорія кодів').selectOption('cadets')
  await page.getByLabel('Кількість кодів').fill('1')
  await page.getByLabel('Строк дії, днів').fill('14')
  await page.getByRole('button', { name: 'Видати коди' }).click()
  await expect(page.getByText('Коди показано лише один раз')).toBeVisible()
  const token = await page.locator('textarea[readonly]').inputValue()
  expect(token).toMatch(/^[0-9a-f]{32}$/)
  await page.getByRole('button', { name: 'Сховати коди' }).click()
  await page.getByRole('button', { name: 'Так, сховати' }).click()

  await page.goto('/survey')
  await page.getByRole('combobox', { name: 'Відкритий цикл' }).selectOption({ label: uniqueName })
  await page.getByLabel('Категорія респондента').selectOption('cadets')
  await page.getByLabel('Підрозділ').selectOption({ index: 1 })
  await page.getByLabel('Одноразовий код доступу').fill(token)
  const questions = page.locator('.survey-api-question')
  await expect(questions).toHaveCount(14)
  for (const question of await questions.all()) await question.locator('input[type="radio"][value="3"]').check()
  // Сесія data_officer у браузері ще активна: подання все одно має йти без cookies та Authorization.
  expect((await page.context().cookies()).length).toBeGreaterThan(0)
  const submitted = page.waitForRequest(request => request.method() === 'POST' && /\/api\/assessments\/\d+\/submissions$/.test(request.url()))
  await page.getByRole('button', { name: 'Надіслати анкету' }).click()
  const submission = await submitted
  const headers = await submission.allHeaders()
  expect(headers.cookie).toBeUndefined()
  expect(headers.authorization).toBeUndefined()
  expect(headers['x-csrf-token']).toBeUndefined()
  const payload = submission.postDataJSON() as { questionnaire_version?: string, token?: string }
  expect(payload.questionnaire_version).toBe('demo-v1')
  expect(payload.token).toBe(token)
  expect((await submission.response())?.status()).toBe(201)
  await expect(page.getByText('Анкету прийнято. Повторне надсилання заблоковано.')).toBeVisible()

  // Повторне подання тим самим кодом (окремий контекст без cookies) — 403.
  const anonymous = await playwright.request.newContext()
  try {
    const replay = await anonymous.post(submission.url(), { data: payload })
    expect(replay.status()).toBe(403)
  } finally {
    await anonymous.dispose()
  }

  await page.goto('/officer/participation')
  await page.getByRole('combobox', { name: 'Цикл' }).selectOption({ label: `${uniqueName} · Відкритий` })
  await expect(page.getByText('анкет: приховано')).toBeVisible()
  await expect(page.getByText('невикористаних: приховано')).toBeVisible()
  await signOut(page)

  await signIn(page, adminEmail, /\/admin/)
  await page.goto('/admin/testing')
  await page.getByRole('combobox', { name: 'Цикл' }).selectOption({ label: `${uniqueName} · Відкритий` })
  await page.getByRole('button', { name: 'Закрити цикл' }).click()
  await expect(page.getByText('Статус: Закритий')).toBeVisible()
  // Після закриття мала група (1 анкета < k=5) залишається прихованою.
  await expect(page.getByText('анкет: приховано')).toBeVisible()
  await expect(page.getByText('невикористаних: приховано')).toBeVisible()
})
