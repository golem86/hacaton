// Перевірка після `pnpm build`: тестовий стенд офіційних анкет (E2E-only сторінка, синтетичний API,
// E2E-коди) не потрапляє ні у frontend dist, ні в production-образи backend/frontend.
import assert from 'node:assert/strict'
import { readdir, readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoDir = resolve(frontendDir, '..')
const distDir = join(frontendDir, 'dist')
const forbidden = [
  'official-integration-harness',
  'official_e2e_server',
  'prototype-test-api',
  '/_e2e/verify',
  'e2e-only-form1',
  'e2e-only-form2',
]

async function walk(directory) {
  const files = []
  for (const item of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, item.name)
    if (item.isDirectory()) files.push(...await walk(path))
    else files.push(path)
  }
  return files
}

const distFiles = await walk(distDir)
assert.ok(distFiles.some(path => path.endsWith('.html')), 'production frontend dist must contain the application shell')
for (const marker of forbidden) {
  assert.ok(!distFiles.some(path => path.includes(marker)), `test-only artifact path found: ${marker}`)
}
for (const file of distFiles) {
  const text = (await readFile(file)).toString('utf8')
  for (const marker of forbidden) {
    assert.ok(!text.includes(marker), `test-only marker ${marker} found in ${file}`)
  }
}

const backendMain = await readFile(join(repoDir, 'backend', 'app', 'main.py'), 'utf8')
assert.ok(!backendMain.includes('official_e2e_server'), 'app.main must not import the E2E-only server')
assert.ok(!backendMain.includes('prototypes'), 'app.main must not mount questionnaire prototypes')
const backendDocker = await readFile(join(repoDir, 'backend', 'Dockerfile'), 'utf8')
assert.match(backendDocker, /COPY --chown=app:app app \.\/app/)
assert.ok(!/^\s*COPY\s+.*(?:prototypes|backend\/|\.\s+\.)/im.test(backendDocker),
  'backend production Dockerfile must not copy prototype/source trees')
const frontendDocker = await readFile(join(frontendDir, 'Dockerfile'), 'utf8')
const runtimeStage = frontendDocker.split(/^FROM caddy/im).at(-1) ?? ''
assert.match(runtimeStage, /COPY --from=build \/app\/dist \/srv/)
assert.ok(!runtimeStage.includes('e2e/'), 'frontend runtime image must not copy e2e files')

console.log(`Production artifact isolation PASS (${distFiles.length} frontend files; Docker runtime copy boundaries verified)`)
