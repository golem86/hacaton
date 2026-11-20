# Final decisions required from #5

This evidence package recommends **CONDITIONAL APPROVAL FOR ISOLATED DEVELOPMENT ONLY**. Keep PR #25 Draft / DO NOT MERGE until the following are approved.

1. **Anonymity threat boundary:** acknowledge that schema-level unlinkability does not protect against a privileged DB/WAL/backup observer correlating code consumption and response insertion in one SQLite transaction. Decide whether to accept this, or require a reviewed unlinkability architecture. Existing schema-3 `access_tokens.token` is plaintext; this WIP does not modify it.
2. **Rate limiting:** approve SQLite-backed counters for a single host/low-volume deployment or identify an already-approved shared service for multi-host workers. Prototype POC uses `BEGIN IMMEDIATE`, global/per-cycle fixed-window buckets, TTL and fail-closed 503 on storage failure. Multi-host production behavior is unverified. Decide 429/503 policy and lock-contention target.
3. **Suppression:** approve `k`, allowed cuts, complementary/repeated-query/cross-cycle protection, and whether to use a disclosure ledger or another reviewed method. Current helper is not an aggregate security mechanism; no aggregate route is exposed.
4. **Retention:** select raw response, code, audit, WAL, export and backup lifetimes/start events; approve purge/recovery and physical erasure evidence. Options are in `QUESTIONNAIRE_RETENTION_OPTIONS.md`; no defaults are implemented.
5. **DDL/API:** approve additive schema after schema 3, exact keys/indexes, `cycles(id)` references, mode/version binding, SQLite version support, error responses, category and unit mapping.
6. **`demo-v1` coexistence:** approve the separate one-row-per-cycle official binding and route gating while leaving `cycle_configs.questionnaire_version` semantics/legacy data untouched.
7. **Audience:** confirm Form 1 working group and Form 2 interpretation; preserve the documented page-60 title vs Appendix Г ambiguity. Do not auto-route Form 2 until decision.
8. **Expert role governance:** approve grant/revoke authority, self-grant prohibition, assignment model, reviewer need (currently not justified), session invalidation, fresh 2FA and assignment handling after user→admin promotion.
9. **Scoring:** descriptive answers remain outside Integrity Index. Any mapping requires a separately approved methodology.

No item above is silently implemented in production by this WIP.
