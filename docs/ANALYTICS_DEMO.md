# Показ Analytics журі: локальний синтетичний сценарій

Показуйте лише локальний backend з окремою новою синтетичною SQLite-БД. У PowerShell із каталогу `backend` задайте `$env:INTEGRITY_DB` як шлях до нового файла поза спільною БД, виконайте `python -m app.seed`, потім задайте `$env:INTEGRITY_ANALYTICS_DEMO = '1'` і `$env:INTEGRITY_DEMO_XROLE = '1'` (без нього запити з `X-Role` повертають 401; прапорець діє лише в режимі development, який є типовим, і заборонений у release) і запустіть `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`. Seed не запускайте для вже заповненого файла. Прапорець не перевіряє походження даних. Нижче `curl.exe` використовує демонстраційний заголовок `X-Role: manager`; це не автентифікація користувача. Без цього прапорця ті самі дані видно в інтерфейсі: увійдіть адміністратором і відкрийте «Огляд» та «Аналітику».

```powershell
curl.exe -H "X-Role: manager" "http://127.0.0.1:8000/api/index-methodologies/team-results-demo-0.1"
curl.exe -H "X-Role: manager" "http://127.0.0.1:8000/api/assessments/1/index?methodology=team-results-demo-0.1"
curl.exe -H "X-Role: manager" "http://127.0.0.1:8000/api/assessments/1/recommendations?methodology=team-results-demo-0.1"
curl.exe -H "X-Role: manager" "http://127.0.0.1:8000/api/analytics/comparisons?assessment_id=1&comparison_assessment_id=2&methodology=team-results-demo-0.1"
```

У поточному seed цикли 1 і 2 закриті, а цикл 3 відкритий; ID перевірте через `GET /api/assessments`, якщо використовуєте іншу синтетичну БД. Чотири відповіді показують:

| Запит | Що пояснити журі |
| --- | --- |
| Методика | `version`, `weights`, `formula`, `approval_status=proposed`, `synthetic_only=true`, `official=false`, `limitations`. |
| Індекс | `index`, `components`, `by_category`, `coverage`, `audit`, `approval_status=proposed`; `null` і `suppressed` означають, що показувати число не можна. |
| Рекомендації | `proposals`, `objective_context`, `persistence=none; ...`; пропозиції не записуються й потребують рішення людини. |
| Порівняння | `category_comparisons`, `period_comparison`, `change_points`, `warnings`; `status=limited_comparability` не доводить причинного поліпшення. |

Формула: **Integrity Index = Σ(бал компонента × вага компонента)**. Ваги C1–C7 (`0.15, 0.15, 0.15, 0.20, 0.10, 0.15, 0.10`) походять із поточного демонстраційного seed; команда ще має погодити їхній зміст. Це не офіційна методика. Обчислення спирається на агрегати `/results`, уже округлені до 0,1 бала; приховані групи не розкриваються.

У раніше перевіреній конкретній seed-БД цикл 1 дав `index=48.4` і **3 пропозиції** рекомендацій. Це приклад результату саме того набору даних, а не гарантована відповідь будь-якої БД. Поточний запуск може дати інші числа. Для порівняння `assessment_id=1` означає «до», `comparison_assessment_id=2` — «після»; порядок задає запит. Статус `limited_comparability` потрібний, бо історичні версії анкет і склад популяції ще не зафіксовані. Рекомендації мають `status=proposed`, `requires_human_decision=true`; їх прийняття, призначення відповідальних і збереження є окремим майбутнім кроком.

Якщо цикл відкритий, обчислення повертає `409`; без ролі — `401`, без дозволеної ролі — `403`, а без `INTEGRITY_ANALYTICS_DEMO=1` — `503`. [Контракт](API_CONTRACT.md) описує поля й обмеження докладніше.
