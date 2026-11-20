# Синтетичний демо-цикл для звітів локальної LM

`python -m app.demo_cycle` додає в **синтетичну** БД один закритий цикл оцінювання з ≈150 анонімними анкетами
вигаданих учасників. За ним локальна LM (`docs/LOCAL_LM.md`) пише змістовні резюме, рекомендації й порівняння
з попереднім циклом (наприклад, `2026-I` із seed). Реальних людей і даних немає.

## Що генерується

Одна транзакція (або все, або нічого):

| Що | Значення за замовчуванням (`--responses 150 --seed 2026`) |
|---|---|
| Цикл | назва «Демо-цикл (синтетичні дані)», статус `closed`, `min_group_size` = 5 (як у seed), початок — 60 днів тому, завершення — 14 днів тому |
| `cycle_configs` | усі 4 категорії, опис «Демонстраційні синтетичні дані», анкета `demo-v1` |
| Анкети | 150: курсанти 100, НПП 43, керівництво 4, персонал 3; відповіді на **всі** питання анкети (`kind = survey`) у межах шкали |
| Підрозділи | з довідника `units`: Факультет 1 — 75, Факультет 2 — 52, Кафедра загальних дисциплін — 23 |
| Коди доступу | лише SHA-256 випадкових кодів (самі коди ніде не зберігаються й не виводяться): 150 використаних + 30 невикористаних; участь 83,3 % |
| Політики кодів | категорія кожного коду, строк дії вже минув |
| Журнал | одна подія `demo.cycle_generated`: `actor_role = "server"`, цикл, `details: {"count": 150}` |

Анонімність: керівництво (4) і персонал (3) менші за k = 5 і **приховуються** в `/results` (`suppressed: true`);
разом їх 7 ≥ k, тож вторинне приховування не зачіпає основні групи — курсантів і НПП видно.

Профілі відповідей різні за категоріями (рівень 0–100 → шкала питання) плюс індивідуальний зсув учасника
(σ = 8) і шум відповіді (σ = 11). Детерміновано від `--seed` (`random.Random(seed)`): той самий seed → ті самі
анкети й агрегати. Середні за компонентами для seed 2026:

| C1 | C2 | C3 | C4 | C5 | C6 | C7 |
|---|---|---|---|---|---|---|
| 59,3 | 69,3 | 52,4 | 52,5 | 74,5 | **36,5** | 59,2 |

Найсильніші — C5 «Навчання і комунікація» і C2 «Антикорупційна політика»; найслабший — C6 «Повідомлення про
порушення», у курсантів помітно нижчий, ніж у НПП; керівництво оцінює все вище (видно лише в загальних балах).

## Запобіжники

- Лише БД з позначкою `instance_meta('dataset', 'synthetic')` (ставить `python -m app.seed` або
  `v2_db_tool.py mark-synthetic`). Інакше **відмова** (код 2): демо-анкети не змішуються з реальними даними.
- Цикл із такою самою назвою вже є → відмова, нічого не змінено (повторний запуск безпечний).
- Схема лише перевіряється (`check_schema`, integrity schema 6); БД не мігрує й не створюється.
- Не потребує `V2_SECRET_KEY`; читає лише `INTEGRITY_DB` (у release обов'язкова) і `APP_ENV`.
- Коди виходу: `0` — виконано або план, `2` — відмова, `1` — помилка. Вивід — короткий підсумок без кодів доступу.

## Локально

З каталогу `backend` (синтетична БД із `python -m app.seed`):

```
python -m app.demo_cycle --responses 150 --seed 2026                  # лише план, нічого не пише
python -m app.demo_cycle --responses 150 --seed 2026 --confirm        # створити цикл
python -m app.demo_cycle --seed 7 --name "Демо seed 7" --confirm      # ще один цикл з іншими даними
```

## На сервері (Windows)

Обгортка `installer/windows-v2/ops/New-V2DemoCycle.ps1` бере `INTEGRITY_DB`, `V2_AUTH_DB`, `APP_ENV` і робочий
каталог із живого XML служби `integrity-v2-backend` (секрети не читаються), запускає `app.demo_cycle` з venv
служби. Backend зупиняти не потрібно. PowerShell від адміністратора, з каталогу, куди скопійовано скрипт:

1. **Резервна копія** INTEGRITY_DB (шлях — з XML служби, зазвичай `C:\srv\integrity-v2\data\integrity_v2.db`;
   ціль не повинна існувати):

   ```
   & 'C:\Program Files\Python313\python.exe' -I -B C:\srv\integrity-v2\pkg\ops-backup\v2_db_tool.py backup `
       C:\srv\integrity-v2\data\integrity_v2.db C:\srv\integrity-v2\backups\pre-demo-<час>.db `
       --expect-version 6 --kind integrity --strict
   ```

   Очікуваний рядок: `BACKUP OK user_version=6 … restore-test=ok sha256=…` — збережіть SHA256.
2. План: `powershell -NoProfile -ExecutionPolicy Bypass -File .\New-V2DemoCycle.ps1`
3. Застосування: `powershell -NoProfile -ExecutionPolicy Bypass -File .\New-V2DemoCycle.ps1 -Apply`
   (параметри `-Responses`, `-Seed`, `-Name` — як у CLI).

## Відкат

Цикл створюється однією транзакцією; при помилці нічого не записується. Щоб прибрати вже створений цикл,
відновіть БД з резервної копії кроку 1 (backend зупинено; відновлення лише в новий файл):

```
sc.exe stop integrity-v2-backend
Rename-Item C:\srv\integrity-v2\data\integrity_v2.db integrity_v2.db.manual-<час>
& 'C:\Program Files\Python313\python.exe' -I -B C:\srv\integrity-v2\pkg\ops-backup\v2_db_tool.py restore `
    C:\srv\integrity-v2\backups\pre-demo-<час>.db C:\srv\integrity-v2\data\integrity_v2.db `
    --expect-version 6 --kind integrity --sha256 <SHA256 з кроку 1> --strict
sc.exe start integrity-v2-backend
```

Перевірте права на відновлений файл (як у `installer/windows-v2/docs/UPGRADE_IN_PLACE.md`, розділ 6). Зміни,
внесені в БД після кроку 1 (не лише демо-цикл), при відновленні теж зникнуть.
