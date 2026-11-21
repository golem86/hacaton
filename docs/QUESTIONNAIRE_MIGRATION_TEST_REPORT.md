# Questionnaire schema-3 prototype migration report

> **Історичний робочий документ команди (стан на 20.11.2026).** Чинний стан продукту — [README](../README.md), [API_CONTRACT.md](API_CONTRACT.md) і [integration-map.md](integration-map.md).

**Status: synthetic-only test prototype; not a production migration.** Run against the current WIP tree on 2026-11-20. The only migration target used by tests is a newly created `.prototype.sqlite` file copied from a synthetic schema-3 source. Production paths and the release branch are guarded out.

## Results

The test fixture creates a SQLite database from the checked-in SQLAlchemy `Base.metadata`, writes `PRAGMA user_version=3`, and seeds synthetic legacy data in `cycles`, numeric `response_sets`/`answers`, access tokens/policies, cycle config, and audit events. It then makes a byte-separated SQLite backup copy, marks a second copy with a test-only guard, and applies isolated questionnaire tables to that copy.

| Check | Result | Evidence |
| --- | --- | --- |
| Synthetic schema 3 source and separate target | PASS | `backend/tests/test_questionnaire_integration_prototype.py::test_schema3_migration_backup_preservation_constraints_and_idempotency` |
| Verified backup before migration | PASS | Same test verifies backup integrity, schema version, and core table hashes |
| Legacy cycle/numeric answer/token/audit preservation | PASS | Same test; numeric answer remains 4 and token unused |
| Questionnaire FK/unique/check constraints | PASS | `test_template_and_answer_constraints_are_enforced`, FK inspection in migration test |
| SQLite integrity and FK checks | PASS | `PRAGMA integrity_check=ok`, no FK violations |
| Repeat migration | PASS | Returns `already_applied` for complete marked migration |
| Interrupted migration at 3 points | PASS | `test_migration_failure_injection_rolls_back_and_backup_restores[ddl_1/after_templates/before_meta]` |
| Restore from verified backup | PASS | `test_restore_removes_prototype_tables_and_preserves_synthetic_legacy_rows` |
| No production DB mutation | PASS (scope guard/test setup) | No production DB path supplied; only pytest temporary files used |
| Schema 2 startup/migration | NOT RUN | This prototype intentionally starts from actual schema 3; schema 2 is not part of this migration |

The prototype adds its own `questionnaire_prototype_meta(version=1)` and deliberately leaves `PRAGMA user_version=3`. Actual schema-3 references use `cycles(id)`; there is no `assessments` table. Numeric tables and the existing `cycle_configs.questionnaire_version` are not modified. The synthetic DB is generated from current model metadata, so this verifies the checked-in model/schema shape, not the Windows installer’s deployed database artifact.

Final Prompt #13 run: full backend **424 passed, 1 skipped, 1 warning** in 83.92 seconds; targeted suite **40 passed, 1 skipped, 1 warning** in 15.37 seconds. The skip is Windows symlink creation denied with WinError 1314; the sole warning is Starlette's httpx/TestClient deprecation. All migration/restore/failure-injection checks passed; no tests were skipped other than the explicit OS-limited symlink case.

## Limits

This is not an approved DDL, production migration, rollback runbook, or proof of recovery from a real backup. Before production, #5 must approve the DDL/API, version reconciliation with `demo-v1`, retention/suppression, SQLite minimum version, backup ownership, and deployment order. No production migration was run.
