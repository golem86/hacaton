# Windows Clean Install V2, schema 3 — контрольований план

Стан: локальний кандидат. Справжній Windows SCM/WinSW, service SID, ACL, TLS, reboot і production не перевірені. Жоден крок цього документа не є дозволом виконувати інсталяцію.

## Exact artifacts

- `integrity-v2-schema3-manager-deploy.zip`: SHA256 `d7c523a167eec578a03ed9b0ede62868aed1d4c59f50fbf2b78f997fbb79a5db`. Вкладені backend schema 3 (55 файлів), frontend dist (3 файли), wheelhouse для Python 3.13, Caddyfile, manifests і read-only preflight.
- `integrity-v2-tools-winsw2.12.0-caddy2.11.9.zip`: SHA256 `abce6a9ce7afde4ab938d2d66062abf732668960c8c12b53fdd2e9d9b68fbaba`. WinSW/Caddy перевіряються за окремими pinned hashes і версіями в `V2-install-common.ps1`.
- Інсталятор: `candidate/clean-install.ps1` разом з рештою `candidate/`. Точний SHA256 у зовнішньому маніфесті фінального пакета.

## Порядок

1. №5 визначає ізольовану VM, snapshot, Windows build, test-only DNS/IP, синтетичний mail sandbox та окремим рішенням дозволяє runtime. До встановлення виконати H1–H12 і read-only preflight; за конфлікту зупинитися.
2. На VM без V1 послідовно виконати T0–T13 з `C3_TEST_HOST_REQUIREMENTS_R03.md`. Не змішувати запуски на одному стані VM; фіксувати snapshot і SHA артефактів.
3. `clean-install.ps1` запускається лише з `-TestHost`, `-DecisionRef`, exact `-ToolsZip`, `-DeployZip`, Python 3.13.14 x64, схваленим `-ExpectedWindowsBuild`, тестовими `-TlsHost`/`-TlsAddresses` і синтетичною admin-скринькою. Пароль адміністратора вводиться інтерактивно як SecureString. Production hostname/IP із шаблонів не застосовувати як тестові.
4. Після PASS перевірити C1–C8 та незалежний review особою, яка не реалізовувала зміни. Required NOT RUN або FAIL означає NO-GO. До production потрібні окремий read-only preflight сервера і явний дозвіл №5.

## Поведінка при збої

- До створення нового кореня інсталятор не змінює наявну V2-інсталяцію. Після створення власного кореня збій записує FAILED-маркери, відкликає READY, зупиняє й переводить у Disabled лише підтверджені власні служби. Якщо cleanup недоведений, код виходу 2 і ручне рішення №5.
- `-Abort` допустимий лише для невдалої спроби з FAILED-маркерами. До `stop/uninstall` перевіряється точний `PathName` усіх наявних служб. Корінь перейменовується в `-abandoned-*`; БД не використовуються повторно.
- Clean Install не викликає `Invoke-V2DbRestore` і не використовує Upgrade/Rollback. Останній має окремий gate. Файл `V2-release-preflight.ps1` у deploy ZIP є read-only перевіркою для майбутнього сервера й містить server-specific передумови V1/IP; він не замінює H1–H12 на ізольованій VM.

## Evidence

Тести й статуси — в `RUN-SUMMARY.txt` і `C1_C8_STATUS_SCHEMA3.md` фінального пакета. Локальні синтетичні PASS не є доказом Windows SCM/ACL/TLS. Невдалі проміжні прогони залишаються у робочих журналах із причиною; фінальні результати прив'язані до exact SHA256 кандидата.
