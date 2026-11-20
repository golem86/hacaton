# V2 hardening — інсталятор, Caddy, оновлення на місці, резервне копіювання (гілка fix/v2-infra-installer)

База: 47e0ba8 (стан сервера TLSFIX5). Контракт: `docs/V2_HARDENING_CONTRACT.md`, розділи 2 і 5. Статус: перевірено лише локально;
на сервері нічого не запускалося. Деталі експлуатації: `docs/UPGRADE_IN_PLACE.md`.

## Зміни

| № | Що | Файли |
|---|---|---|
| I1 | Caddy: журнал `default` без `http.log.error`, `http.handlers.reverse_proxy`, `http.stdlib`; CSP SPA (`img-src 'self'`, без `unsafe-*` і `data:`), CSP `/docs` із sha256 вбудованого скрипта Swagger (FastAPI 0.163.1), CSP API; Permissions-Policy; `request_body max_size 256KB` для `/api/*`, `/v2/*`; `keepalive 4s` до 127.0.0.1:8100; збережено HSTS, nosniff, DENY, Referrer-Policy, `-Server`, `-X-Role` (×2), `admin off`, лише 100.111.221.74:443, файлову TLS-пару, `/redoc` 404 | `deploy/Caddyfile` |
| I2 | `New-V2TargetConfig`: Caddyfile — UTF-8 без BOM (раніше cp1251 → подвійне кодування коментарів) | `V2-install-common.ps1` |
| I3 | `Test-V2WinswXml`: `--no-proxy-headers` вимагає рівно `TRUSTED_PROXIES=127.0.0.1,::1` | `V2-install-common.ps1` |
| I4 | `runtime-harness.ps1`: версії БД з `$V2DbSet` (3/1), а не закріплене 2 | `runtime-harness.ps1` |
| I5 | `v2_db_tool.py`: таблиця `SCHEMA_SPECS` (integrity 3/4/5, auth 1/2), строгі перевірки + твердження контракту, `restore`, `backup --kind/--strict`, `mark-synthetic`, `bind-check` (SHA джерел — з маніфесту релізу), `user-version` | `v2_db_tool.py`, `test_v2_db_tool.py` |
| I6 | `Update-V2InPlace.ps1`, `Rollback-V2InPlace.ps1` (неінтерактивно, SSH), спільна бібліотека й симуляція | `upgrade/*` |
| I7 | `Register-V2BackupTask.ps1` + `Invoke-V2DailyBackup.ps1` (SYSTEM, 03:30, 14 копій, restore-test) | `upgrade/*` |
| I8 | Режим запуску: delayed-auto для обох служб **за замовчуванням** (`-KeepManualStart` — відмова); залежність Caddy → Tailscale перевіряється | `upgrade/Update-V2InPlace.ps1` |
| I9 | `Protect-V2Leftovers.ps1` (звіт / `-Apply`, без видалення) і `Disable-V2InstallLeftoverTasks.ps1` | `upgrade/*` |
| I10 | `Rotate-V2SecretKey.ps1`; рішення щодо DPAPI і процедура ротації SMTP | `upgrade/*`, `docs/UPGRADE_IN_PLACE.md` |
| I11 | `V2-release-preflight.ps1`: очікування TLSFIX5 (auto_https off, лише IPv4, файлова пара, журнали, CSP, request_body, keepalive) на цільовій формі через stdin; Machine/User-змінні — лише імена | `deploy/V2-release-preflight.ps1` |
| I12 | Документація оновлення на місці; ці нотатки | `docs/UPGRADE_IN_PLACE.md` |

## Що підставити інтегратору після злиття backend

1. `bind-check` на зібраному backend (auth 2, integrity 5) з маніфестом `BACKEND-SHA256.txt`; при `B03` — замінити DDL у
   `SCHEMA_SPECS[("auth", 2)]` / `[("integrity", 5)]` фактичним (імена тригерів, NOT NULL, FK, позиція `actor_user_id`,
   форма `instance_meta`), прапорці `strict_sql`. Твердження `contract` не змінювати без зміни контракту.
2. Міграції перебудови таблиць — 12-кроковою процедурою SQLite (інакше I08/A08: FK на тимчасове ім'я).
3. Пакет оновлення за `docs/UPGRADE_IN_PLACE.md` §1: `backend-src.zip` + `BACKEND-SHA256.txt` (байти LF), dist main-final,
   `Caddyfile` (шаблон), `requirements-hashed.txt` + `wheels\` (charset_normalizer 3.5.2, pillow 13.0.0, reportlab 5.1.0,
   xlsxwriter 3.3.3), `APPROVED-SHA256.txt` окремим каналом.
4. CSP `/docs`: при зміні FastAPI/параметрів Swagger — перерахувати хеш (`test-caddy-config.ps1` C7).
5. SHA256 нових `V2-install-common.ps1` і `v2_db_tool.py` змінилися: скрипти TLSFIX5 на сервері (`V2-release-TLSFIX5-20261120`)
   закріплені на старих файлах і працюють далі зі своїми копіями — нові файли розміщувати в окремому каталозі релізу.

## Відомі обмеження

- На сервері не перевірено; SCM/ACL/HTTP-адаптери — лише симуляція (`-Simulate`) і перевірений код TLSFIX5.
- Clean Install досі закріплений на dde86e6 (версії 3/1, deploy ZIP d7c523a1…).
- `Restart-V2Tlsfix5Verified.ps1` / `Verify-V2Tlsfix5Runtime.ps1` (TLSFIX5) вимагають Manual і версії 3/1 — після оновлення не використовувати;
  завдання TLS-поновлення сумісне (Auto/Manual, `tls`-рядок Caddyfile збережено, ACL Caddyfile не змінюється).
