# C1–C8 за критеріями №4 — ревізія CI-FIX1

| | |
| --- | --- |
| Джерело критеріїв | №4 `CLEAN_INSTALL_V2_C1_C8_GATE_CRITERIA_FOR_5.md` (19.11.2026). Нумерація та формулювання — **лише №4** |
| Оцінює | №2 — первинні докази. Незалежна звірка — №4, рішення — №5 |
| Правило | PASS лише за **усіма** обов'язковими пунктами критерію. Будь-яка частина без доказу → BLOCKED/NOT RUN. PASS одного критерію іншому не зараховується |
| Журнали | `logs/` (зарахований паралельний прогін CI-FIX1), `RUN-SUMMARY.txt` |

## Зведення

| ID (№4) | Статус | Чого бракує до PASS |
| --- | --- | --- |
| C1 — scope та відокремлення | **PASS (первинно №2)** | незалежний static review і diff №4 |
| C2 — автономні release artifacts | **BLOCKED** | offline install transcript на хості без V1 (тест-хост); підписів у бінарників немає взагалі |
| C3 — release, preflight, ізоляція | **BLOCKED** | host transcript preflight (тест-хост); цільова збірка Windows — з read-only preflight сервера |
| C4 — нові SQLite та backup | **PASS (первинно №2, синтетично)** | незалежна звірка №4; прогін на тест-хості з Python 3.13.14 (локально 3.12) |
| C5 — ACL, секрети й bootstrap | **BLOCKED** | ефективні права virtual accounts і справжній bootstrap — лише на тест-хості |
| C6 — справжні Windows Services і мережа | **BLOCKED** | тест-хост (дозвіл №5) |
| C7 — часткові відмови й cleanup | **BLOCKED** (локально PASS) | fault injection install/start/TLS на справжніх службах; доказ виходу процесів на SCM |
| C8 — підсумковий gate і пакет | **FAIL (gate)** за правилом №4 | required NOT RUN: J10, J18.winsw-timeout, C3/C6 runtime; незалежний review №4 |

**Підсумок:** Clean Install gate **не пройдено** (BLOCKED, runtime). DEPLOYMENT **NO-GO**.

## Детально

### C1 — scope та відокремлення → PASS (первинно №2)

| Вимога №4 | Доказ |
| --- | --- |
| Окрема точка входу й manifest clean-only | `candidate/clean-install.ps1`; `MANIFEST-SHA256.txt` |
| Відсутність служб, root і data V2 **до будь-якого запису** | 4.0: служби V2 → STOP; `$V2Root` існує → STOP; порти і хост — до Stage 4.1. Статика **CI-S7**; мутації MCS5 |
| Static call graph без restore/upgrade/rollback | **CI-S1** (7 функцій Rollback недосяжні), **CI-S2** (Job Object), **CI-S5**, **CI-S6**; мутації MCS1–MCS4 |
| FAIL: невідомий файл, БД, маркер чи служба | корінь має не існувати. `Assert-V2DataReady` відхиляє будь-який маркер, крім OK: CI.ready-ok+unknown, -ok+revoked, -ok+failed-install, -rootfailed; мутації MC11, MC12 |
| FAIL: автоматичний resume | неможливий: `$Owned`, порожній `data\` (CI.init-notempty, CI.fault-* reuse → STOP), CI-S6; MCS4 |

### C2 — автономні release artifacts → BLOCKED

| Вимога №4 | Доказ / стан |
| --- | --- |
| Пакет доставляє WinSW 2.12.0 і Caddy з SHA256, версіями, provenance | **PASS:** `artifacts/integrity-v2-tools-winsw2.12.0-caddy2.11.9.zip` (SHA256 `abce6a9c…baba`); `CI02_ARTIFACT_PROVENANCE.md`. WinSW = офіційний `WinSW-x64.exe` v2.12.0 (`05b82d46…`), FileVersion 2.12.0.0 (`Assert-V2Winsw`). Caddy = офіційний архів 2.11.9: SHA512 = `checksums.txt`, SHA256 = digest GitHub; `caddy.exe` `2622e239…` |
| Підписи | **немає в джерела:** WinSW і Caddy не мають Authenticode, sigstore для Caddy не перевірено — ризик P-1/P-2, рішення №4/№5 |
| Installer читає лише з V2 release | CI-S3, CI-S4; мутація MCS2; `Expand-V2Tools` (склад, без виходу за каталог, SHA): CI.tools-*, MC5 |
| Встановлення на тест-хості без V1 | **NOT RUN → BLOCKED** (немає хоста); `C3_TEST_HOST_REQUIREMENTS.md` H3, T1 |

### C3 — release, preflight, ізоляція → BLOCKED

| Вимога №4 | Доказ / стан |
| --- | --- |
| Підтверджений release ZIP і backend | deploy ZIP SHA `62363714…` перевіряється на 4.0; вихідний код backend = коміт `dde86e6` 52/52 побайтно (CI-02 §3) |
| Цільові Windows, Python, PowerShell; ресурси | **нове:** `Assert-V2HostPreflight` — збірка Windows = `-ExpectedWindowsBuild`, Windows PowerShell 5.1 Desktop x64, ≥ 2 ГБ вільно (CI.host-*; MC18, MC19). Python 3.13.14 x64 (4.0) |
| Вільні порти та імена служб | **нове:** `Assert-V2PortsFree` — TCP 80/443/8100/8199, UDP 443 до першого запису (CI.ports-*; MC16). Імена служб — 4.0 |
| Безпечні ancestors, reparse, ACL | `Assert-V2Ancestors`, `Assert-V2NoReparseChain`, `Get-V2AclRisk`: P5d–P5q |
| V1 baseline лише read-only, V1 не потрібна | `Get-V1Baseline -AllowAbsent`: CI.v1-absent, CI.v1-present; MC6 |
| Без зміни спільних ACL і портів для обходу | наявний `C:\srv` лише перевіряється; зайнятий порт → STOP, нічого не зупиняється |
| Host transcript | **NOT RUN → BLOCKED** |

### C4 — нові SQLite та backup → PASS (первинно №2, синтетично)

| Вимога №4 | Доказ |
| --- | --- |
| `data` порожній; seed/migration лише на нових БД | `Initialize-V2CleanDatabases`: CI.init-notempty, R10c |
| integrity, version, fingerprint, повна схема | verify `--expect-version 2`, відбиток = репетиції 5а, `check_schema` + `check_auth_schema`; CI.fault-verify/-fingerprint/-schema |
| Перевірений backup і restore-test **до** підтвердження міграції | `v2_db_tool backup`: перевірка копії, кількість рядків, **тест відновлення** (копія → тимчасова БД → check + відбиток) — до `migrations --confirm-verified-backup`; CI.fault-backup |
| Фінальні backups обох БД з hashes | `Complete-V2CleanDatabases`: `*-initial-*.db` обох БД + `SHA256SUMS` (R10a, CI.complete-ok) |
| `auth-schema` A01–A13 на новій `v2_auth.db` після bootstrap і на фінальній копії | CI.complete-badauth, CI.complete-badbackup, R10a/R10b (справжній backend); MC3; 62/62 auth |
| FAIL → STOP до старту служби | маркер FAILED і `Assert-V2DataReady`: CI.fault-* (7 кроків), CI.complete-*; MC17 |

### C5 — ACL, секрети й bootstrap → BLOCKED

| Вимога №4 | Доказ / стан |
| --- | --- |
| Атомарно захищений root; точні ACL | `New-V2Root` (SDDL під час створення), `Assert-V2AclExact/Matrix/Tree`: D4d, P5i–P5q |
| Ефективні права virtual accounts | **NOT RUN → BLOCKED** (справжні `NT SERVICE\*` лише на хості) |
| Секрети й пароль адміністратора поза логами | `Set-V2Secrets` (SecureString, XML-екранування, плейсхолдерів 0: R8a/R8b); bootstrap — `getpass` через `Invoke-V2Interactive`. Окремого тесту «журнал без секретів» на справжньому прогоні немає → на хості (T6) |
| DEMO-змінні лише для синтетичних даних | `Assert-V2SyntheticDb`: R7a/R7b, CI.complete-* |
| Справжній bootstrap | R10a (справжній backend, синтетично); справжній `getpass` на хості — NOT RUN |

### C6 — справжні Windows Services і мережа → BLOCKED

Усі вимоги потребують ізольованого хоста: WinSW 2.12.0 під virtual accounts, Manual, PID/SID, loopback, TLS, smoke 2FA/CSRF/roles, restart зі збереженням БД. Сценарій — `C3_TEST_HOST_REQUIREMENTS.md` T1–T8. Локальних доказів, що замінювали б runtime, **немає й не подаються**.

### C7 — часткові відмови й cleanup → BLOCKED (локально PASS)

| Сценарій №4 | Локальний доказ | На хості |
| --- | --- | --- |
| seed, migration, backup, auth-schema | CI.fault-seed/-verify/-fingerprint/-backup/-migrations/-schema/-auth-schema (FAILED, старт заборонено, reuse → STOP); MC17 | T9 |
| bootstrap | CI.complete-noadmin, CI.complete-badauth; R10b | T9 |
| install/start, TLS (після першого старту) | **CI-01:** CI.late-4.6, CI.late-4.7, CI.late-5 — READY інвалідовано, лише V2 Stopped + Disabled, БД без змін (SHA до/після); CI.late-markerfail/-nodisable; MC10–MC15, MCS3/MCS4 | T10, T10a |
| Доказ виходу всіх процесів | `Stop-V2Service` (дерево, обліковий запис служби) — фейкові процеси | **NOT RUN** |
| Без автоматичного DB restore; артефакти для рішення №5 | Rollback недосяжний (CI-S1); `-Abort` → `-abandoned-<ts>`; CI.abort-*, CI.late-abort | T11, T12 |

### C8 — підсумковий gate і пакет → FAIL (gate)

| Вимога №4 | Стан |
| --- | --- |
| Один відтворюваний runner, явні PASS/FAIL/NOT RUN; required NOT RUN → FAIL | `run-all.ps1` (паралельний режим, власний `%TEMP%` кожного набору); B-04 `test-audit-gate` + MB4 |
| Required NOT RUN | **є:** J10, J18.winsw-timeout (`test_v2_job`), C3/C6 runtime → **gate FAIL** |
| ZIP, manifest, hashes, diff, команди, версії хоста, сирі журнали | пакет CI-FIX1 (див. звіт). Проміжні прогони — окремими каталогами, не змішано |
| Незалежний review №4 | очікує |
| V1 baseline незмінний | локально V1 немає; на хості — T13 |
