import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { after, test } from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

/** Мобільна оболонка V2: іконки навігації, доступні назви кнопок і компактне меню облікового запису. */
const server = await createServer({ server: { middlewareMode: true, hmr: false }, optimizeDeps: { noDiscovery: true }, cacheDir: 'node_modules/.vite-shell-test', appType: 'custom', logLevel: 'error' })
after(() => server.close())
const nav = await server.ssrLoadModule('/src/v2/navigation.ts')
const icons = await server.ssrLoadModule('/src/v2/icons.tsx')
const account = await server.ssrLoadModule('/src/v2/AccountMenu.tsx')
const auth = await server.ssrLoadModule('/src/api/auth.ts')

const ROLES = ['admin', 'data_officer', 'user']
const html = element => renderToStaticMarkup(element)
/** Пункти меню ролі так, як їх показує оболонка: розділи + посилання на опитування для admin і data_officer. */
const shellItems = role => [...nav.navigationFor(role), ...(role === 'user' ? [] : [{ key: icons.SURVEY_NAV_KEY, title: 'Анонімне опитування' }])]
const user = role => ({ name: 'Олена Коваль', email: 'olena@example.test', role })

test('every navigation key of every role has its own inline SVG icon', () => {
  for (const role of ROLES) {
    const items = shellItems(role)
    assert.ok(items.length > 0, role)
    const drawn = new Set()
    for (const { key } of items) {
      assert.ok(icons.hasNavIcon(key), `немає іконки для ${role}/${key}`)
      const svg = html(createElement(icons.NAV_ICONS[key]))
      assert.match(svg, /^<svg[^>]* viewBox="0 0 24 24"/, key)
      assert.match(svg, /stroke="currentColor"/, key)
      assert.match(svg, /fill="none"/, key)
      assert.match(svg, /aria-hidden="true"/, key)
      drawn.add(icons.NAV_ICONS[key])
    }
    assert.equal(drawn.size, items.length, `іконки в меню ${role} не повторюються`)
  }
  assert.equal(icons.hasNavIcon('toString'), false)
  assert.match(html(createElement(icons.NavIcon, { name: 'unknown-section' })), /<svg/, 'невідомий ключ має запасну іконку')
})

test('icon nav buttons keep the Ukrainian section title as accessible name and tooltip', () => {
  for (const role of ROLES) {
    for (const item of shellItems(role)) {
      const markup = html(createElement(icons.NavButton, { navKey: item.key, title: item.title, onClick: () => {} }))
      assert.ok(markup.startsWith('<button type="button"'), item.key)
      assert.ok(markup.includes(`aria-label="${item.title}"`), item.key)
      assert.ok(markup.includes(`title="${item.title}"`), item.key)
      assert.ok(markup.includes(`<span class="v2-nav-text">${item.title}</span>`), item.key)
      const svg = markup.match(/<svg[^>]*>/)?.[0] ?? ''
      assert.match(svg, /class="v2-nav-icon"/, item.key)
      assert.match(svg, /aria-hidden="true"/, item.key)
      assert.match(svg, new RegExp(`data-icon="${item.key}"`), item.key)
      assert.doesNotMatch(markup, /is-active|aria-current/, item.key)
    }
  }
  const active = html(createElement(icons.NavButton, { navKey: 'testing', title: 'Цикли оцінювання', active: true, onClick: () => {} }))
  assert.match(active, /class="is-active"/)
  assert.match(active, /aria-current="page"/)
  assert.match(active, /aria-label="Цикли оцінювання"/)
})

test('mobile nav grid keeps every tap target at least 44 px wide from 320 to 430 px', () => {
  for (const role of ROLES) {
    const count = shellItems(role).length
    const style = icons.navGridStyle(count)
    assert.equal(style['--v2-nav-count'], count)
    for (const viewport of [320, 340, 360, 375, 390, 414, 430]) {
      const columns = viewport < 360 ? style['--v2-nav-cols-xs'] : style['--v2-nav-cols-sm']
      assert.ok(columns >= Math.ceil(count / 2), `${role}: не більше двох рядів`)
      const cell = (viewport - 24 - (columns - 1) * 4) / columns
      assert.ok(cell >= 44, `${role} @ ${viewport}px: ${cell.toFixed(1)}px`)
    }
  }
  assert.equal(icons.navGridColumns(7, 375), 7)
  assert.equal(icons.navGridColumns(7, 320), 4)
  assert.equal(icons.navGridColumns(9, 375), 5)
})

test('compact account menu renders only an avatar button; the popover is hidden until opened', () => {
  for (const role of ROLES) {
    const markup = html(createElement(account.AccountMenu, { user: user(role), compact: true, onLogout: () => {}, onLogoutAll: async () => {} }))
    const trigger = markup.match(/<button[^>]*class="v2-account-trigger"[^>]*>/)?.[0] ?? ''
    assert.ok(trigger, role)
    assert.match(trigger, /aria-expanded="false"/)
    assert.match(trigger, /aria-haspopup="dialog"/)
    assert.match(trigger, /aria-label="Обліковий запис: Олена Коваль"/)
    const controls = trigger.match(/aria-controls="([^"]+)"/)?.[1]
    assert.ok(controls, 'aria-controls')
    const panel = markup.match(new RegExp(`<div[^>]*id="${controls.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}"[^>]*>`))?.[0] ?? ''
    assert.match(panel, /class="v2-account-popover"/)
    assert.match(panel, /role="dialog"/)
    assert.match(panel, /hidden=""/, 'меню закрите в початковій розмітці')
    assert.match(markup, />ОК</, 'ініціали на аватарі')
    // Повна картка (ім’я, роль, email, «Вийти», «Вийти на всіх пристроях») — лише всередині прихованого меню.
    assert.ok(!markup.includes('v2-topbar-actions'))
    const hiddenPart = markup.slice(markup.indexOf(panel))
    for (const text of ['Олена Коваль', auth.roleLabel(role), 'olena@example.test', 'Вийти<', 'Вийти на всіх пристроях']) assert.ok(hiddenPart.includes(text), text)
  }
})

test('full account card on desktop stays unchanged and has no avatar trigger', () => {
  const markup = html(createElement(account.AccountMenu, { user: user('admin'), onLogout: () => {}, onLogoutAll: async () => {} }))
  assert.match(markup, /^<div class="v2-topbar-actions"><div class="v2-account-menu">/)
  assert.match(markup, /<button class="v2-logout-button" type="button">Вийти<\/button>/)
  assert.match(markup, /<button class="v2-logout-all-button" type="button">Вийти на всіх пристроях<\/button>/)
  assert.ok(!markup.includes('v2-account-trigger'))
  assert.ok(!markup.includes('<svg'))
})

test('avatar initials use the first letters of the name', () => {
  assert.equal(account.accountInitials('Олена Коваль'), 'ОК')
  assert.equal(account.accountInitials('  тест  '), 'ТЕ')
  assert.equal(account.accountInitials(''), '?')
})

test('mobile CSS hides the topbar card, shows the avatar and keeps 44 px nav targets', async () => {
  const css = await readFile(new URL('../src/v2/v2.css', import.meta.url), 'utf8')
  const shell = css.slice(css.indexOf('/* Компактна мобільна оболонка'))
  const tablet = shell.match(/@media \(max-width: 900px\) \{([\s\S]*?)\n\}/)?.[1] ?? ''
  assert.match(tablet, /\.v2-account-compact \{ display: block; \}/)
  assert.match(tablet, /\.v2-topbar \.v2-topbar-actions \{ display: none; \}/)
  assert.match(tablet, /\.v2-nav-label, \.v2-nav-text \{ display: none; \}/)
  assert.match(tablet, /\.v2-nav button \{[^}]*min-height: 2\.75rem/)
  assert.match(css, /\.v2-account-compact \{[^}]*display: none/)
  assert.match(css, /\.v2-account-popover\[hidden\] \{ display: none; \}/)
  assert.match(css, /\.v2-account-trigger \{[^}]*width: 2\.75rem; height: 2\.75rem/)
})
