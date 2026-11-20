# Questionnaire Prototype — Prompt 15 Release Gates

**Scope:** WIP branch `feature/assessment-questionnaire-v2`; PR #25 stays Draft / DO NOT MERGE. PR #24 and production systems are unchanged. This document distinguishes prototype evidence from production gates.

## Gate matrix

| Gate | Status | Evidence / remaining action |
|---|---|---|
| Sync with release CI head | PASS | Release commit `db70706f14cbcaba0d137151572aa996b106cd18` is an ancestor of the WIP branch through a normal merge. |
| Full backend regression | PASS locally with limitation | `428 passed, 1 skipped`, 429 cases; skipped only because this local Windows host denied symlink creation. Strict JUnit gate intentionally fails on any skip. Ubuntu full suite must report all 429 with zero skips; independent Actions run pending. |
| Frontend tests | PASS | 46 passed, zero skipped. |
| TypeScript and production build | PASS | `npm run build` includes `tsc --noEmit` and Vite build. |
| Browser E2E | **PASS locally** | Direct Playwright CLI exit **0**, `13 passed (34.6s)`. JUnit gate: 13 tests, 0 failures, 0 errors, 0 skips. After exit, all three ports (8033, 8034, 5184) were closed. JUnit is at `frontend/test-results/e2e-junit.xml` (ignored local test output, not committed). |
| Independent CI for PR #25 | PENDING | Workflow run `44751073266` on commit `915c667` failed before creating jobs because `runner.temp` was referenced at job-level (GitHub Actions context restriction). Moved the expression into the E2E step environment; `actionlint` passes after the fix. A follow-up push and new Actions run are required before CI can be reported PASS. Workflow is read-only and has no deploy/push steps. |
| Windows symlink security | NOT RUN locally | Local test is skipped by OS privilege. Independent CI has a Windows-only job that turns skip/incomplete JUnit into failure. The Ubuntu backend gate also executes the same symlink attack test; it must not skip. If hosted Windows still denies symlink creation, retain the failed check and request #5 approval for the passing Linux equivalent plus a Windows path/reparse-point test. |
| Production artifact isolation | PASS for source/build boundary; physical image check pending | `frontend/scripts/check-production-artifact.mjs` scans actual `dist` output and packaging config. Docker is unavailable locally. Independent CI builds, exports and scans both production Docker images for the E2E module, route, harness and synthetic codes. No image is pushed or deployed. |
| SQLite schema-3 migration / backup / restore | PASS on synthetic copy | Prior focused checks passed; exact Windows schema-3 release artifact is still required from №5 before claiming installer compatibility. |
| Template immutability and binding race | PASS in isolated regression | Published template/child edits are trigger-rejected. `bind_cycle` uses `BEGIN IMMEDIATE`; an insert trigger rejects non-draft bindings. `activate_cycle` is serialized and requires a binding. Race test asserts no open/unbound state. Production integration needs an approved hook into the Assessment Manager activation transaction. |
| Anonymous response design | NO-GO for production | Test prototype has no respondent/token FK, but plaintext schema-3 codes and response writes share transaction chronology in SQLite/WAL. Logs, backups/restore, ingress timing and colluding DB observers remain threats. No absolute anonymity claim. |
| Suppression / aggregates | BLOCKED | Only synthetic one-shot suppression and in-memory disclosure ledger are present; no aggregate API. `k`, cuts, persistence and retention await approval. |
| Expert lifecycle | BLOCKED for production | Prototype checks grant and assignment each request and keeps expert data separate. V2 Auth still does not revoke old verified sessions on privilege promotion; Auth owner must fix and add fresh-login/2FA tests. |
| Production DDL/API | PROPOSAL ONLY | See [`OFFICIAL_QUESTIONNAIRE_PRODUCTION_INTEGRATION_CONTRACT.md`](OFFICIAL_QUESTIONNAIRE_PRODUCTION_INTEGRATION_CONTRACT.md). Additive migration after schema 3 is proposed, not implemented. |

## Exact V2 Auth regression requested

Use the existing temporary V2 auth DB, a normal user and a completed-2FA session. Simulate an authorized role promotion using the same mechanism the Auth owner will implement; never edit production state. After the role mutation:

1. Every session created before promotion, including verified-2FA sessions, must return 401 on an admin/expert protected endpoint and be absent/revoked in the auth store.
2. A fresh pending session must return 403 for privileged actions until a correct fresh 2FA challenge succeeds.
3. The newly rotated session may perform an authorized admin operation only after the new role is server-resolved and fresh 2FA is verified.
4. The old session must remain rejected after fresh authentication; changing a browser role header or `X-Role` must never change the result.

Current evidence is the inverse behavior test `test_user_promoted_to_admin_keeps_old_verified_session_in_current_auth_contract`: it proves the existing session still succeeds (200) after the test DB role change. The test is a security finding, not a passing implementation.

## Production integration recommendation

**BLOCKED / NO-GO.** Continue only isolated prototype work until №5 approves audience mapping, schema/API v4, the code/response separation threat model, suppression/retention, restore-replay policy, and Auth privilege invalidation. Do not merge PR #25, enable official submit in `app.main`, or expose aggregate endpoints.
