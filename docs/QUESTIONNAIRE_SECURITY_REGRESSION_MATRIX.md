# Questionnaire security regression matrix

**Scope:** synthetic test application and `.prototype.sqlite` DB only. All test cases below were executed in the targeted test run on 2026-11-20 unless marked otherwise.

| Test ID | Requirement | Expected behavior | Result | Evidence |
| --- | --- | --- | --- | --- |
| MIG-01 | Migration target isolation | Requires explicit flag, guarded schema-3 synthetic copy, and `.prototype.sqlite` path | PASS | migration refusal tests |
| MIG-02 | Backup and legacy preservation | Backup verifies; cycles, numeric answers, codes and audit remain unchanged | PASS | migration backup/preservation test |
| MIG-03 | Failure/restore | DDL failure rolls back; verified backup restores clean schema 3 | PASS | three injected failure points + restore test |
| ANON-01 | No respondent linkage | No identity/token/IP/time fields or token FK in anonymous response tables | PASS | adapter schema inspection test |
| ANON-02 | Anonymous request | Cookie and Authorization are rejected; response never returns set ID | PASS | adapter/anonymous request test |
| AUTH-01 | Expert identity source | Existing V2 cookie session and completed 2FA are required; `X-Role` has no effect | PASS | real V2 session/2FA/role spoof test |
| AUTH-02 | Explicit grant and scope | Admin self-grant rejected; active expert grant and per-assessment assignment required | PASS | grant/assignment access test |
| AUTH-03 | Revocation/expiry | Revoked grant, invalid/deleted/expired session, and pending 2FA fail closed | PASS | expert revocation and V2 session tests |
| CSRF-01 | Mutation origin/CSRF | Missing CSRF or invalid Origin is rejected | PASS | grant and expert update tests |
| EXP-01 | Assignment ownership | Other principal cannot read a specific assessment | PASS | outsider assessment read test |
| EXP-02 | Optimistic concurrency/finalize | Stale revision and repeated/after-finalize mutation rejected | PASS | revision/finalization test |
| EXP-03 | Audit isolation | Transactional allowlisted actions and event times; no answer content in audit | PASS | expert audit test |
| ATOM-01 | One-time code/replay | Exactly one concurrent submit using same code succeeds | PASS | same-code race test |
| ATOM-02 | Close/submit | Close serializes with submission; no submit can commit after close returns | PASS | competing close/submit test |
| ATOM-03 | Partial failure | Injected answer insert failure rolls back response set and token state | PASS | same-code/failure atomicity test |
| CODE-01 | Expiry/category/cycle/version | Expired, wrong-category, wrong-version, replayed, and closed-cycle submissions rejected | PASS | adapter rejection tests |
| RATE-01 | Global/per-cycle throttle | Limits return deny after configured synthetic thresholds; no IP key | PASS | rate limiter unit + HTTP test |
| LOG-01 | Secret logging | Access codes, option IDs, auth/cookie/CSRF values absent from prototype app logs | PASS (prototype logger only) | caplog test |
| LOG-02 | Deployed access logs/IP | Proxy/ASGI/access/error tracker config not provided to this worktree | NOT RUN | deployment validation still required |
| SUP-01 | Primary/complementary suppression | Test helper hides small cell and a derivable companion cell with unknown values | PASS (test helper only) | suppression test |
| SUP-02 | Differencing across repeated queries | No aggregate endpoint exists; cross-query policy is not implemented | NOT RUN / BLOCKED | requires #5-approved suppression design and API |
| SUP-03 | Dashboard/raw access | Prototype registers no raw-response/dashboard endpoint | PASS (route inventory) | suppression route inventory test |
| RET-01 | Transactional purge/cascade | Test-only closed-cycle purge is atomic; child answers disappear; FK/integrity valid | PASS | purge test |
| RET-02 | WAL/backup behavior | WAL checkpoint and post-purge verified backup contain no purged response rows | PASS (logical SQLite test) | purge/WAL test |
| RET-03 | Physical erasure of old pages/backup copies | SQLite pages and historical backups cannot be proven securely erased by this test | NOT RUN | requires approved operations runbook/storage controls |
| COMP-01 | Legacy numeric path | Numeric response and historical schema-3 tables remain unchanged | PASS (synthetic baseline) | migration and adapter tests |
| COMP-02 | Dashboard/Analytics/Integrity Index | No production routes or scoring code changed; runtime integration not enabled | PASS (change isolation), end-to-end contract NOT RUN | scoped diff and no production mount |

The in-memory rate limiter is process-local, intentionally not presented as distributed or production ready. Suppression and retention remain proposals; the prototype does not publish official aggregates.

Final verification on 2026-11-20: targeted prototype suite **25 passed**; full backend **409 passed, 1 Starlette/httpx deprecation warning**; frontend **45 passed** (non-failing WebSocket port-24678-in-use warning emitted by test tooling); TypeScript/production build **PASS**; browser E2E **12 passed** against temporary synthetic SQLite. These results do not validate production ingress logging, deployed proxy configuration, or an approved aggregate API.
