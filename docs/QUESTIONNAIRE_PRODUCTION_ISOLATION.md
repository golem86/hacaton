# Production isolation review

**Result: runtime path isolation verified for the prototype; no production integration or migration.** Review performed on the WIP tree after adding path guards.

## Verified boundaries

- The only integration prototype is `backend/prototypes/questionnaire_integration.py`; its factory `create_integration_test_app()` is not imported or mounted by `backend/app/main.py` or production routers.
- Static import search found no production imports of `questionnaire_integration` from `backend/app`, production migrations, seed/startup, Docker, Windows deployment, Analytics, Dashboard, or Integrity Index. Only the test module imports it.
- Its deliberate `Base.metadata` import occurs only inside `create_synthetic_schema3_source()` to create a schema-shaped **temporary synthetic file**. The test prototype does not call production `Base.metadata.create_all()` on an existing production DB.
- `_require_test_temp_path()` requires a resolved path under the OS temporary root, rejects protected/default DB paths and final-component symlinks, and source-copy validation checks schema version, core tables, sentinel synthetic rows, FK and integrity before copying.
- `_require_isolated_auth_db()` fails unless `V2_AUTH_DB` is explicitly configured to an existing temp DB; it rejects the default production path and symlink. `grant_expert()` uses SQLite URI `mode=ro` for identity lookup. The V2 session adapter checks this guard before calling the existing `session_user()` path.
- Regression tests verify missing/default auth configuration returns 503 without changing default DB existence/size/mtime; configured outside-temp/protected paths fail before file creation. No production auth DB was opened for write.
- Changed files are limited to prototype code/tests and questionnaire documents. No release branch, production app/auth/schema, Docker, installer, Analytics, Dashboard or scoring files are in the diff.

## Limits / NOT RUN

- Windows did not permit creating a symbolic link in the test environment; the symlink rejection test is **SKIPPED**, while resolved path/containment checks passed for regular paths. A privileged CI runner should run the symlink case.
- This is defense-in-depth for a test-only module, not a security boundary against a hostile process running with the same OS account. There is a small check/use race if another local process can replace a temporary DB path between validation and open.
- `session_user()` uses the unchanged V2 auth connector after the guard. Production auth changes remain out of scope.
- No production DB, installer candidate, Docker image, or production server was opened or modified.
