# Questionnaire integration: schema-3 compatibility review

> **Update 2026-11-20 — prototype moved to integrity schema 5.** The isolated prototype
> (`backend/prototypes/questionnaire_integration.py`) now targets the current integrity schema 5
> instead of a frozen schema-3 DDL copy. The synthetic source DB is created by `app.migrations.migrate()`
> on an empty file (`PRAGMA user_version=5`, `access_tokens.token_hash`, `audit_events.actor_user_id`,
> `instance_meta('dataset','synthetic')`); a test pins `PROTOTYPE_SCHEMA_VERSION == app.migrations.SCHEMA_VERSION`.
> One-time codes are redeemed by `hash_access_code(code)`; plaintext codes are never stored.
> Selectively ported from draft PR #25: 2.1.0 catalog IDs, the `binding_insert_requires_draft` trigger,
> serialized `bind_cycle`/`activate_cycle`, the E2E-only server `prototypes/official_e2e_server.py`
> and a browser harness that saves both full 2.1.0 forms to the synthetic DB
> (`frontend/e2e/official-integration-harness.*`, excluded from production builds by
> `frontend/scripts/check-production-artifact.mjs`). Still a prototype: production submission of official
> questionnaires and the expert mode need an approved API/DDL; the blockers below remain open
> (read "schema 3" there as "current integrity schema").

**Status: prototype compatible with the inspected schema-3 shape; production integration blocked pending #5 approvals.** Release branch/PR #24 and deployment files are outside this change.

## Verified database facts

The checked-in release schema-3 model uses `cycles` with `id INTEGER PRIMARY KEY`; there is no `assessments` table. `cycle_configs.cycle_id` is a PK/FK to `cycles.id`, and `questionnaire_version` currently defaults to `demo-v1`. Existing numeric `response_sets` refer to `cycles.id`; numeric `answers.response_set_id` refers to `response_sets.id`. One-time code tables are `access_tokens` and `access_token_policies`. `audit_events.assessment_id` refers to `cycles.id`.

The current DDL proposal had two references to `assessments(id)`; these have been corrected to `cycles(id)`. The isolated executable prototype also uses `cycles(id)`, and its separate `cycle_questionnaires` binding does not modify `cycle_configs.questionnaire_version`.

## Test evidence and scope

The test migration is applied only to a new, explicitly marked `.prototype.sqlite` copy generated from SQLAlchemy model metadata and synthetic rows. It preserves `PRAGMA user_version=3`, checks all legacy table snapshots, runs FK/integrity checks, supports safe repeat invocation, backs up before DDL, and can restore a verified synthetic backup. Targeted suite: 25 passed on 2026-11-20.

`app.main`, production auth, schema version, release branch, Windows install candidate, Dashboard, Analytics, and Integrity Index were not modified. Numeric demo-v1 fixture storage is checked for non-mutation; this prototype has no production route or analytics integration.

## Remaining compatibility blockers

1. Decide whether official templates may bind while cycle is draft and how to reconcile that binding with `cycle_configs.questionnaire_version=demo-v1` without changing legacy clients.
2. Approve final table/index DDL, audience/category mapping, optional unit dimension, identifier and time precision, SQLite minimum version, and migration number.
3. Specify safe startup when schema 3 has no questionnaire tables, and rollback/backup policy for the eventual deployment.
4. Validate actual Windows clean-install seed/database artifact and migration order; this test generated a synthetic DB from current models and does not prove installer behavior.
5. Approve `k`, allowed aggregate dimensions, repeated-query protection, retention terms, backup/WAL lifecycle, and purge evidence.

No production migration was executed and no production schema/API change is proposed as ready to merge.
