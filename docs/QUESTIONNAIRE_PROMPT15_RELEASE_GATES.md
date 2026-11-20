# Questionnaire Prototype — Prompt 15 Release Gates

**Scope:** WIP branch `feature/assessment-questionnaire-v2`; PR #25 stays Draft / DO NOT MERGE. PR #24 and production systems are unchanged. This document distinguishes prototype evidence from production gates.

## Gate matrix

| Gate | Status | Evidence / remaining action |
|---|---|---|
| Sync with release CI head | PASS | Release commit `db70706f14cbcaba0d137151572aa996b106cd18` is an ancestor of the WIP branch through a normal merge. |
| Full backend regression | **PASS in CI** | Ubuntu full suite reports exactly 429 tests with zero failures/errors/skips (strict JUnit gate passed) in runs `44752925047` and `44752913909`. Local Windows result is `428 passed, 1 skipped`, only because this host denies symlink creation; the hosted Windows symlink job passed. |
| Frontend tests | **PASS locally and in CI** | 46 passed, zero skipped; strict count gate passed in both current-head Actions runs. |
| TypeScript and production build | **PASS locally and in CI** | `tsc --noEmit`, Vite production build, and source artifact boundary scan passed. |
| Browser E2E | **PASS locally and in CI** | Local Playwright CLI exit **0**, `13 passed (34.6s)`, strict JUnit 13/0/0/0; ports 8033, 8034, 5184 closed. Both Actions runs generated strict 13/0/0/0 JUnit and verified all three server ports closed. |
| Independent CI for PR #25 | **PASS** | Runs `44752925047` (pull_request) and `44752913909` (push), head `940d6f488ca28e90717802bb55bca6bcc49f7a86`: all 5/5 jobs passed. The earlier failures were corrected: actionlint caught the invalid job-level `runner.temp` context; the harness then correctly rejected GitHub's non-system temp path; finally the serialized-race test assertion was corrected to accept the valid activation-first `409` outcome. Workflow has read-only permissions and no deploy/push steps. |
| Windows symlink security | **PASS in hosted Windows CI** | Dedicated symlink regression and strict JUnit gate passed. Local Windows execution remains skipped because this host denies symlink creation. |
| Production artifact isolation | **PASS in CI** | Production backend/frontend Docker images were built locally on the hosted runner, exported and scanned for E2E server, route, harness and synthetic code markers. Images were not pushed or deployed. Local `dist` and packaging boundary scan also passed. |
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
