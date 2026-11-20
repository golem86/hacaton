# Production DDL/API proposal: official questionnaires

**Статус: для рішення №5; не реалізовано.** Поточний isolated prototype лишається у `backend/prototypes/`. Ця пропозиція потребує окремого технічного затвердження, security review і плану deployment. Вона не змінює SQLite schema 3, поточні routes, response tables, авторизацію чи scoring.

## Цілі та сумісність

- Numeric `demo-v1` і працюючі Assessment Manager цикли залишаються незмінними.
- Офіційний шаблон закріплюється за циклом у `draft`, до активації; активна прив’язка незмінна.
- Відповіді — лише дозволені `single_choice` option ID. `0%` є частиною опису варіанта, не балом.
- Немає respondent ID, access-token ID, email, IP чи точного часу в таблицях відповідей.
- Expert data має інші таблиці/namespace і не має FK до анонімних відповідей.
- Нові DDL додаються окремою міграцією **після** затвердження й baseline schema 3. Існуючі таблиці та історичні записи не перейменовувати й не переписувати.

## Схема даних для обговорення

Нижче наведені поля й обмеження — логічний контракт, не готовий deployment SQL. Для SQLite варто використовувати `STRICT` таблиці лише після перевірки мінімальної версії SQLite у всіх підтримуваних інсталяціях.

```sql
CREATE TABLE questionnaire_templates (
  template_id TEXT NOT NULL CHECK (length(template_id) BETWEEN 1 AND 64),
  version TEXT NOT NULL CHECK (length(version) BETWEEN 1 AND 32),
  form_number INTEGER NOT NULL CHECK (form_number IN (1, 2)),
  audience_code TEXT NOT NULL CHECK (length(audience_code) BETWEEN 1 AND 32),
  source_uri TEXT NOT NULL CHECK (length(source_uri) <= 512),
  source_appendix TEXT NOT NULL CHECK (source_appendix = 'В'),
  status TEXT NOT NULL CHECK (status IN ('draft','published','retired')),
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
  created_at TEXT NOT NULL,
  PRIMARY KEY (template_id, version)
);

CREATE TABLE questionnaire_questions (
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  question_id TEXT NOT NULL CHECK (length(question_id) BETWEEN 1 AND 64),
  section_id TEXT NOT NULL CHECK (length(section_id) BETWEEN 1 AND 64),
  question_number INTEGER NOT NULL CHECK (question_number > 0),
  printed_page INTEGER NOT NULL CHECK (printed_page BETWEEN 53 AND 66),
  display_order INTEGER NOT NULL CHECK (display_order > 0),
  kind TEXT NOT NULL CHECK (kind = 'single_choice'),
  required INTEGER NOT NULL CHECK (required IN (0,1)),
  wording_status TEXT NOT NULL CHECK (wording_status IN ('adapted','verbatim')),
  source_duplicate INTEGER NOT NULL DEFAULT 0 CHECK (source_duplicate IN (0,1)),
  prompt TEXT NOT NULL CHECK (length(prompt) BETWEEN 1 AND 4000),
  PRIMARY KEY (template_id, version, question_id),
  UNIQUE (template_id, version, display_order),
  FOREIGN KEY (template_id, version) REFERENCES questionnaire_templates(template_id, version)
);

CREATE TABLE questionnaire_options (
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  question_id TEXT NOT NULL,
  option_id TEXT NOT NULL CHECK (length(option_id) BETWEEN 1 AND 64),
  display_order INTEGER NOT NULL CHECK (display_order > 0),
  label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 5000),
  PRIMARY KEY (template_id, version, question_id, option_id),
  UNIQUE (template_id, version, question_id, display_order),
  FOREIGN KEY (template_id, version, question_id)
    REFERENCES questionnaire_questions(template_id, version, question_id)
);

CREATE TABLE cycle_questionnaires (
  cycle_id INTEGER NOT NULL REFERENCES assessments(id),
  mode TEXT NOT NULL CHECK (mode = 'official_self'),
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  PRIMARY KEY (cycle_id, mode),
  UNIQUE (cycle_id, mode, template_id, version),
  FOREIGN KEY (template_id, version) REFERENCES questionnaire_templates(template_id, version)
);

CREATE TABLE official_response_sets (
  response_set_id TEXT PRIMARY KEY CHECK (length(response_set_id) = 32),
  cycle_id INTEGER NOT NULL REFERENCES assessments(id),
  mode TEXT NOT NULL DEFAULT 'official_self' CHECK (mode = 'official_self'),
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  category_code TEXT NOT NULL CHECK (length(category_code) BETWEEN 1 AND 32),
  unit_code TEXT CHECK (unit_code IS NULL OR length(unit_code) BETWEEN 1 AND 64),
  UNIQUE (response_set_id, template_id, version),
  FOREIGN KEY (cycle_id, mode, template_id, version)
    REFERENCES cycle_questionnaires(cycle_id, mode, template_id, version),
  FOREIGN KEY (template_id, version)
    REFERENCES questionnaire_templates(template_id, version)
);

CREATE TABLE official_answers (
  response_set_id TEXT NOT NULL REFERENCES official_response_sets(response_set_id) ON DELETE CASCADE,
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  question_id TEXT NOT NULL,
  option_id TEXT NOT NULL,
  PRIMARY KEY (response_set_id, question_id),
  FOREIGN KEY (response_set_id, template_id, version)
    REFERENCES official_response_sets(response_set_id, template_id, version),
  FOREIGN KEY (template_id, version, question_id, option_id)
    REFERENCES questionnaire_options(template_id, version, question_id, option_id)
);
```

**DDL blockers:** Existing `assessments` table name and key must be verified against the approved schema-3 commit before writing runnable migration SQL. Category/unit references need a decision: strict FK to approved lookup tables or a frozen allowlist at validation. Published templates and their child rows must be immutable by application rule and/or triggers. A correction creates a new version and content hash.

The anonymous response tables deliberately have **no** `respondent_id`, `user_id`, `token_id`, email, IP, precise timestamp, browser identifier or foreign key to an access-code row. If duplicate submission protection needs an idempotency value, decide separately whether a one-way request key can be stored without linking it to the issued token; the current recommendation is single-use code state plus atomic insert and generic refusal on replay.

## API proposal

| Method and route | Access | Behavior |
| --- | --- | --- |
| `GET /api/questionnaire-templates/{template_id}/versions/{version}` | Public, published versions only | Return immutable catalog IDs, adapted wording, source metadata and options. No scores. |
| `GET /api/assessments/{cycle_id}/official-questionnaire` | Public only for an open cycle | Return the exact version assigned before activation; no inferred audience routing. |
| `POST /api/assessments/{cycle_id}/official-submissions` | Anonymous, no cookie or Authorization header | Accept `{template_id, version, category_code, unit_code?, code, answers:[{question_id,option_id}]}`. Validate cycle open, bound version, audience/category policy, expiry, unused code, unique complete question set and option membership. Return `201 {"accepted":true}` only. Never return response-set ID. |
| `GET /api/assessments/{cycle_id}/participation` | Admin session + 2FA + CSRF | Aggregate only after approved suppression; do not return mutually derivable `issued - unused` or live small-group breakdowns. |

Every mutation uses bounded Pydantic/schema inputs with `extra=forbid`, rejects free text, and uses uniform errors that never echo submitted values. Submission performs a single `BEGIN IMMEDIATE`: re-read cycle state and code state; insert response set and all answers; mark code used; commit. Any exception rolls back all three. `close` uses the same SQLite write lock, so after `close` returns no new accepted submission can commit. The route rejects credentials/cookies and must not log request bodies, code, option IDs, Origin values, or raw errors.

No `expert` route is part of this proposal. Expert endpoints, grants, assignments and storage are described separately in [`EXPERT_ROLE_API_CONTRACT.md`](EXPERT_ROLE_API_CONTRACT.md) and must use a separately approved role/session design.

## Compatibility and migration outline

1. Confirm exact schema-3 table/column/index definitions and supported SQLite versions from the release commit; do not infer the `assessments` FK from application model names.
2. Approve DDL, category mapping, audience, suppression/retention, and API response/error contract.
3. Add a new migration version after schema 3. Create only new questionnaire tables and indexes; do not alter legacy numeric response tables or their constraints.
4. Validate on a synthetic copy: pre/post table counts and checksums for existing data, FK/UNIQUE/quick checks, repeated migration, injected failure rollback, backup restoration, and startup from schema 2 and 3.
5. Deploy code that can read schema 3 without official tables; enable the new cycle mode only after migration verification. Keep `demo-v1` routing unchanged.
6. Production migration is out of scope until separately approved; never run it from this WIP.

## Required tests before integration

- Published version immutability and content hash; form 1/2 counts, source pages, duplicate marker, 6-choice whistleblower item and full maturity text.
- API rejects unknown/mixed versions, foreign options, duplicates, incomplete forms, arbitrary text, oversized data, wrong category, expired/replayed code, closed cycle and any cookie/auth identity.
- Concurrent same-code submission and close/submit are serialized; failure midway leaves no answer, response set or used code.
- DB/schema inspection proves no respondent/token link; query/log tests prove no raw code, IP, exact timestamp or answer in access logs.
- Suppression tests cover primary and complementary cells and difference queries across endpoints, cycles and time windows.
- Retention purge removes response sets and answers transactionally and accounts for WAL/backup copies.
- Full existing schema-3, Assessment Manager, numeric API, Analytics and Dashboard suites pass without new official data fields.
