import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'
import type { FullConfig } from '@playwright/test'

export default async function globalSetup(_config: FullConfig) {
  const backendDir = resolve(process.cwd(), '..', 'backend')
  const python = process.env.V2_E2E_PYTHON || 'python'

  const seed = spawnSync(python, ['-m', 'app.seed'], {
    cwd: backendDir,
    env: process.env,
    encoding: 'utf8',
    windowsHide: true,
  })
  if (seed.status !== 0) {
    throw new Error(`Не вдалося створити синтетичну БД для E2E (код ${seed.status ?? 'невідомий'}).`)
  }

  const createAccounts = [
    'from app.v2_auth import create_user, migrate_auth_db',
    'migrate_auth_db()',
    'create_user("E2E Admin", "e2e-admin@example.test", __import__("os").environ["V2_E2E_TEST_PASSWORD"], role="admin")',
    'create_user("E2E User", "e2e-user@example.test", __import__("os").environ["V2_E2E_TEST_PASSWORD"], role="user")',
  ].join('; ')
  const accounts = spawnSync(python, ['-c', createAccounts], {
    cwd: backendDir,
    env: process.env,
    encoding: 'utf8',
    windowsHide: true,
  })
  if (accounts.status !== 0) {
    throw new Error(`Не вдалося створити локальні синтетичні E2E-акаунти (код ${accounts.status ?? 'невідомий'}).`)
  }
}
