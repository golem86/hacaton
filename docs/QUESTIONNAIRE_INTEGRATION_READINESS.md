# Official Questionnaire Integration Readiness — Prompt 14

**State:** isolated WIP / Draft PR #25 / **DO NOT MERGE**. Assessment Manager PR #24 is not modified. The release CI head used for synchronization is `db70706f14cbcaba0d137151572aa996b106cd18`; the WIP synchronization merge is `971ba4a` (before the Prompt 14 implementation commit). All submitted answers and identities in this report are synthetic.

## Implemented and exercised in this WIP

- Frontend labels 1.0.0 and 1.1.0 as partial prototypes, 2.0.0 and 2.1.0 as full adapted catalogs. All versions remain marked as methodologically pending. The full 2.1.0 Form 1 preview is the default; product preview still has no submission control.
- The isolated prototype catalog accepts full Form 1 and Form 2 for 2.0.0 and 2.1.0. IDs are stable between the two full versions; the updated wording and maturity descriptions remain fixture text and have no score.
- A test-only Uvicorn app (`prototypes.official_e2e_server`) prepares a new synthetic copy of schema 3, runs only the prototype migration, seeds exact form/version bindings and synthetic codes, and exposes an E2E verification endpoint. It is not imported by `app.main`.
- Browser E2E loads the actual frontend catalog, validates all required answers, submits Form 1 and Form 2 version 2.1.0 through the isolated test API with `credentials: omit`, and verifies durable SQLite rows using a fresh connection. It also verifies replay rejection, code consumption, the unchanged legacy numeric-answer count, and absence of respondent/token columns from the response-set table.
- Backend tests cover invalid versions/options/answers, wrong cycle/category, expiry, duplicate/replay, atomic answer/code transaction, same-code races, close/submit serialization, and expert grant/assignment access checks. Assignment revocation is checked on the next request with the same V2 session.
- Synthetic disclosure ledger tests show exact replay returns a cached result while changed overlapping filters or a different cycle in the same release family are rejected. There is no aggregate endpoint.

## Verification state

| Check | Result | Evidence / limitation |
|---|---|---|
| Full backend pytest | **PASS: 427 passed, 1 skipped** | `PYTHONUTF8=1 ..\\..\\audit-venv\\Scripts\\python.exe -m pytest -q` from `backend`. Initial run without `PYTHONUTF8=1` failed in unrelated `test_mig1_explicit_migration_requires_confirmed_backup`: a spawned Python process decoded Windows output as UTF-8 and raised `UnicodeDecodeError`; no test expectation or production code was changed. |
| Questionnaire integration + expert prototype tests | **PASS: 66 passed, 1 skipped** | Includes synthetic SQLite, 2.1.0 forms, session/2FA/CSRF/Origin, assignment/grant revocation, and ledger tests. One skip is the OS-denied symlink creation test. |
| Frontend unit tests | **PASS: 46 passed, 0 skipped** | `npm test` after the test-only harness/proxy additions; only harmless Vite WebSocket port and npm update notices. |
| TypeScript + production build | **PASS** | `npm run build` after the test-only harness/proxy additions; `tsc --noEmit` and Vite production build completed. |
| Playwright browser suite | **PARTIAL: all 13 cases printed `ok`; process exit not captured** | Run against local synthetic V2 DB and separate test API with Chromium. The E2E scenario posted both 2.1.0 forms and verified SQLite via a fresh connection. The Windows command wrapper did not return its final summary/exit status after tests finished. Therefore this is not reported as aggregate PASS. |
| SQLite migration, backup, restore, failure injection | **PASS: 6 focused checks** | Synthetic schema 3 only; includes idempotence, preservation and failure rollback. |
| Windows install artifact compatibility | **NOT RUN** | No Windows clean-install script or schema-3 database artifact exists in this repository. The synthetic schema-3 source is not proof of the release installer order. |
| Windows symlink security case | **NOT RUN / skipped** | Symlink creation raised an OS privilege error even in an elevated attempt. |
| PR #25 GitHub Actions | **NOT RUN** | `.github/workflows/v2-ci.yml` triggers PR checks only when base is `feature/v2-integration`; Draft PR #25 targets the release branch. No Actions PASS is inferred. |
| `git diff --check` and workflow YAML | **PASS** | Workflow parsed using the Python YAML parser. |

## Security findings and limits

1. **No absolute anonymity claim.** The test adapter reuses schema 3 `access_tokens.token` (plaintext). It creates the official response set/answers and marks the token used in one SQLite transaction. There is no respondent ID, token column, response ID in the token table, or exact answer timestamp, but a privileged observer of the DB/WAL can correlate transaction chronology. This is a prototype tradeoff, not an approved anonymous production design.
2. **Logs and ingress remain unverified.** The synthetic app does not represent the deployed reverse proxy, ASGI access logging, tracing or error collection. Production must ensure request bodies, code, cookies, Authorization, IP and answer options are not logged before an anonymity claim.
3. **Disclosure ledger is test-only and in-memory.** It is a conservative demonstration, not durable across processes/restarts and not connected to an aggregate endpoint. Production must use an owner-approved persistent disclosure-control design before publishing aggregates.
4. **Retention is not approved.** The test-only purge is transactional and checks rows after a WAL checkpoint, but deletion does not erase older backups or previously copied WAL files. Retention duration, backup expiry, export deletion and restore procedures remain for №5/data owner.
5. **Auth-owner blocker:** current V2 Auth behavior permits a user promoted to admin to keep using an already verified session. `test_user_promoted_to_admin_keeps_old_verified_session_in_current_auth_contract` documents the observed behavior. This task did not change V2 Auth. The Auth owner must invalidate old sessions on privilege change and require fresh 2FA before production expert/admin lifecycle integration.
6. **Expert lifecycle is prototype-only.** Explicit grant and active assignment are checked on each request; assignment and grant revocation affect the next request; audit records include event time and exclude answers. No production expert role, schema, or API is implemented.
7. **Windows compatibility remains open.** No checked-in Windows install artifact was found. The Windows symlink test cannot execute in this environment. Before deployment, validate the exact installer artifact on a synthetic copy and run the symlink test on an authorized Windows host.

## Architecture options for anonymity (not approved)

| Option | Complexity | Linkage/security | Schema 3 fit |
|---|---|---|---|
| A. Current one-time code and answer stored/consumed in same schema-3 SQLite transaction | Low; reuses current token tables and atomic write | Prevents replay and respondent ID linkage, but plaintext code and DB/WAL chronology can correlate access with answer | High; no existing DDL change for test adapter |
| B. Separate credential service/store with keyed blinded/HMAC code verification, delayed/batched consumption, and separately controlled response DB | High; new service, key rotation, restore/replay safeguards and operational runbook | Better separation of code validation from answer writes; still needs traffic timing, proxy logs, backup and collusion threat analysis | Low without new services/contracts; do not implement until №5 approves |

Putting an HMAC token in the same table and transaction alone is not sufficient to remove the WAL/transaction correlation risk.

## Decisions required before production integration review

1. Approve the threat model and choose the token/response separation architecture.
2. Approve the exact Form 2 audience mapping; current synthetic binding does not enable product routing.
3. Approve template 2.1.0 methodology/version publication, including the restored `0%` wording and duplicate-source marker. No scoring changes are proposed.
4. Approve production DDL/API and migration plan after schema 3, including code rollback/restore replay protections.
5. Set `k`, supported aggregate cuts, persistent disclosure-ledger semantics and cross-cycle policy.
6. Set retention start/end, backup/WAL/export deletion, restore and evidence-of-purge policy.
7. Require ingress/logging verification and anonymous abuse controls that do not silently collect identity metadata.
8. Require V2 Auth session invalidation and fresh 2FA after role/privilege changes.
9. Provide the exact Windows schema-3 release artifact and installer scripts for synthetic-copy validation.
10. Decide how CI should run for a Draft PR based on `feature/assessment-manager-release-v2` and update PR #25 description only after local evidence is complete.

**Readiness conclusion:** this WIP has a runnable isolated synthetic browser/API/SQLite scenario and stronger regression coverage, but is **not ready for production integration**. PR #25 remains Draft / DO NOT MERGE; no production DDL/API, auth, Analytics, scoring, or database was changed.
