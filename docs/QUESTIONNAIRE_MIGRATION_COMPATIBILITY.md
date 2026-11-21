# Questionnaire migration compatibility evidence

> **Історичний робочий документ команди (стан на 20.11.2026).** Чинний стан продукту — [README](../README.md), [API_CONTRACT.md](API_CONTRACT.md) і [integration-map.md](integration-map.md).

**Status: synthetic migration proof only; production integration BLOCKED.**

## Verified release schema

Release commit `db70706f14cbcaba0d137151572aa996b106cd18` has `cycles(id INTEGER PRIMARY KEY)` and no `assessments` table. `cycle_configs.cycle_id` is a PK/FK to `cycles.id`; `questionnaire_version` defaults to `demo-v1`. Numeric tables retain their existing integer IDs/FKs. Access-code tables are `access_tokens` and `access_token_policies`; `audit_events.assessment_id` references `cycles.id`. Two old proposal FKs that said `assessments(id)` were corrected to `cycles(id)`.

## Implemented synthetic verification

`create_synthetic_schema3_source()` uses current SQLAlchemy model metadata to create a temporary schema-shaped file and deterministic synthetic legacy cycle, numeric response, one-time code, and audit row. It verifies integrity/FKs and `user_version=3`. `create_synthetic_schema3_copy()` now requires an OS-temp destination, checks the source's exact expected schema/sentinel rows/integrity in read-only mode before copying, and rejects protected/default DB paths. Migration creates only prototype questionnaire/expert/rate-limit tables, leaves `user_version=3`, snapshots legacy data, uses backup, and has idempotence/failure-injection/restore tests.

**Final evidence:** targeted suite after Prompt #13 changes was **40 passed, 1 skipped, 1 warning**; full backend **424 passed, 1 skipped, 1 warning** in 83.92 seconds. The skip is the Windows symlink-creation test (WinError 1314: symlink privilege unavailable); the warning is Starlette/httpx deprecation. No production DB path was opened for write and no migration was run on production.

## Compatibility decisions and blockers

- Preserve all existing `cycle_configs.questionnaire_version` values/meaning as the legacy numeric `demo-v1` contract.
- Proposed official mode uses an additive one-row-per-cycle `cycle_questionnaires` binding. Absence means legacy behavior; presence selects the official descriptive endpoint. Route gating is not implemented in production.
- Keep official answers in separate tables, and never backfill or rewrite old numeric rows.
- Before release, run the approved migration against a release-SHA synthetic copy and clean-install/seed artifact; verify old cycle lifecycle, token consumption, numeric submission, Dashboard, Analytics, and Integrity Index API outputs.
- Production requires approved DDL/version number, deploy/rollback/backup order, SQLite version support, category mapping, `k`, retention, and recovery runbook.

The migration script is not connected to `backend/app/main.py`, production migration runner, Windows installer or Docker release. It must not be imported into deployment code.
