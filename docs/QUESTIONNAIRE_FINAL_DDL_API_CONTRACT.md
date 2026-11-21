# Proposed final DDL/API contract: official questionnaires and expert assessments

> **Історичний робочий документ команди (стан на 20.11.2026).** Чинний стан продукту — [README](../README.md), [API_CONTRACT.md](API_CONTRACT.md) і [integration-map.md](integration-map.md).

**Status: PROPOSAL — requires approval from #5 and the auth/data owners. Nothing in this document is a production migration or API implementation.**

## Verified schema-3 baseline

At release commit `db70706f14cbcaba0d137151572aa996b106cd18`, the cycle table is `cycles` with `id INTEGER PRIMARY KEY`; no `assessments` table exists. `cycle_configs.cycle_id` is PK/FK to `cycles.id`; `cycle_configs.questionnaire_version` defaults to `demo-v1`. Numeric `response_sets.id` and `answers.id` are integer PKs; `response_sets.cycle_id → cycles.id`, `answers.response_set_id → response_sets.id`, `answers.question_id → questions.id`, and `(response_set_id, question_id)` is unique. `access_tokens` has `(id, cycle_id, token, used)` with unique plaintext token; `access_token_policies.token_id` is PK/FK to `access_tokens.id`. `audit_events.assessment_id → cycles.id`.

## Coexistence without changing `demo-v1` semantics

Keep every existing `cycle_configs.questionnaire_version` value and its meaning unchanged: it selects the legacy numeric questionnaire contract. Add a separate `cycle_questionnaires` binding, one row per cycle, with `cycle_id REFERENCES cycles(id)`, `mode='official_self'`, `template_id`, and immutable `version`. Absence of a binding means the cycle remains on legacy numeric `demo-v1`; a binding means official descriptive self-assessment is the selected questionnaire mode. After approval, route guards must reject use of the numeric submission endpoint for an officially bound cycle and reject the official endpoint for a cycle without the binding. Existing cycles and API clients therefore continue unchanged. Never infer audience or mode from the category or browser payload.

## Logical table contract

All tables are additive and use a new migration **after** schema 3. Exact SQL, indexes, SQLite minimum version and migration number require approval.

| Table | Primary/foreign keys and constraints | Data boundary |
| --- | --- | --- |
| `questionnaire_templates` | PK `(template_id,version)`; form number check; published/draft state; source metadata and content hash | Published content immutable; corrections create a new version |
| `questionnaire_questions` | PK `(template_id,version,question_id)`; unique display order; FK to template; fixed `single_choice` kind; page/question/source metadata; `source_duplicate` | No scoring/weights |
| `questionnaire_options` | PK `(template_id,version,question_id,option_id)`; unique option order; FK to question | Descriptive option text, including source marker `0%`, never inferred numeric value |
| `cycle_questionnaires` | PK `cycle_id`; FK `cycle_id → cycles(id)` and `(template_id,version) → questionnaire_templates`; mode fixed `official_self` | Bound in draft, frozen after activation |
| `official_response_sets` | Random non-client-facing PK; FK `(cycle_id,template_id,version) → cycle_questionnaires`; category constrained to approved code | No respondent/user/token ID, IP, device ID or answer timestamp; category may still expose a small group |
| `official_answers` | PK `(response_set_id,question_id)`; FK to response set and exact template question option | Separate from numeric `answers`; no score/weight |
| `expert_permissions` | Principal key to V2 user ID by application contract; explicit enabled/granted/revoked state | Separate expert authorization store |
| `expert_assignments` | Random PK; FK to grant and exact `(cycle,template,version)`; active/revoked state | One assessment scope per assignment; no blanket “expert sees all” |
| `expert_assessments` | PK; unique FK assignment/principal; `draft/finalized`, monotonic revision | Separate from anonymous responses |
| `expert_answers` | PK `(assessment_id,question_id)`; FK to exact option | No linkage to official anonymous response set |
| `expert_audit_events` | Event PK; action allowlist; actor, target/assignment references, event timestamp | No answer values, codes, cookies, or free-text payload |

The current prototype's DDL in `backend/prototypes/questionnaire_integration.py` is executable only on a synthetic guarded copy. It intentionally differs from a production-ready proposal where the latter needs policy choices; do not copy it directly into a production migration.

## Proposed API

- `GET /api/questionnaire-templates/{id}/versions/{version}` — published immutable template only; source references and descriptive options; no score fields.
- `GET /api/assessments/{cycle_id}/official-questionnaire` — public only for open officially bound cycle; returns one exact version; no automatic audience routing.
- `POST /api/assessments/{cycle_id}/official-submissions` — anonymous, no Cookie/Authorization; body contains template/version/category/code and exact question/option IDs. Validate completeness, cycle mode/open state, category policy, expiry and one-time state. Response is generic `{accepted:true}`; never return response ID.
- Expert APIs are separately authenticated, require V2 session + 2FA + CSRF/Origin on mutations, explicit grant and active assignment on every request. Scope every query by principal and assignment. Use expected revision and one-time finalization.
- No raw official response or official aggregate/dashboard endpoint until suppression and access policy are approved.

## Rate-limit design proposal

The current synthetic proof of concept uses two fixed-window keys only: `global` and `cycle:{cycle_id}`. It atomically reads/increments both counters under `BEGIN IMMEDIATE`, deletes expired buckets, stores no IP/user/device/code, returns generic 429 at a configured limit, and returns generic 503 if the counter store fails. Concurrent worker instances on one local SQLite file are tested. This is appropriate only as a low-volume single-host closed-contour candidate; writer locks/latency and filesystem lock semantics must be load-tested. Never silently fall back to per-process counters if the shared store is unavailable.

For multiple hosts, use an already-approved shared in-contour service if one exists; an atomic Redis-compatible script with TTL and ACLs is one possible option but adds deployment, monitoring, backup, network and secret-management dependencies. Do not add a new service without #5/operations approval. Fail closed with 503 on infrastructure failure, 429 on an actual quota denial, and expose only a coarse retry time. One-time code consumption remains separately atomic and is not replaced by rate limiting.

The existing schema-3 `access_tokens.token` is plaintext. This contract does not authorize changing it. If a future design uses HMAC digests or a separate credential table, review migration, key custody, expiry, replay and transaction-correlation risks separately. The present same-file atomic submission protects correctness but does not hide write-set correlation from a privileged DB/WAL observer.

## Migration and rollback sequence

1. Confirm approved release SHA, schema version and SQLite runtime; back up the database and verify the backup opens and passes `integrity_check`.
2. On a synthetic copy, apply additive DDL in one transaction. Preserve `PRAGMA user_version=3` until a separately approved migration increments the production schema version.
3. Run `foreign_key_check`, `integrity_check`, table/count/hash comparisons, unique/check failures, `demo-v1` API regression, and old-cycle lifecycle tests.
4. Repeat migration; expect a verified idempotent no-op. Inject failures after each DDL phase; require rollback and successful restore from the verified backup.
5. Test startup with schema 3 and no questionnaire tables; legacy routes must continue to serve old cycles. No production startup should auto-run prototype DDL.
6. Rollback only by restoring the verified pre-migration backup in an approved maintenance window. Do not delete questionnaire tables ad hoc after data collection begins.
7. Run only after #5 approves DDL, API, audience/category mapping, suppression, retention, deployment and restore plan. No production migration was performed by this WIP.

## Decisions needed

Template audience for Form 2, category/unit vocabulary, whether unit is stored, one mode per cycle, `k` and query disclosure policy, retention/backup schedules, whether plaintext shared access tokens are acceptable for this threat model, and expert grant authority all remain open.
