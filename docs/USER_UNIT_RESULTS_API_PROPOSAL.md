# API proposal: user-scoped unit aggregates

**Статус: реалізовано (20.11.2026).** Чинний контракт — `docs/API_CONTRACT.md`, розділ «Результати підрозділу для користувача V2» (`GET /v2/user/unit-results`). Екран «Результати підрозділу» кабінету V2 замінив заглушку `BLOCKED` і викликає цей маршрут. Нижче — первісна пропозиція й відповіді на її відкриті питання.

## Current gap (до реалізації)

The verified user session does not contain a server-validated unit association. The current user API exposes profile, available personal assessments, the signed-in user's own attempts/history/results/stats, and no organization or unit aggregates. The admin participation endpoint reports aggregate participation only; it does not return C1–C7 results and is not a user endpoint. The UI therefore shows a protected `BLOCKED` state and does not infer unit membership or reuse organization-wide analytics.

Розв'язання: довірене джерело належності — `instance_meta` INTEGRITY_DB, яке заповнює лише власник сервера через консоль (див. відповідь 1).

## Proposed read contract

`GET /v2/user/unit-results?assessment_id={id}`

- Authentication: verified V2 `user` session after 2FA; normal session cookie and request security protections.
- Authorization: the server resolves the user's current/authorized unit from a trusted membership source. The client must not send `unit_id`, unit name, role, or category as an authority input.
- Cycle: only a closed assessment. An open cycle returns a non-data response (suggest `409`).
- Data: aggregate counts and approved C1–C7 component aggregates only. Never return individual responses, answer rows, access tokens, or identifying metadata.
- Privacy: enforce the approved minimum group size `k` server-side for every returned aggregate; apply complementary suppression so totals or overlapping slices cannot reconstruct hidden groups. Repeated/filterable queries must not permit differencing attacks.
- Missing membership, not-found cycle, insufficient sample, and suppressed outputs must use responses that do not disclose another unit's existence or size. Exact status semantics need #5 and #2 approval.
- Response should include assessment `{id,name,status}`, methodology version, privacy status, and each component's `score: number | null` plus explicit status (`available`, `suppressed`, `insufficient_data`). Include a count only when independently safe to disclose.
- No endpoint for cross-unit comparison is proposed in this scope.

Реалізація відповідає цим пунктам. Відмінність: доступ має верифікована сесія V2 після 2FA з будь-якою роллю (`user`, `admin`, `data_officer`), бо підрозділ однаково визначає лише сервер.

## Questions for #5 / #2 — відповіді

1. **Джерело належності.** Таблиця `instance_meta` INTEGRITY_DB, рядок `unit_member:<id користувача V2_AUTH_DB>` → `<units.id>` (модуль `backend/app/unit_membership.py`, без зміни схеми). Призначає й знімає **лише власник сервера** командою `python -m app.v2_unit_cli` або обгорткою `installer\windows-v2\ops\Set-V2UserUnit.ps1`. Ні користувач, ні веб-адміністратор цього не роблять, вебмаршруту немає. Один користувач — один підрозділ.
2. **Поріг k.** `min_group_size` самого циклу (у демо 5). Підрозділи циклу — групи всередині підсумку циклу: діє первинне (< k) і вторинне (сума прихованих — 0 або ≥ k) приховування, як у `participation` (`anonymity.hidden_flags`). Прихований підрозділ → `insufficient_data`, без кількості й балів. Компонент з відповідями менше ніж від k анкет підрозділу (або прихований вторинно серед підрозділів) → `score: null`, `suppressed`. Кількість `respondents` повертається лише при `available` і може бути `null`: якщо разом з адмінською розбивкою `participation?by_unit=true` точна кількість дала б суму прихованих клітинок «категорія × підрозділ» між 0 і k (`0 < залишок < k`), сервер її не віддає. Розрізів за категорією немає; приховані групи адмінських звітів цим маршрутом не відновлюються.
3. **Момент належності.** Діє належність **на момент запиту**, а не на дату закриття циклу. Після перепризначення користувач бачить агрегати нового підрозділу, зокрема за минулі закриті цикли. Агрегат рахується за анкетами циклу з відповідним підрозділом із довідника (`response_sets.unit`); зв'язку між користувачем і його анкетою немає.
4. **Статуси.** `401` — немає верифікованої сесії; `404` — вказаного циклу немає або це чернетка, а роль не `admin` (як у публічних маршрутах); `409` — цикл відкритий (для `admin` — також чернетка); `422` — некоректний `assessment_id`. Інакше `200` зі статусом `available`, `no_unit`, `no_closed_cycle` або `insufficient_data`. Відповідь стосується лише власного підрозділу й не розкриває існування, назв чи розміру інших підрозділів. Відкриті цикли не повертаються, тож порівняння запитів «до/після» неможливе.
5. **Методика.** Бали C1–C7 рахуються тією самою формулою, що й адмінські `/results` (`routes/results.py`), на яких побудована аналітика: середнє відповідей анкети в шкалі 0–100, один знак після коми; версія — у полі `methodology_version` (`services/scoring.VERSION`). Порівнянність циклів — як в адмінській аналітиці (`limited_comparability`, див. `README.md`, розділ «Analytics для синтетичної демонстрації»).

## Acceptance conditions before frontend integration

- Approved API contract and reviewed threat model.
- Backend tests for ownership, role checks, closed-cycle restriction, primary and complementary suppression, and query-differencing resistance.
- Synthetic-data regression evidence with no individual answers in responses or logs.

Контракт зафіксовано в `docs/API_CONTRACT.md`; тести маршруту, CLI і належності — у `backend/tests`. Демо-сценарій на синтетичних даних — `docs/DEMO_DATA.md`, розділ «Демо: результати підрозділу».
