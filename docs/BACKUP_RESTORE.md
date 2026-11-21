# Резервні копії та відновлення робочого сервера V2

Стан на 21.11.2026: реліз `integrity-v2-48256d6`, схеми integrity **7** і auth **2**. Шляхи наведено для стандартного встановлення в `C:\srv\integrity-v2`. Імені та адреси сервера тут немає навмисно.

## 1. Що є на сервері

| Що | Де | Як створюється |
|---|---|---|
| Щоденна копія обох БД | `backups\daily\<yyyyMMdd-HHmmss>\` | Задача `Integrity-V2-DB-Backup`, щодня о 03:30. Інструмент `v2_db_tool.py backup` (SQLite backup API) робить копію, тест відновлення, `SHA256SUMS.txt` і `DAILY-BACKUP.json`. Ротація зберігає останні 14 вдалих запусків. Журнал — `backups\daily\daily-backup.log` |
| **Набір, готовий до розгортання** | `backups\deploy-ready-<stamp>\` | Створюється вручну з перевіреної щоденної копії (розділ 3). Ротація його не видаляє |
| Точка відкату оновлення | `backups\pre-upgrade-<stamp>\` | `Update-V2InPlace.ps1` перед кожним оновленням. Відкат — `Rollback-V2InPlace.ps1` ([UPGRADE_IN_PLACE.md](../installer/windows-v2/docs/UPGRADE_IN_PLACE.md)) |

Усі каталоги копій доступні лише групі Administrators і SYSTEM.

**Обмеження:** усі копії лежать на тому самому диску, що й робочі БД. Від відмови диска чи шифрувальника вони не захищають. Окремої копії на іншому носії поки немає.

## 2. Набір `deploy-ready-20261121-203248`

Створено 21.11.2026 з щоденної копії `daily\20261121-203248` (PASS).

| Файл | Зміст |
|---|---|
| `integrity_v2.db`, `v2_auth.db` | БД: 5 циклів, 1105 анкет, синтетичні дані |
| `SHA256SUMS.txt`, `DAILY-BACKUP.json` | Суми й звіт щоденної копії |
| `v2_db_tool.py` | Інструмент відновлення (той самий файл, що й у задачі бекапу, SHA256 закріплено) |
| `release-integrity-v2-48256d6\` | Пакет поточного релізу: `package\backend-src.zip`, `dist.zip`, шаблон `Caddyfile`, `installer\`, `APPROVED-SHA256.txt` |
| `MANIFEST.json` | SHA256 кожного файлу набору |
| `RESTORE.md` | Готові команди відновлення з конкретними SHA256 |

Під час створення перевірено:
- SHA256 обох БД збігаються з `SHA256SUMS.txt`;
- тестове відновлення в нові файли: `RESTORE OK` для integrity v7 (19 083 рядки) і auth v2 (74 рядки, строга схема);
- `pragma integrity_check = ok`, порушень зовнішніх ключів немає;
- п'ять файлів пакета релізу збігаються з `APPROVED-SHA256.txt`.

**Секретів у наборі немає:** XML служб, `V2_SECRET_KEY`, паролі SMTP, TLS-ключі й ключ LM лишаються лише в конфігурації служб. Для схеми integrity 7 у `v2_db_tool.py` немає строгого опису схеми, тому integrity перевіряється без `--strict`, як і в щоденній копії.

## 3. Як оновити набір

1. Запустіть щоденну копію позачергово: `Start-ScheduledTask -TaskName Integrity-V2-DB-Backup`. Дочекайтеся рядка `PASS` у `daily-backup.log`.
2. Створіть каталог `backups\deploy-ready-<stamp>` з ACL лише Administrators/SYSTEM, без успадкування.
3. Скопіюйте туди файли щоденної копії, `pkg\ops-backup\v2_db_tool.py` і каталог пакета чинного релізу.
4. Звірте SHA256 і виконайте тестове відновлення в окремий каталог, як у розділі 4. Після перевірки цей каталог видаліть.
5. Запишіть `MANIFEST.json` і `RESTORE.md`. Попередній набір видаліть, щоб не зберігати зайвих копій.

## 4. Відновлення БД на тому самому сервері

Від імені адміністратора:

```powershell
$d  = 'C:\srv\integrity-v2\backups\deploy-ready-20261121-203248'
$py = 'C:\Program Files\Python313\python.exe'
$ts = Get-Date -Format yyyyMMdd-HHmmss
Stop-Service integrity-v2-backend
Rename-Item C:\srv\integrity-v2\data\integrity_v2.db "integrity_v2.replaced-$ts.db"
Rename-Item C:\srv\integrity-v2\data\v2_auth.db "v2_auth.replaced-$ts.db"
& $py -I -B "$d\v2_db_tool.py" restore "$d\integrity_v2.db" C:\srv\integrity-v2\data\integrity_v2.db --expect-version 7 --sha256 <SHA256 з SHA256SUMS.txt> --kind integrity
& $py -I -B "$d\v2_db_tool.py" restore "$d\v2_auth.db" C:\srv\integrity-v2\data\v2_auth.db --expect-version 2 --sha256 <SHA256 з SHA256SUMS.txt> --kind auth --strict
Start-Service integrity-v2-backend
```

- Обидві команди мають вивести `RESTORE OK`.
- `restore` пише лише в новий файл, тому чинні БД спершу перейменовуються. Після перевірки сайту файли `*.replaced-*` можна видалити.
- Дані, записані після створення набору, буде втрачено.
- Готові команди з уже підставленими SHA256 є в `RESTORE.md` всередині набору.

## 5. Розгортання на новому сервері

1. Виконайте чисте встановлення з репозиторію на коміті `48256d6`: [CLEAN_INSTALL_CURRENT.md](../installer/windows-v2/docs/CLEAN_INSTALL_CURRENT.md). Секрети служби (`V2_SECRET_KEY`, SMTP) задаються заново, бо в набір вони не входять.
2. Перевірте пакет: SHA256 п'яти файлів у `package\` мають збігатися з `APPROVED-SHA256.txt`.
3. Відновіть БД, як у розділі 4.
4. Новий `V2_SECRET_KEY` робить недійсними старі сесії: користувачі просто входять знову. Паролі й прив'язки підрозділів зберігаються в БД.
