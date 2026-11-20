# Анкети й експертне оцінювання — методика та ізольований backend-прототип

**Гілка:** `feature/assessment-questionnaire-v2`, [Draft PR #25](https://github.com/golem86/hacaton/pull/25). **Статус:** prototype-only / DO NOT MERGE. Production `app.main`, SQLite schema 3, auth, Assessment Manager, Integrity Index, Dashboard і numeric `demo-v1` не змінювалися. Прототип запускається тільки окремою фабрикою тестового застосунку; production routes не зареєстровано.

## 1. Методична перевірка

[Таблиця відповідності](docs/OFFICIAL_QUESTIONNAIRE_METHOD_MAPPING.md) охоплює всі 22 питання Додатка В: 12 у формі 1, 10 у формі 2, по чотири розділи. Спосіб відповіді залишається `single_choice`: 20 питань мають 5 варіантів, два питання про викривачів — 6. Каталог `2.0.0` не змінено. Його стислі адаптації зберігають теми й порядок варіантів, але **не є методично затвердженою еквівалентною анкетою**. Потребують рішення №5: дубль питань 4/5 про відкритість у формі 1; опущена в адаптації позначка `0%` у першому варіанті питання про викривачів форми 1; суттєве стиснення складених описів п’яти рівнів зрілості; загальна придатність скорочених критеріїв. Нову версію не створювали без редакційного рішення.

[Огляд аудиторії](docs/QUESTIONNAIRE_AUDIENCE_REVIEW.md): найбільш обґрунтоване прочитання документа — Анкета 1 для членів робочої групи, Анкета 2 для постійного й змінного особового складу. Заголовок Анкети 2 на с. 60 цьому суперечить, тому статус `ambiguous` збережено. Коди `mgmt/npp/cadets/staff` не доводять членство в робочій групі й не дають однозначного зіставлення з двома аудиторіями. Автоматичного призначення немає; експерт — окремий процес.

## 2. Прототип анонімних описових відповідей

`backend/prototypes/official_expert.py` створює **лише за явним викликом у тестах** окрему БД з обов’язковим суфіксом `.prototype.sqlite`. Таблиці `official_response_sets` і `official_answers` не мають FK до користувача/особи або зв’язку з access token. У тестовій таблиці кодів зберігається HMAC digest; немає `response_set_id`. Відповідь складається лише з дозволених `question_id`/`option_id`, прив’язки до cycle/template/version і категорії. Вільного тексту, score/weight, точного часу відповіді, IP, email або respondent ID немає.

`POST /prototype/official/submissions` доступний **лише в окремому test app**, приймає code-only запит без cookie/Authorization. Застосовуються обмеження довжини, `extra='forbid'`, точна версія шаблону й циклу, повнота, унікальність питань, належність опції питанню, категорія, строк коду та стан циклу. `BEGIN IMMEDIATE` серіалізує close/submit і два submit; відповідь, усі опції й використання коду фіксуються однією транзакцією. Успіх повертає тільки `{"accepted": true}` без ID. Невалідні запити не відлунюють токен чи тіло. Жодного endpoint для сирих відповідей або управлінського Dashboard немає.

Обмеження: каталог ID у Python — окрема prototype fixture, а не затверджений спільний реєстр; правила видачі кодів, rate limiting, retention, suppression, production logging і точний контракт з циклом потребують №5. Цей API не є інтегрованим поданням з `/app/official`.

## 3. Прототип експертних прав та API

Окремі `expert_permissions`, `expert_assignments`, `expert_assessments`, `expert_answers`, `expert_audit_events`. Серверний fixture видає opaque session із expiry, ознакою завершеної 2FA та CSRF; роль і призначення беруться з тестового серверного стану/БД. `X-Role` не надає прав. Експерт бачить лише власну призначену оцінку. Мутації перевіряють Origin/Referer та CSRF. `GET /prototype/expert/assessments/{id}`, `PUT .../{id}/answers` і `POST .../{id}/finalize` працюють тільки в test app. Draft дозволяє часткові валідні відповіді з revision; finalize вимагає повноти, після чого оцінка незмінна. Зміни й audit — одна транзакція, без option ID або відповіді в audit.

[Контракт і негативні сценарії](docs/EXPERT_ROLE_API_CONTRACT.md) розрізняють фактичну тестову підмножину й цільову модель. Не реалізовано production роль, авторизацію браузерного UI як експерта, persistent sessions/cookie policy, lifecycle призначень, reviewer, production audit або інтеграцію з Analytics. Expert answers не мають FK/join до анонімних відповідей.

## 4. Перевірки

| Перевірка | Результат |
| --- | --- |
| Ізольовані prototype tests | **23 passed**: невідомі/чужі ID, версії, неповнота, дублікати, replay/expiry, close/submit, конкурентні update, анонімність, чужі оцінки, role spoofing, 2FA, CSRF/Origin, finalize, audit |
| Повний backend pytest | **384 passed**, 1 зовнішнє deprecation warning |
| Frontend tests | **44 passed** |
| TypeScript і production build | **PASS** |
| Повний browser E2E | **12 passed** на тимчасових синтетичних БД |
| `git diff --check` | **PASS**, включно з усіма новими staged-файлами |
| Production official/expert API й scoring | **BLOCKED / NOT RUN**, контракт не затверджений |

## 5. Файли й передача

Нові: `backend/prototypes/__init__.py`, `backend/prototypes/official_expert.py`, `backend/tests/test_official_expert_prototype.py`, `docs/OFFICIAL_QUESTIONNAIRE_METHOD_MAPPING.md`, `docs/QUESTIONNAIRE_AUDIENCE_REVIEW.md`, `docs/EXPERT_ROLE_API_CONTRACT.md`, цей звіт. Готові до **технічного рев’ю** методична таблиця, test-only моделі, API handlers та негативні/конкурентні тести. Вони не готові до production інтеграції.

№5 має затвердити методичну редакцію й аудиторію, єдиний версіонований серверний каталог, production DDL/API й міграцію, політику кодів/анонімності/suppression/retention, експертні grants/assignments, сесії/2FA/CSRF/audit, lifecycle та окремо scoring. Commit реалізації: `b290a6be838a29647604990c8adfd0f0139a6823`. Після push перевірено: Draft PR #25 містить 17 WIP-файлів, без production `backend/app`, CI, schema 3 чи Assessment Manager; head PR #24 залишився `db70706f14cbcaba0d137151572aa996b106cd18`. Merge не виконувати.
