# Questionnaire integration: schema-3 compatibility review

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
