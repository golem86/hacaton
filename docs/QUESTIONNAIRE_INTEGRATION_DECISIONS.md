# Questionnaire integration decisions required from #5

> **Історичний робочий документ команди (стан на 20.11.2026).** Чинний стан продукту — [README](../README.md), [API_CONTRACT.md](API_CONTRACT.md) і [integration-map.md](integration-map.md).

This document tracks decisions that block production DDL/API. The implementation in this WIP is a test-only adapter and must remain Draft / DO NOT MERGE.

## Required decisions

1. **DDL/migration:** approve the corrected `cycles(id)` foreign keys, exact SQLite DDL/indexes, migration version/order, SQLite minimum version, startup behavior, backup and rollback approach.
2. **Cycle binding:** approve separate immutable questionnaire binding vs. using/reconciling `cycle_configs.questionnaire_version` (currently `demo-v1`), binding timing, and handling of already-open cycles.
3. **Audience and categories:** confirm Form 1 working-group audience; accept Form 2 as a working interpretation for permanent and variable personnel per Appendix Г while documenting the page-60 title ambiguity; do not enable automatic routing until approved. Approve category/unit mapping and whether unit is stored at all.
4. **Anonymous submission contract:** approve required/optional answers, generic error behavior, code expiry/category policy, rate limits, and what operational metadata can exist outside the response database.
5. **Privacy:** choose `k`, allowed cuts, complementary/repeated-query suppression, raw response retention start/deadline, code digest retention, audit/log/backup terms, and purge/recovery runbook.
6. **Expert governance:** approve the separate role/grant and assignment authority, admin self-grant prohibition, session/2FA policy, session revalidation after grant revocation, audit allowlist/time precision, concurrency/finalization semantics, and expert retention.
7. **Scoring:** no descriptive option becomes a score. Any Integrity Index mapping requires a separately approved method and remains outside this WIP.

## Present implementation boundary

- Prototype tables and routes are test-only and not mounted by `app.main`.
- Test adapter uses the existing V2 session cookie, completed 2FA, CSRF/Origin checks, server-side explicit grant, assignment-scoped reads/writes, and rechecks current grants/assignments on every expert request.
- Anonymous responses are separate from numeric responses and have no link to the consumed token or respondent identity.
- No production aggregates, production retention scheduler, production role, production API, DDL migration, scoring, or deployment changes are included.

Until the decisions above are resolved, keep PR #25 Draft and marked DO NOT MERGE.
