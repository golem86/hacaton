import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, join, resolve, sep } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const frontendDir = resolve(fileURLToPath(new URL('..', import.meta.url)))
const tempDir = mkdtempSync(join(tmpdir(), 'im-v2-e2e-'))
const cli = join(frontendDir, 'node_modules', '@playwright', 'test', 'cli.js')

let result
try {
  result = spawnSync(process.execPath, [cli, 'test', '--config=playwright.config.ts', ...process.argv.slice(2)], {
    cwd: frontendDir,
    env: { ...process.env, V2_E2E_TEMP_DIR: tempDir },
    stdio: 'inherit',
    windowsHide: true,
  })
} finally {
  const tempRoot = resolve(tmpdir())
  const resolved = resolve(tempDir)
  if (resolved.startsWith(`${tempRoot}${sep}`) && basename(resolved).startsWith('im-v2-e2e-')) {
    rmSync(resolved, { recursive: true, force: true })
  }
}

process.exitCode = result?.status ?? 1
