import { defineConfig } from '@playwright/test'
import { existsSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendDir = dirname(fileURLToPath(import.meta.url))
const repoDir = resolve(frontendDir, '..')
const backendDir = resolve(repoDir, 'backend')
const pythonDefault = process.platform === 'win32'
  ? resolve(backendDir, '.venv', 'Scripts', 'python.exe')
  : resolve(backendDir, '.venv', 'bin', 'python')
const python = process.env.V2_E2E_PYTHON || (existsSync(pythonDefault) ? pythonDefault : 'python')
const runDir = process.env.V2_E2E_TEMP_DIR || mkdtempSync(join(tmpdir(), 'im-v2-e2e-'))
const backendPort = process.env.V2_E2E_BACKEND_PORT || '8018'
const questionnairePort = process.env.V2_E2E_QUESTIONNAIRE_PORT || '8020'
const frontendPort = process.env.V2_E2E_FRONTEND_PORT || '5175'
const apiBaseURL = `http://127.0.0.1:${backendPort}`
const questionnaireAPIURL = `http://127.0.0.1:${questionnairePort}`
const frontendBaseURL = `http://127.0.0.1:${frontendPort}`
const testPassword = 'E2E-Only-Local-Synthetic-2026!'

const localEnv: Record<string, string> = {
  ...Object.fromEntries(Object.entries(process.env).filter((entry): entry is [string, string] => typeof entry[1] === 'string')),
  APP_ENV: 'development',
  INTEGRITY_DB: join(runDir, 'integrity.db'),
  V2_AUTH_DB: join(runDir, 'auth.db'),
  V2_AUTH_DEV_MAIL: '1',
  V2_AUTH_SECURE_COOKIE: '0',
  INTEGRITY_DEMO_XROLE: '0',
  FRONTEND_ORIGINS: frontendBaseURL,
  PYTHONUTF8: '1',
  V2_E2E_PYTHON: python,
  V2_E2E_TEMP_DIR: runDir,
  V2_E2E_API_URL: apiBaseURL,
  QUESTIONNAIRE_E2E_DB: join(runDir, 'official-questionnaire.prototype.sqlite'),
  V2_E2E_QUESTIONNAIRE_API_URL: questionnaireAPIURL,
  V2_E2E_FRONTEND_URL: frontendBaseURL,
  V2_E2E_ADMIN_EMAIL: 'e2e-admin@example.test',
  V2_E2E_USER_EMAIL: 'e2e-user@example.test',
  V2_E2E_TEST_PASSWORD: testPassword,
}

Object.assign(process.env, localEnv)

const shellQuote = (value: string) => `"${value.replaceAll('"', '\\"')}"`

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [
    ['list'],
    ['junit', { outputFile: 'test-results/e2e-junit.xml' }],
  ],
  outputDir: 'test-results/playwright-output',
  use: {
    baseURL: frontendBaseURL,
    browserName: 'chromium',
    headless: true,
    screenshot: 'off',
    trace: 'off',
    video: 'off',
    actionTimeout: 8_000,
    navigationTimeout: 12_000,
  },
  webServer: [
    {
      command: `${shellQuote(python)} -m uvicorn app.main:app --host 127.0.0.1 --port ${backendPort}`,
      cwd: backendDir,
      env: localEnv,
      url: `${apiBaseURL}/api/health`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: `${shellQuote(python)} -m uvicorn prototypes.official_e2e_server:app --host 127.0.0.1 --port ${questionnairePort}`,
      cwd: backendDir,
      env: localEnv,
      url: `${questionnaireAPIURL}/_e2e/health`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: `pnpm exec vite --host 127.0.0.1 --port ${frontendPort} --strictPort`,
      cwd: frontendDir,
      env: {
        ...localEnv,
        VITE_API_PROXY_TARGET: apiBaseURL,
        VITE_QUESTIONNAIRE_TEST_API_TARGET: questionnaireAPIURL,
      },
      url: frontendBaseURL,
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
})
