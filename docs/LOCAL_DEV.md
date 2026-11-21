# Запуск для розробки без Docker і перевірки

Основний спосіб запуску — Docker, розділ «Як запустити» в [README](../README.md). Тут описано запуск backend і frontend окремо, для розробки.

## Вимоги

Node.js 22 або новіший з npm та Python 3.11 або новіший. Команди виконуються в PowerShell з кореня репозиторію.

## Backend

У першому вікні:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Перевірка доступності API — `http://127.0.0.1:8000/api/health`. Схема API (`/docs`, `/openapi.json`) доступна лише адміністратору V2 після входу з 2FA ([API_CONTRACT.md](API_CONTRACT.md), розділ «Документація API (Swagger)»).

## Frontend

У другому вікні, з прямим підключенням до backend:

```powershell
cd frontend
npm install
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev
```

Відкрийте `http://127.0.0.1:5173`. Якщо PowerShell блокує `npm.ps1`, використайте `npm.cmd` без зміни політики виконання Windows.

Для backend на іншому порту, наприклад `8001`, змініть лише значення змінної:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8001"
```

Альтернатива — Vite proxy. У цьому режимі Dashboard звертається до відносних `/api` маршрутів, а proxy пересилає їх на backend:

```powershell
cd frontend
$env:VITE_API_BASE_URL = ""
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:8001"
npm run dev
```

`VITE_API_BASE_URL` має пріоритет над proxy. Після зміни змінних перезапустіть Vite.

Секрети, паролі й реальні файли `.env` не публікуються. Змінні середовища перелічено в `.env.example`.

## Аналітика на синтетичних даних

Методика `team-results-demo-0.1` — авторська пропозиція зі статусом `approval_status=proposed`, а не офіційна або затверджена оцінка ([methodology.md](methodology.md)).

Для локального показу:
1. Задайте `INTEGRITY_DB` як шлях до **окремої нової синтетичної SQLite-БД**.
2. Створіть її командою `python -m app.seed` з каталогу `backend`.
3. Встановіть `INTEGRITY_ANALYTICS_DEMO=1` перед запуском backend.

Прапорець лише вмикає обчислювальні маршрути й не перевіряє походження записів. Не використовуйте спільну або робочу БД. Без прапорця обчислювальні маршрути повертають `503`. Деталі — у [сценарії показу](ANALYTICS_DEMO.md). У Docker-стеку прапорець уже ввімкнено.

## Перевірки

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
cd ..\frontend
npm run test
npm run build
cd ..
git diff --check
```

Ті самі перевірки автоматично виконує GitHub Actions ([`.github/workflows/v2-ci.yml`](../.github/workflows/v2-ci.yml)):
- backend — Python 3.13.14 на Windows, повний pytest з контролем кількості тестів;
- frontend — pnpm `--frozen-lockfile`, тести, TypeScript і production build;
- `git diff --check` і перевірка, що в Git немає БД і секретів.

Збірка frontend зберігається як артефакт на 14 днів. CI нічого не розгортає і не підключається до сервера.
