# Integrity Management Dashboard V2 — Windows installer (Clean Install) — **WIP**

Статус: **WIP, не для встановлення.** Clean Install gate **не пройдено**: C2, C3, C5–C7 BLOCKED (немає ізольованого Windows-хоста), C8 FAIL (обов'язкові NOT RUN). Upgrade/Rollback — окремий BLOCKED gate. **DEPLOYMENT NO-GO.**

Автор: учасник №2. Ревізія: **CI-FIX1** (AUDITFIX3 + Clean Install + виправлення Caddy `Job` + CI-01 + preflight C3 + fault injection C7).

## Production-параметри в Git відсутні

- Ім'я вузла tailnet сервера та його IP замінено документаційними значеннями: `v2-host.tailnet.example`, `192.0.2.10`, `2001:db8::10`.
- `clean-install.ps1 -TlsHost/-TlsAddresses` — обов'язкові параметри без значень за замовчуванням.
- **Відомий WIP-пункт:** `FRONTEND_ORIGINS` у `integrity-v2-backend.xml.template` і в репетиції (`V2-install-common.ps1`) — фіксоване документаційне значення. Перед реальним встановленням його має замінити значення з приватного пакета; параметризація — наступна ревізія.
- Секретів немає: SMTP — плейсхолдери `__V2_SMTP_*__` (вводяться приховано як SecureString під час встановлення), ключі генеруються під час встановлення, пошта лише `@example.test`.
- Бінарники (WinSW, Caddy), deploy ZIP, БД і журнали в Git не додаються. Провенанс артефактів — `docs/CI02_ARTIFACT_PROVENANCE.md`; самі артефакти передано №5 окремим пакетом.

## Склад

| Файл | Призначення |
| --- | --- |
| `clean-install.ps1` | оркестратор Clean Install: етапи 4.0–4.7, smoke, `-Abort` |
| `V2-install-common.ps1` | спільні функції: служби, ACL, БД, fail-closed, preflight |
| `v2_db_tool.py`, `v2_job_launcher.py`, `job_child.py` | інструменти БД і Job Object |
| `*.xml.template` | шаблони WinSW 2.12.0 (`jobtest` — лише для тестів) |
| `V2_INSTALLATION_FINAL_PLAN.md` | план встановлення (Upgrade/Rollback — BLOCKED) |
| `run-all.ps1` | єдиний runner: усі набори й мутації паралельно, кожен із власним `%TEMP%`; required NOT RUN → FAIL |
| `test-rev3-negative.ps1`, `test_v2_auth_schema.py`, `test_v2_job.py`, `rehearse-rev3.ps1`, `static-*.ps1`, `test-audit-gate.ps1`, `runtime-harness.ps1`, `mutate.py` | тести, статика, мутації, runtime harness |
| `docs/` | CI-01, CI-02, матриця C1–C8 за критеріями №4, вимоги до тест-хоста, gate |

## Запуск перевірок (Windows PowerShell 5.1)

```
powershell.exe -NoProfile -File installer\windows-v2\run-all.ps1 -LogDir <поза репозиторієм> -Py <python 3.12+> -BackendPy <venv backend> -DeployZip <integrity-v2-dde86e6-deploy.zip> [-WithMutation -MutationJobs 8]
```

Потрібен перевірений `integrity-v2-dde86e6-deploy.zip` (SHA256 `62363714…`), у Git його немає.

## Статус перевірок (19.11.2026, ПК №2: Windows 11, PS 5.1.26100, Python 3.12, без прав адміністратора)

| Набір | PASS | FAIL | NOT RUN |
| --- | --- | --- | --- |
| test_v2_auth_schema | 62 | 0 | 0 |
| test_v2_job | 46 | 0 | **2** (J10, J18.winsw-timeout — потрібні справжні служби на тест-хості) |
| test-rev3-negative | 271 | 0 | 0 |
| test-audit-gate (B-04) | 1 | 0 | 0 |
| static-rev3 / static-clean-install | 25 / 7 | 0 | 0 |
| rehearse-rev3 | 21 | 0 | 0 |
| runtime-harness RH0 | PASS (відмова на непогодженому хості) | — | — |
| mutation (у пакеті CI-FIX1) | 72 KILLED | 0 | 0 |

`run-all.ps1` завершується з exit 1 — **за задумом**: є обов'язкові NOT RUN. Це не PASS.

## Відомі блокери

1. Немає ізольованого Windows тест-хоста. Блокує J10, J18, runtime C2/C3/C5–C7 (сценарій `docs/C3_TEST_HOST_REQUIREMENTS.md`).
2. Потрібна збірка Windows сервера з read-only preflight (`-ExpectedWindowsBuild`).
3. Незалежний re-audit №4.
4. WinSW і Caddy без підписів Authenticode — рішення №4/№5.
5. Параметризація `FRONTEND_ORIGINS` (див. вище).
