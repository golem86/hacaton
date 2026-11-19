# CI-01 (P0) — інвалідація READY після пізнього збою Clean Install

| | |
| --- | --- |
| Для | №5; повторна перевірка — №4 |
| Підготував | №2, 19.11.2026 |
| Ревізія | CI-FIX1 (на базі ревізії Clean Install; AUDITFIX3 — заморожений baseline, Upgrade/Rollback не змінено) |

## 1. Дефект (підтверджено)

У ревізії Clean Install після `CLEAN-INIT-OK` (кінець 4.5) збій на 4.6 / 4.7 / 5 мав такі наслідки:
- `catch` писав `CLEAN-INSTALL-FAILED` **лише в корінь V2**, а `Assert-V2DataReady` перевіряє `data\`, де лишався `CLEAN-INIT-OK` → стан приймався як READY;
- помилка запису маркера мовчки ігнорувалась (`catch { }`);
- служби лишались `Manual`: ручний `sc start` минав `Assert-V2DataReady`.

**Знайдено додатково:** перевірки «корінь/служба V2 уже існує» стояли всередині `try`. Тому повторний запуск поверх **наявного** встановлення потрапляв у `catch` і зупиняв чужі служби V2.

## 2. Виправлення (`V2-install-common.ps1`, `clean-install.ps1`)

| № вимоги №5 | Реалізація |
| --- | --- |
| 1. Помилка після ініціалізації БД інвалідує READY | `Invoke-V2CleanInstallFailClosed`, у такому порядку: (1) `CLEAN-INIT-FAILED-INSTALL-<ts>` у `data\` — першим; (2) `CLEAN-INIT-OK-*` → `CLEAN-INIT-REVOKED-*`; (3) `CLEAN-INSTALL-FAILED-<ts>` у корені; (4) зупинка лише служб V2; (5) служби V2 → `Disabled`; (6) самоперевірка: `Assert-V2DataReady` має дати STOP. Будь-яка невдача кроку → `STOP: FAIL-CLOSED НЕ ЗАВЕРШЕНО`, exit 2 (не «успіх») |
| 2. `Assert-V2DataReady` відхиляє FAILED/IN-PROGRESS незалежно від старого OK | STOP на **будь-якому** маркері `CLEAN-INIT-*`, крім `CLEAN-INIT-OK-*` (FAILED, FAILED-INSTALL, IN-PROGRESS, REVOKED, невідомий), і на `CLEAN-INSTALL-FAILED-*` у корені. Позитивний маркер, як і раніше, обов'язковий |
| 3. Без resume і повторного використання часткових SQLite | `$Owned` = `$true` лише після перевірки «кореня немає» і до `New-V2Root`. Наявний корінь → STOP без змін. `Initialize` — лише порожній `data\`. `Complete` — лише за рівно одного `IN-PROGRESS`. Шляху продовження немає — тільки свідоме `-Abort` і новий Clean Install |
| 4. Fail-closed лише для V2, без видалення БД | діє лише на `integrity-v2-backend/-caddy` і корінь, створений цим запуском; у функції немає `Remove-Item`/`Delete` (CI-S6); БД і копії не змінюються (перевіряється SHA256 у тестах) |
| 5. Негативні тести 4.6 / 4.7 / 5 | `CI.late-4.6`, `CI.late-4.7`, `CI.late-5`; також `CI.late-markerfail`, `CI.late-nodisable`, `CI.late-abort`, `CI.ready-rootfailed`, `CI.ready-revoked`, `CI.ready-ok+revoked`, `CI.ready-ok+failed-install`, `CI.ready-ok+unknown`; статика CI-S6 |
| 6. Мутація: відсутність інвалідації READY виявляється | MC10 (немає FAILED-INSTALL і відкликання OK), MC11 (стара перевірка Assert), MC12 (маркер у корені ігнорується), MC13 (без `Disabled`), MC14 (fail-closed видаляє БД), MC15 (незавершений fail-closed звітує успіх), MCS3 (catch без fail-closed — поведінка до виправлення), MCS4 (без `$Owned`) |

**Обмеження локальних тестів:**
- служби й процеси — фейкові адаптери; справжні SCM, `Disabled → 1058` і перезапуск ОС — сценарій C3 T10/T10a (тест-хост, BLOCKED);
- оркестратор як цілісний процес не запускався (потрібні адміністратор і служби). Його структуру доводить CI-S6, а поведінку fail-closed — CI.late-*.

## 3. Знайдено в тестовому інструментарії

- **Справжній `sc stop`.** У частині тестів після розділу Q діє справжній `Invoke-V2Native`. Під час налагодження нові тести CI.late-* один раз викликали справжній `sc stop integrity-v2-backend / -caddy`. Служб на ПК №2 немає, тож результат 1060 «служби не існує» і жодних змін. Тепер CI.late-* підміняють `Invoke-V2Native` фейком, як і тести переривання. Запобіжник I9 нативні виклики `sc.exe` не рахує — пропозиція для №4.
- **`run-all.ps1` → паралельний режим** (вимога користувача прискорити прогони):
  - усі набори і мутації стартують одночасно, кожен у власному процесі з власним `%TEMP%`;
  - журнали оформлюються після завершення, у порядку оголошення;
  - `Start-Process` у PS 5.1 без консолі інколи повертав `ExitCode`/`ExitTime = $null` (5 з 8 запусків). Виявлено на `test-audit-gate`, перейшли на `System.Diagnostics.Process`: 8/8 стабільно;
  - `test-audit-gate` (B-04) тепер перевіряє нові `Start-Suite`/`Complete-Suites`, MB4 KILLED.
