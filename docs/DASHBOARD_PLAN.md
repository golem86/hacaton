# Executive Dashboard (№3)

> **Історичний робочий документ команди (стан на 16.11.2026).** Чинний стан продукту — [README](../README.md), [API_CONTRACT.md](API_CONTRACT.md) і [integration-map.md](integration-map.md).

Dashboard працює в окремому worktree `codex/dashboard` від `feature/integration`. Контрактом для інтеграції є `docs/API_CONTRACT.md` у `origin/feature/integration` після PR #5.

## Реалізовано

| Частина | Файли | Джерело |
| --- | --- | --- |
| Вибір і стан циклу | `frontend/src/main.tsx`, `frontend/src/api/assessments.ts` | `GET /api/assessments`, `GET /api/assessments/{id}` |
| KPI з дозволених агрегатів | `frontend/src/dashboard/DashboardSummary.tsx` | `responses_total`, `components`, `categories` з `/results` |
| Бали C1–C7 | `frontend/src/dashboard/ComponentScores.tsx` | `components[].score` |
| Порівняння категорій | `frontend/src/dashboard/CategoryComparison.tsx` | `categories`, `components[].by_category` |
| Об’єктивні показники | `frontend/src/dashboard/ObjectiveIndicators.tsx` | `components[].objective_indicators` |
| Клієнт результатів і типи | `frontend/src/api/client.ts`, `frontend/src/dashboard/results.ts`, `types.ts` | `GET /api/assessments/{id}/results` |
| Адаптивні стилі | `frontend/src/style.css`, `frontend/src/dashboard/dashboard.css` | Без нових залежностей |

`/results` запитується лише для закритого циклу. `409` і відкритий цикл показують повідомлення про очікування закриття; `401`, `403`, `404` і мережеві помилки мають окремі повідомлення. Запити скасовуються при зміні циклу. Значення з `hidden: true` не відображаються, `null` не стає нулем. Загальний Integrity Index не обчислюється.

Assessment Manager і Dashboard використовують спільний `frontend/src/api/client.ts` для URL, демозаголовка, JSON і HTTP-помилок. Для окремого backend задайте `VITE_API_BASE_URL`; для локального Vite proxy задайте `VITE_API_PROXY_TARGET` і залиште `VITE_API_BASE_URL` порожнім. Без цих змінних запити йдуть на той самий origin. Порти backend у клієнті не закріплені. Frontend-тести: `node --test tests/dashboard.test.mjs` у `frontend`; backend-тести: `python -m pytest` у `backend` (через окрему тимчасову базу з `tests/conftest.py`).

## Очікують API

- Integrity Index — методика й `GET /api/assessments/{id}/index`.
- Recommendations — серверний маршрут рекомендацій.
- Comparative Analytics — `GET /api/analytics/comparisons`.
- Reporting / PDF / XLSX — серверні маршрути звітів та експорту. Локального експорту в Dashboard немає.

Межа №3: backend, контракт API, обчислення Index Engine і логіка анкет не змінюються. Після синхронізації з `feature/integration` перевірено реальний backend на закритих циклах 1 і 2 та відкритому циклі 3, а також інтерфейс у браузері на 375, 768 і 1440 px. Порожній закритий цикл перевірено лише на ізольованому тестовому сценарії.
