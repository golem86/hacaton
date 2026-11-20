# Questionnaire prototype compatibility with SQLite schema 3

**Status: review proposal; no production changes.** This review examines release branch `feature/assessment-manager-release-v2` at `db70706f14cbcaba0d137151572aa996b106cd18` and the current test-only questionnaire prototype. It does not certify a production migration. The prototype uses its own SQLite file and is not registered in `backend/app/main.py`.

## Evidence from the release candidate

- `backend/app/migrations.py` declares `SCHEMA_VERSION = 3`. Schema 3 includes the `units` lookup, `response_sets.unit` foreign key, uniqueness of `(response_set_id, question_id)` in numeric `answers`, and `audit_events`.
- The schema 3 numeric response model stores `response_sets` and integer `answers.value`. `ResponseSet.respondent_category` has the existing `mgmt/npp/cadets/staff/expert` comment; this does not create a distinct permission model for expert assessments.
- Access codes are in `access_tokens` and their category/expiry policy in `access_token_policies`. The current release has atomic code use with numeric submission and privacy suppression rules. Official descriptive responses must not reuse numeric `answers` or infer numeric values from option order.
- In release mode `check_schema()` refuses an old or incomplete `INTEGRITY_DB` without modifying it. Explicit migration requires `--apply --confirm-verified-backup`; tests confirm that schema checks do not alter an old DB.
- `migrate()` handles older response schema and adds current metadata tables. A schema 2 database with existing core constraints follows the add-only path; it is backed up when file-backed, `create_all` adds missing tables, and the version is set to 3. Existing schema 3 cycles and numeric responses are not being rewritten for this prototype.
- Existing migration tests cover backup, preservation of row counts, FK/integrity checks, idempotence, and release refusal. The WIP prototype tests use `.prototype.sqlite`; they assert production `app.main` has no `/prototype/*` route.

## Compatibility conclusion

The isolated prototype is compatible with the release candidate because it has its own app factory, database filename guard, tables, route namespace and ID fixture. It does not use `INTEGRITY_DB`, `Base.metadata` from production, numeric answer tables, production access tokens, Dashboard queries or Analytics. No production cycle can yet select an official template; no official response is visible in the production application.

This proves isolation in the current code, not compatibility of a future integrated schema. Adding these tables to `INTEGRITY_DB` would change the production schema and migration contract and remains blocked pending №5 technical approval.

## Suggested future DDL boundary (not implemented)

Keep the numeric entities and their constraints unchanged. Add a separately versioned migration only after schema 3. The following is a table plan, not executable or approved DDL:

| Entity | Proposed keys and constraints | Separation rule |
| --- | --- | --- |
| `questionnaire_templates` | `(template_id, version)` primary key; immutable content hash, status, audience/source metadata | Does not rewrite `questions` used by numeric `demo-v1` |
| `questionnaire_questions` | Composite key `(template_id, version, question_id)`; kind, required, section, order, source page/number | Descriptive text is not an Integrity Index score |
| `questionnaire_options` | Composite key `(template_id, version, question_id, option_id)` and FK to its question; order and text only | No score/weight columns |
| `cycle_questionnaires` | FK to current cycle and exact template/version; frozen at cycle activation | Nullable/new relation only; existing cycles keep their existing behavior |
| `official_response_sets` | Random internal key; `cycle_id`, template/version, approved category; no person, token, IP or exact response timestamp | Separate from numeric `response_sets`; do not expose internal key |
| `official_answers` | FK to official set; `question_id`, `option_id`; unique `(response_set_id, question_id)` and composite FK to the exact option/version | Never join to numeric `answers` or scoring |
| `expert_permissions` / `expert_assignments` | Explicit server-managed grant and active assignment bound to cycle/template/version | Not derived from `respondent_category` or `X-Role` |
| `expert_assessments` / `expert_answers` | Separate lifecycle/revision store; immutable after finalization; references only expert assignments and immutable template IDs | No FK/join to anonymous response sets or numeric answers |

**Important:** Do not add an FK from access-code rows to a response set. Consume a code and create the anonymous response in one transaction, but store no code digest, token ID or link on the answer side. The access-code store itself must not have a `response_set_id` field. Define how cycle category and k-suppression interact before schema design.

## Suggested production migration sequence

1. №5 approves final methodology/audience, DDL, routes, retention and suppression policy. Freeze the official catalog version and compute a stable content hash. No retroactive edits to template versions.
2. Design a new migration version after 3. Preserve all existing tables, columns, constraints, IDs and row values. Add nullable/independent relations first; do not require old cycles to have an official template.
3. Test on a synthetic copy of schema 3: create and verify SQLite backup; capture counts and stable hashes for existing cycle/config/token/numeric-response/answer/audit rows; apply migration; run `foreign_key_check`, `integrity_check`, uniqueness and schema-version checks; run twice to prove idempotence.
4. Verify compatibility with old and new code: schema 3 with new code must remain refused or explicitly supported without writes; new schema with previous code must fail safely if unsupported. Verify startup does not silently migrate in release mode.
5. Test rollback/restore from backup and failure during each migration phase. SQLite DDL transactional behavior and filesystem backup restore must be exercised on the supported Windows deployment path as well as CI.
6. Only after review, ship a separately versioned migration/deployment step and then enable API/UI by feature gate. Never retrofit the existing `SCHEMA_VERSION=3` migration in place.

Do not promise a destructive down migration. For rollback, stop writes, restore the verified pre-migration backup under the operational runbook, and reconcile any official submissions accepted after the backup according to an approved recovery procedure. Until an operational recovery path is approved, disable official writes before restore.

## Backward compatibility and isolation tests to require

- Schema 3 existing cycles still list, open, close and submit numeric questionnaires with unchanged payloads and results.
- Numeric answer constraints, scoring outputs and `demo-v1` fixtures remain unchanged before/after migration.
- Existing `cycle_configs`, access tokens/policies, units and audit rows preserve identity and contents.
- Official-only cycle has an explicit template/version; old cycles do not acquire an implicit questionnaire.
- Official answers reject foreign template/version/question/option IDs and duplicates; no free text unless separately approved.
- Anonymous response schema has no user/actor/token/IP/precise-timestamp/foreign respondent identifier and no recoverable code-answer join.
- Expert permissions and assignment ownership are checked for each request; 2FA, CSRF, Origin, revoke, revision conflicts and finalize are tested without `X-Role` fallback.
- Suppression tests cover small and differencing groups across categories, units, cycles, time slices and combined numeric/official totals.
- Failure/retry/concurrent-submit/close tests prove atomic code consumption, no accepted submission after close, and no duplicate response.
- Retention and deletion tests prove official and expert stores are independently purged according to approved policy, with audit retention defined separately.
- Migration backup, row preservation, integrity/FK checks, idempotence, rollback and supported Windows clean install are tested on synthetic schema 3 copies. No production database is used in these tests.

## Decision needed from №5

Approve or revise: the new versioned schema and migration boundary; whether official forms attach to a cycle and category; how one-time codes are scoped when respondent categories overlap; suppression and retention policy; expert grants, assignments and reviewer/reopen lifecycle; integration rollout and Windows recovery. Until then, keep all prototype tables and routes out of production schema 3 and production `app.main`.
