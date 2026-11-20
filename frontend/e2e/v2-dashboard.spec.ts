import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const apiBaseURL = process.env.V2_E2E_API_URL || 'http://127.0.0.1:8018'
const adminEmail = process.env.V2_E2E_ADMIN_EMAIL || 'e2e-admin@example.test'
const userEmail = process.env.V2_E2E_USER_EMAIL || 'e2e-user@example.test'
const password = process.env.V2_E2E_TEST_PASSWORD || 'E2E-Only-Local-Synthetic-2026!'

async function latestOtp(request: APIRequestContext): Promise<string> {
  const response = await request.get(`${apiBaseURL}/v2/auth/dev-mail/latest`)
  if (response.status() !== 200) throw new Error('Локальна тестова пошта недоступна.')
  const mail = await response.json() as { body?: string }
  const code = mail.body?.match(/\b\d{6}\b/)?.[0]
  if (!code) throw new Error('У локальній тестовій пошті немає коду підтвердження.')
  return code
}

async function loginInBrowser(page: Page, email: string) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Пароль').fill(password)
  await page.getByRole('button', { name: 'Увійти' }).click()
  await expect(page.getByRole('heading', { name: 'Підтвердження входу' })).toBeVisible()

  const code = await latestOtp(page.request)
  await page.getByLabel('Код підтвердження').fill(code)
  await page.getByRole('button', { name: 'Підтвердити' }).click()
  await expect(page).toHaveURL(/\/(admin|app)(\/|$)/)
}

async function loginThroughTwoFactor(request: APIRequestContext, email: string) {
  const csrfResponse = await request.get(`${apiBaseURL}/v2/auth/csrf`)
  expect(csrfResponse.status()).toBe(200)
  const preauth = await csrfResponse.json() as { csrf_token: string }

  const login = await request.post(`${apiBaseURL}/v2/auth/login`, {
    data: { email, password },
    headers: { 'X-CSRF-Token': preauth.csrf_token },
  })
  expect(login.status()).toBe(200)
  const pending = await login.json() as { csrf_token: string }

  const code = await latestOtp(request)
  const verify = await request.post(`${apiBaseURL}/v2/auth/2fa/verify`, {
    data: { code },
    headers: { 'X-CSRF-Token': pending.csrf_token },
  })
  expect(verify.status()).toBe(200)
}

test('сторінка входу показує базову форму автентифікації', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: 'Вхід до системи' })).toBeVisible()
  await expect(page.getByLabel('Email')).toBeVisible()
  await expect(page.getByLabel('Пароль')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Увійти' })).toBeEnabled()
})

test('повний вхід з 2FA відкриває Dashboard, а вихід завершує сесію', async ({ page }) => {
  await loginInBrowser(page, adminEmail)
  await expect(page.getByRole('button', { name: 'Вийти', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Вийти', exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  expect((await page.request.get(`${apiBaseURL}/v2/auth/me`)).status()).toBe(401)
})

test('неавторизований користувач не відкриває admin сторінку або Swagger', async ({ page, playwright }) => {
  await page.goto('/admin')
  await expect(page.getByRole('heading', { name: 'Вхід до системи' })).toBeVisible()

  const anonymous = await playwright.request.newContext({ baseURL: apiBaseURL })
  try {
    expect((await anonymous.get('/docs')).status()).toBe(401)
    expect((await anonymous.get('/openapi.json')).status()).toBe(401)
  } finally {
    await anonymous.dispose()
  }
})

test('Swagger та OpenAPI доступні лише після серверної ролі admin і 2FA', async ({ playwright }) => {
  const user = await playwright.request.newContext({ baseURL: apiBaseURL })
  const admin = await playwright.request.newContext({ baseURL: apiBaseURL })
  try {
    const userCsrfResponse = await user.get('/v2/auth/csrf')
    const userCsrf = await userCsrfResponse.json() as { csrf_token: string }
    const userLogin = await user.post('/v2/auth/login', {
      data: { email: userEmail, password },
      headers: { 'X-CSRF-Token': userCsrf.csrf_token },
    })
    expect(userLogin.status()).toBe(200)
    expect((await user.get('/docs')).status()).toBe(401)
    const userPending = await userLogin.json() as { csrf_token: string }
    const userCode = await latestOtp(user)
    expect((await user.post('/v2/auth/2fa/verify', {
      data: { code: userCode },
      headers: { 'X-CSRF-Token': userPending.csrf_token },
    })).status()).toBe(200)
    expect((await user.get('/docs')).status()).toBe(403)
    expect((await user.get('/openapi.json')).status()).toBe(403)

    await loginThroughTwoFactor(admin, adminEmail)
    const docs = await admin.get('/docs')
    expect(docs.status()).toBe(200)
    expect(docs.headers()['content-type']).toContain('text/html')
    expect((await admin.get('/openapi.json')).status()).toBe(200)
  } finally {
    await user.dispose()
    await admin.dispose()
  }
})

test('Dashboard показує синтетичні KPI, C1–C7 та приховує малу групу', async ({ page }) => {
  await loginInBrowser(page, adminEmail)
  await page.goto('/admin')
  await expect(page.getByText('Відповідей у циклі')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Оперативний огляд' })).toBeVisible()

  await page.goto('/admin/analytics')
  await expect(page.getByRole('heading', { name: 'Бали компонентів' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'За категоріями респондентів' })).toBeVisible()
  for (const code of ['C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7']) {
    await expect(page.getByText(code, { exact: true }).first()).toBeVisible()
  }
  await expect(page.getByText('Приховано').first()).toBeVisible()
  await expect(page.getByText(/4\s+відповідей/)).toHaveCount(0)
})

test('відкритий цикл показує безпечний стан без результатів', async ({ page }) => {
  await loginInBrowser(page, adminEmail)
  await page.goto('/admin')
  await page.getByLabel('Цикл оцінювання').selectOption('3')
  await expect(page.getByText('Результати стануть доступними після закриття циклу.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Бали компонентів' })).toHaveCount(0)
})

test('Dashboard не має горизонтального переповнення на мобільній ширині', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  await loginInBrowser(page, adminEmail)
  await page.goto('/admin/analytics')
  await expect(page.getByRole('heading', { name: 'Бали компонентів' })).toBeVisible()
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }))
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport)
})
