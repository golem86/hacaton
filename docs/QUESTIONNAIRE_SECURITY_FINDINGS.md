# Questionnaire security findings and threat model

> **Історичний робочий документ команди (стан на 20.11.2026).** Чинний стан продукту — [README](../README.md), [API_CONTRACT.md](API_CONTRACT.md) і [integration-map.md](integration-map.md).

**Scope:** WIP prototype at the current working tree. Synthetic data and temporary SQLite files only. This is not a production security certification.

## Threat model

| Actor/capability | Asset/attack | Verified controls | Residual risk |
| --- | --- | --- | --- |
| Anonymous caller | Guess/replay one-time access codes | Code checked for cycle/category/expiry/unused state; SQLite transaction; global/per-cycle SQLite POC limiter; generic response | Schema-3 token is stored in plaintext; distributed multi-host rate limiting is not implemented |
| Authenticated non-expert | Spoof `X-Role`, access an assessment | Existing V2 session lookup, 2FA, explicit grant and exact assignment checked per request; spoofed role ignored | Test-only adapter; no production expert role or approved role-change policy |
| Operator with DB/WAL/backup access | Correlate code consumption to answer insertion | No token/response FK; no respondent ID or response timestamp; separate answer tables | **A privileged DB/WAL observer can correlate rows in the same SQLite write transaction or before/after snapshot. No absolute anonymity claim.** A pre-submit backup may also restore an unused code after its response is absent |
| Dashboard/API consumer | Infer small groups through cuts/totals/repeated queries | No official aggregate or raw-answer route exists; synthetic suppression helper masks a small cell and a complementary cell in one result | Helper has no query history, cross-cycle or overlapping-filter defense; production suppression is blocked |
| Proxy/log/error tracker reader | Recover code, answer, identity or IP from logs | App logger is checked for fixed event names and does not include request body; anonymous API rejects Cookie/Authorization | Uvicorn/proxy/access/error logs were not available; IP and timing redaction NOT RUN |
| Local test runner | Accidentally modify production SQLite/auth DB | Prototype database paths must resolve under OS temp, avoid configured/default DB paths, require new synthetic schema-3 file and sentinel rows; auth adapter requires explicit existing temp `V2_AUTH_DB`; grant lookup is read-only | Windows symlink creation test was skipped because the environment did not permit link creation; OS-level races by a process able to replace temp files are outside this prototype's guarantee |

## Verified implementation

- `official_response_sets` and `official_answers` have no user/respondent/email/IP/device/access-token columns, token FK, response creation timestamp, or browser identifier.
- Existing schema-3 `access_tokens` rows have `id`, `cycle_id`, `token`, and `used`. `token` is plaintext and unique. This WIP does not change that shared contract. The distinct older `backend/prototypes/official_expert.py` HMAC fixture is not the code path used by the Assessment Manager adapter.
- Submission inserts response set and answers, then marks the schema-3 code used, all under one `BEGIN IMMEDIATE`; a forced answer insert failure rolls back the response set and token update. Concurrent use of the same code accepts one; close/submit are serialized.
- Response storage has cycle/template/version/category but no exact response time. Rate-limit counters contain global/per-cycle bucket keys and expiry, never code/IP/user/device identifiers. Expert audit has exact event seconds in a different table and contains allowlisted action/assignment identifiers, not answer values.
- The test verifies a WAL checkpoint and a new post-purge backup without response rows. It does **not** prove physical erasure from old WAL pages, filesystem snapshots, or retained pre-purge backups.

## Correlation conclusion

The design prevents direct schema joins from a code row to a descriptive answer and protects against ordinary API callers. It does not provide cryptographic unlinkability against a database owner, forensic WAL reader, or observer with transaction-time snapshots. Both the token state update and answer insert are part of one transaction in the same file; commit grouping and row changes are a correlation channel even without an FK or timestamp. Existing plaintext tokens increase the impact of DB disclosure. Production must either explicitly accept this threat boundary or approve an architecture that separates credential consumption from answer storage with a reviewed unlinkability mechanism. Splitting databases alone is not sufficient if a shared transaction, event, or precise timing signal remains.

## Evidence and remaining tests

- Targeted tests: `backend/tests/test_questionnaire_integration_prototype.py` — **40 passed, 1 skipped** (Windows symlink creation unavailable), plus one Starlette/httpx deprecation warning.
- Full backend: **424 passed, 1 skipped, 1 warning** in 83.92 seconds. Frontend: **45 passed**. TypeScript/production build: **PASS**. Browser E2E: **12 passed** with temporary synthetic SQLite. Frontend test tooling also emitted a non-failing “WebSocket port 24678 already in use” warning.
- Production ingress logging, physical data erasure, multi-host load, and real-world re-identification assessment: **NOT RUN / BLOCKED**.
