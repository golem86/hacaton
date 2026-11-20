# C1–C8 — schema-3 Clean Install candidate (2026-11-20)

Оцінка за `CLEAN_INSTALL_V2_C1_C8_GATE_CRITERIA_FOR_5.md` №4. Це звіт реалізатора; незалежне приймання іншою особою та Windows runtime ще потрібні. `PASS local` означає лише код і синтетичні локальні дані. Повний gate залишається **BLOCKED**.

| Gate | Локальні докази | Стан повного gate |
| --- | --- | --- |
| C1, окремий clean-only | `static-clean-install` CI-S1–S9, перевірка порожнього root/data, відсутність шляху restore, негативні тести повторного використання | PASS local; VM NOT RUN |
| C2, автономні артефакти | Окремі deploy/tools ZIP з SHA256, pinned WinSW/Caddy, код не бере executables з V1. Побайтова відповідність офіційним GitHub release assets задокументована в `TOOL_PROVENANCE.md` | PASS local; політика щодо непідписаних EXE та runtime на VM PENDING |
| C3, release/preflight/ізоляція | R-01/TLS локальні позитивні й негативні фікстури, порти/Windows build/DNS перевіряє код | VM H1–H12, test DNS/IP, effective ACL NOT RUN |
| C4, нові SQLite/backup | Основна схема 3, auth 1, strict A01–A13 до й після bootstrap і на копії, fingerprint, restore-test; локальна репетиція й backend pytest | PASS local; VM NOT RUN |
| C5, ACL/секрети/bootstrap | Атомарне створення root, ACL assertions і synthetic bootstrap тести, локальний перегляд журналів | Effective virtual SID ACL, interactive bootstrap і redaction на VM NOT RUN |
| C6, Windows Services/мережа | Статичний WinSW/Caddy XML, synthetic stop/partial-service tests, frontend E2E з власними портами | SCM/WinSW, service SID, TLS/2FA/restart NOT RUN |
| C7, відмови/cleanup | Synthetic fault injection seed/migration/backup/auth/bootstrap/install/TLS, FAILED/REVOKED/Disabled, `-Abort` ownership tests | Реальні fault injection/SCM cleanup, reboot NOT RUN |
| C8, release evidence | Exact ZIP/manifests, `run-all.ps1`, raw local logs, mutation і diff у фінальному пакеті | Незалежний review та весь host gate NOT RUN → BLOCKED |

**Upgrade/Rollback** має окремий gate. Clean Install не викликає `Invoke-V2DbRestore`. Для майбутнього rollback залишається окреме питання: після першої перевірки SHA256 backup-файла він може змінитися до копіювання, якщо оператор вибере шлях, доступний іншому записувачу. До enable rollback потрібні захищений backup source/handle або повторна hash-bound копія з монопольним доступом та окремі тести.

**Рішення зараз:** schema-3 local candidate може бути переданий на незалежний review. Ізольована VM — лише після окремого дозволу №5 із конкретними параметрами. Production deployment — NO-GO.
