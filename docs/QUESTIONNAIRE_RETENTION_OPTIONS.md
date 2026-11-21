# Retention options for decision #5

> **Історичний робочий документ команди (стан на 20.11.2026).** Чинний стан продукту — [README](../README.md), [API_CONTRACT.md](API_CONTRACT.md) і [integration-map.md](integration-map.md).

**Decision required. These are options for discussion, not legal advice, not production defaults, and not configured by the prototype.** In each option, day zero is the administrative close of a cycle; if the owner prefers report approval, the start point must be changed consistently.

| Option | Raw anonymous responses | Access-code digests/state | Security/audit events | Online backups | Recovery/appeal window | Operational/privacy profile |
| --- | --- | --- | --- | --- | --- | --- |
| A — Short | Purge 90 days after cycle close | Purge 30 days after close | Retain 180 days | Maximum 30 days; expire at same time as covered data | Short; challenges must conclude within 90 days | Lowest raw-data exposure and simplest purpose limitation; least time to investigate late disputes or restore an older cycle |
| B — Balanced | Purge 180 days after close | Purge 30 days after close | Retain 365 days, action-only allowlist | Maximum 60 days; expire/overwrite before raw data purge is deemed complete | Moderate; allows a defined review and correction period | More time for quality review and recovery, but keeps response-level data longer |
| C — Extended review | Purge 365 days after close or final appeal resolution, whichever is later, with a hard cap to be approved | Purge 30 days after close | Retain 730 days, action-only allowlist | Maximum 90 days and no backup outlives its source-data retention deadline | Longest; appropriate only if a documented review cycle requires it | Highest privacy exposure and storage/administration burden; longer investigative/recovery window |

These are intentionally round comparison points. #5/data owner must select a term and set any legal hold, appeal extension, and maximum cap. A longer term should require a documented purpose and access review. The code digest is a credential-control artifact, not an answer; keeping it after close increases exposure without supporting answer analysis.

## Start, purge, and recovery controls

- Record a coarse `closed_at`/approval event in cycle administration; do not add exact response timestamps.
- Purge response sets and answers in one transaction after the approved deadline; purge access-code digests/state separately on their approved deadline. Do not retain token-to-response mapping.
- Keep expert assessments in a separate store with a separate retention decision; anonymous response purge must not delete or join expert material.
- Audit only a fixed purge event, actor/service, cycle reference and counts if approved; never write answer IDs, codes, or option values to logs.
- Include SQLite WAL, snapshots, exports, replicas, and backups. A logical DELETE is not proof of physical erasure. A production runbook must checkpoint/truncate WAL where appropriate, expire every backup containing the data, verify retention inventory, and test recovery from a backup within its retention period.
- Before purge, restore from a pre-purge backup only in an isolated recovery environment and apply the same access and retention policy. After expiry, a backup must not silently resurrect deleted responses into production.

No retention job, scheduler, production purge API, physical erase, or production default is implemented. Prototype tests exercise only transactional purge on disposable synthetic SQLite files.
