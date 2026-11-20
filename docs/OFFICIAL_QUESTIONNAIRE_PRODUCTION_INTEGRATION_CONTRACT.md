# Official Questionnaire Production Integration Contract (for №5 approval)

**Status: proposal only — not approved, not implemented, not migrated.** This is an additive integration contract for a future schema-4 migration after the current SQLite schema 3. No production API, DDL, deployment, or database was changed for this proposal. PR #25 remains Draft / DO NOT MERGE.

## 1. Contract boundaries

- Keep existing Assessment Manager cycles, `cycle_configs.questionnaire_version='demo-v1'`, `response_sets`, numeric `answers`, Analytics, Dashboard and Integrity Index behavior unchanged.
- Official descriptive answers live in `official_response_sets` and `official_answers`, separate from both legacy numeric answers and expert records.
- Templates are immutable by `(template_id, version)` after publication. Corrections publish a new version; do not update historical template content or responses.
- Store option labels and IDs only. No `score`, weight, order-to-score mapping, Integrity Index hook, or automatic numeric conversion is permitted.
- Form 1 is for an officially designated working group. Form 2 audience is unresolved: Appendix В p. 60 names a working group while Appendix Г p. 67 describes questionnaire 2 for personnel. Do not route Form 2 by respondent category until №5 approves the mapping.
- No aggregate endpoint until the owner approves population definitions, `k`, permitted cuts, suppression, query ledger, retention and access rules.

## 2. Additive schema-4 proposal

Migration v4 adds tables and triggers only. It must not alter or rewrite schema-3 rows, legacy numeric data, `cycles`, or the meaning of `demo-v1`. Every cycle FK below targets the existing `cycles(id)`.

### Immutable template catalog

```sql
CREATE TABLE official_templates (
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  form_number INTEGER NOT NULL CHECK (form_number IN (1,2)),
  audience_code TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  source_appendix TEXT NOT NULL CHECK (source_appendix = 'В'),
  status TEXT NOT NULL CHECK (status IN ('draft','published')),
  content_sha256 TEXT NOT NULL CHECK (length(content_sha256)=64),
  created_at TEXT NOT NULL,
  PRIMARY KEY (template_id, version)
);

CREATE TABLE official_questions (
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  question_id TEXT NOT NULL,
  section_id TEXT NOT NULL,
  question_number INTEGER NOT NULL CHECK (question_number > 0),
  printed_page INTEGER NOT NULL CHECK (printed_page BETWEEN 53 AND 66),
  kind TEXT NOT NULL CHECK (kind='single_choice'),
  required INTEGER NOT NULL CHECK (required IN (0,1)),
  source_duplicate INTEGER NOT NULL DEFAULT 0 CHECK (source_duplicate IN (0,1)),
  prompt TEXT NOT NULL,
  PRIMARY KEY (template_id, version, question_id),
  FOREIGN KEY (template_id, version) REFERENCES official_templates(template_id, version)
);

CREATE TABLE official_options (
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  question_id TEXT NOT NULL,
  option_id TEXT NOT NULL,
  display_order INTEGER NOT NULL CHECK (display_order > 0),
  label TEXT NOT NULL,
  PRIMARY KEY (template_id, version, question_id, option_id),
  UNIQUE (template_id, version, question_id, display_order),
  FOREIGN KEY (template_id, version, question_id)
    REFERENCES official_questions(template_id, version, question_id)
);
```

SQLite triggers must reject UPDATE/DELETE of a published template and INSERT/UPDATE/DELETE of its questions/options. A content hash is checked at publish time and by tests. Re-publication under the same version is forbidden.

### Frozen cycle binding

```sql
CREATE TABLE official_cycle_bindings (
  cycle_id INTEGER NOT NULL REFERENCES cycles(id),
  mode TEXT NOT NULL CHECK (mode IN ('self_assessment','expert_assessment')),
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  audience_policy TEXT NOT NULL,
  binding_sha256 TEXT NOT NULL CHECK (length(binding_sha256)=64),
  PRIMARY KEY (cycle_id, mode, template_id, version),
  FOREIGN KEY (template_id, version) REFERENCES official_templates(template_id, version)
);
```

Before binding publication, №5 must approve which modes/forms a cycle can bind and whether a cycle may have multiple templates. Triggers reject binding INSERT/UPDATE/DELETE unless its cycle is `draft`. Binding and activation each use `BEGIN IMMEDIATE`; activation requires an exact, published template/version binding and freezes it. Tests must race bind vs activate and prove that no activated cycle can end up unbound or acquire a later binding. Existing Assessment Manager endpoints own the cycle state transition; integration requires an approved hook/transaction boundary rather than a separate competing state model.

### Anonymous descriptive responses

```sql
CREATE TABLE official_response_sets (
  response_set_id TEXT PRIMARY KEY,
  cycle_id INTEGER NOT NULL,
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  category_code TEXT NOT NULL,
  FOREIGN KEY (cycle_id) REFERENCES cycles(id),
  FOREIGN KEY (template_id, version) REFERENCES official_templates(template_id, version)
);

CREATE TABLE official_answers (
  response_set_id TEXT NOT NULL REFERENCES official_response_sets(response_set_id) ON DELETE CASCADE,
  template_id TEXT NOT NULL,
  version TEXT NOT NULL,
  question_id TEXT NOT NULL,
  option_id TEXT NOT NULL,
  PRIMARY KEY (response_set_id, question_id),
  FOREIGN KEY (template_id, version, question_id, option_id)
    REFERENCES official_options(template_id, version, question_id, option_id)
);
```

`official_response_sets` must not contain account/respondent ID, access code/digest, IP, user agent, exact submission time, session ID, request ID or unit unless separately approved. Category is potentially identifying and must be mapped to a sufficiently large, approved population; do not infer it from Form 2. Internal response IDs never leave the server. Expert answers use a distinct table family and cannot FK/join to anonymous response sets.

### One-time code designs — decision required

**Option A (simpler, weaker unlinkability):** add `official_code_states(code_digest, cycle_id, template_id, version, category_code, expires_at, used)` with a keyed HMAC digest and key stored outside SQLite. Validate, write response set/answers and flip `used` in one `BEGIN IMMEDIATE` transaction. Never store the raw code or a code FK in answers. This gives atomic replay protection but DB/WAL observers can correlate the consumed-code row and response writes by transaction timing. Select only if the data owner explicitly accepts this threat.

**Option B (recommended for a stronger separation goal):** separate credential validation/one-time nullifier state from the answer database and service identity. Use independently controlled stores/keys, a short-lived signed submission context, no shared persistent request ID, delayed/batched answer writes, and a restore protocol that prevents spent codes being re-enabled. Define crash recovery before implementation: if the code is consumed but answer persistence fails, do not silently lose a response or re-open a spent code. This option needs a separate operational/API boundary and is not just an HMAC column in the same database.

Neither design proves anonymity against colluding operators, network observers, endpoint timing, or external logs. The final design depends on the approved threat model.

## 3. API contract

All paths below are proposals. Existing `/api/assessments/*`, public numeric submissions, role model and payloads remain unchanged.

### Administrative template and binding APIs

- `POST /api/official/templates` — create draft version. Admin V2 session, verified 2FA, CSRF and same-origin checks required.
- `PUT /api/official/templates/{id}/{version}` — draft only; server validates unique IDs, option ownership, source metadata and schema. Reject if published.
- `POST /api/official/templates/{id}/{version}/publish` — validate and freeze immutable content hash; audit actor/action/time without answer data.
- `PUT /api/assessments/{cycle_id}/official-bindings/{mode}` — cycle must remain draft; exact published version; approved audience policy; transactional insert. Reuse the existing cycle lifecycle, not a duplicate cycle API.
- `GET /api/assessments/{cycle_id}/official-bindings` — Admin only; return template ID/version, audience policy status and lifecycle state, no response counts below approved suppression.

### Anonymous participant API

- `GET /api/official/templates/{template_id}/{version}` — public immutable questions/choices only; return `Cache-Control: no-store`; do not return counts, category sizes, private notes, analytics or internal response IDs.
- `POST /api/official/submissions` — body contains `{code, template_id, version, answers:[{question_id,option_id}]}`. Do not accept `cycle_id`, respondent ID or category as authority from the browser; resolve them from the one-time code and frozen binding. Require no Cookie, Authorization, CSRF or V2 session; reject Cookie/Authorization if present. The form client must use `credentials: 'omit'`, no Authorization header, no account identifier, and must not place the code in a URL, referrer, browser storage or analytics.
- Server checks published version, open cycle, exact binding, answer completeness and ownership, code category/cycle/version, expiry, rate limits and unused state; code consumption plus response persistence are atomic under the approved code architecture.
- `201 {accepted:true}` only after durable persistence. Replay/expired/foreign code errors are generic and never echo the submitted code or answer. No client-visible response-set ID.
- No GET/read/delete/export API for raw anonymous rows. No aggregate endpoint in this phase.

### Expert API (separate store and permission)

- Admin-only grant/revoke and cycle/template/version assignment endpoints; require existing V2 verified 2FA, CSRF, Origin and audit.
- Each expert read/write/finalize request rechecks live grant, active assignment and V2 session; Admin is not automatically Expert.
- `PUT .../answers` includes `expected_revision`; stale revision returns 409. `POST .../finalize` requires complete validation and is single-use; finalized content is immutable.
- Expert assessment/answers/audit use their own tables. Audit includes event time, actor, target and action only; never answer values, code, session secret or request body.
- A role/privilege change invalidates all existing sessions and requires a fresh login plus fresh 2FA. This is blocked on the V2 Auth owner; do not ship the expert API until fixed and tested.

## 4. Authenticated UI and anonymous submit separation

The current authenticated preview is read-only. A future product flow may allow a signed-in V2 user to navigate to a separate respondent surface, but the anonymous answer request must not carry the V2 session. Preferred deployment: a dedicated no-cookie form origin with a narrow allow-listed CORS policy; the browser sends the code only in the POST body and sets `credentials: 'omit'`. The API rejects Cookie and Authorization even if a browser regression accidentally adds them. Do not tie a code issuance row to an account, return a user-specific response ID, or include the code in a URL. Do not send answers or code to error trackers/analytics. If a separate origin is infeasible, validate the same guarantees with browser tests while accounting for cookie-bearing page requests and reverse-proxy logs.

The isolated E2E test currently signs into V2 with a synthetic account, opens the E2E-only harness, and asserts the browser's questionnaire API request has no Cookie/Authorization. The test server also rejects either header. This demonstrates a test boundary only; the product page still has no submit action or production API.

## 5. Logging, timing and storage threat model

Threats to review before any anonymity statement:

| Surface | Risk | Required control/evidence |
|---|---|---|
| Plaintext codes | Database readers/backups can recover active or spent codes; rollback can re-enable a spent code | Store no plaintext code; use independent key management; backup restore must rotate/revoke code state or prove monotonic consumption |
| SQLite transaction/WAL | Same-transaction code consumption and answer insert correlate under privileged DB/WAL inspection | Choose Option A only with explicit trusted-operator assumption, or separated stores/queued batches; inspect WAL and rollback copies using synthetic fault tests |
| Timing | Request arrival, code validation, DB writes, response latency and expert/admin event timing may correlate | No exact answer timestamp; queue/batch or add a reviewed delay if threat model warrants; measure under synthetic load and document timing limits |
| Reverse proxy/access logs | Source IP, path, body, Cookie or Authorization can re-identify/link submissions | Disable body/header logging; preferably use no-access-log server; test actual proxy config and verify no code/answer/cookie/IP fields in access/error/trace logs |
| Backup/restore | Restoring pre-submit DB can reopen spent code; stale backups preserve deleted answers/WAL | Define backup TTL/access; restore into quarantine; reconcile/rotate code state before reopening writes; test replay and purge across WAL/backup/snapshot copies |
| Error tracking | Framework exceptions may capture body, code and answers | Generic errors; disable request-body capture; synthetic canary test verifies no secrets in logs/traces |
| Aggregate query history | Repeated/overlapping/cross-cycle requests can difference suppressed groups | Persistent, transactional, cross-worker disclosure ledger; canonical query fingerprint and cached identical response; policy limits changed queries; no route until approved |

Do not claim absolute anonymity. Document the accepted observer model and residual IP/timing risks.

## 6. Retention, suppression and rate limiting

- Raw descriptive answer retention start/end and backup/export expiry require data-owner approval. Purge response sets and answers transactionally; then handle WAL, snapshots, backups, caches and exports under a tested runbook. SQLite row deletion alone is not physical erasure.
- Approve `k`, category population, valid cuts, complementary suppression, totals and release cadence. No numeric `k` or category mapping is invented here.
- A production disclosure ledger must be durable across workers/restarts, scoped across related cycles and query cuts, and return cached identical outputs. The prototype's in-memory ledger does not satisfy this.
- Anonymous abuse limits should use per-code/per-cycle/global limits first, generic errors and minimal logging. Multi-host/IP-based limiting requires a separate privacy assessment and retention decision.
- No production aggregate endpoints are proposed for release until these rules are approved and attack tests pass.

## 7. Additive migration and compatibility plan

1. Supply the exact Windows schema-3 release artifact and installer scripts; make a byte-for-byte synthetic copy only. Never point migration tests at production files.
2. Verify schema version 3, `cycles(id)`, FK/integrity checks, legacy row snapshots and `demo-v1` configs before migration.
3. Create a verified backup; migration v4 runs in an explicit transaction, creates only new official tables/indexes/triggers, preserves existing rows and sets schema version 4 only after all checks succeed.
4. Inject failures after each DDL/data phase; verify rollback or restore from verified backup, rerun migration for idempotency, and compare legacy tables/hashes.
5. Test both official forms and historical template versions, cycle binding/activation races, atomic code use, submit/close races, rate limit, replay and duplicate submissions with synthetic data.
6. Verify seed creates only demo-v1 legacy data plus optional immutable templates according to an explicit flag; repeated seed is idempotent. No automatic official cycle/category routing.
7. Build the exact Windows release artifact, copy it to temp, repeat migration/backup/restore and symlink path security test on an authorized Windows runner.
8. Rollback: stop writes, restore the verified backup, confirm schema 3 and all legacy checks, disable new official routes, rotate/revoke issued codes before reopening to avoid replay after rollback. Never downgrade by dropping tables in-place.

## 8. Required tests before approval

- DDL: all composite FKs, unique constraints, immutable published parent/child triggers, draft-only cycle binding insert/update/delete, activation requires binding, `cycles(id)` FK, migration idempotency and no mutation of schema-3 snapshots.
- API: old endpoints/payloads remain unchanged; explicit invalid/missing version; missing/foreign/duplicate answer; wrong cycle/category/expiry/replay; auth header/cookie rejection; generic errors; 2FA/CSRF/Origin for admin/expert.
- Concurrency: bind-vs-activate; close-vs-submit; two simultaneous uses of one code; answer insert failure rolls code use back (for atomic design); concurrent expert revision/finalize.
- Privacy: inspect response schema, access logs, proxy logs, trace/error outputs; compare DB/WAL/backup artifacts; rollback restore replay; timing distribution; no answer/account/code link.
- Suppression: primary/complementary, differencing, overlapping filters, repeated query, cross-cycle inference and ledger restart/multi-worker behavior using synthetic populations.
- Browser: active V2 session present but omitted from anonymous submit; required/allowed choice validation; correct version binding; durable SQLite verification on reopen; no localStorage, URL, analytics, or browser-log secret persistence.
- Artifact: production Docker images exclude `backend/prototypes`, E2E harness/route and synthetic codes; production app has no test API route; test API requires explicit temp-only DB guard.

## 9. Approval decisions from №5 / owners

1. Choose token architecture A or B and approve the threat model/residual correlation risk.
2. Approve exact additive v4 tables/API and a migration owner; confirm migration must not alter schema-3 semantics or `demo-v1`.
3. Resolve Form 2 audience and category mapping; until then no routing.
4. Approve immutable template publication/versioning and who can publish/edit drafts.
5. Set `k`, category semantics, suppression rules, disclosure-ledger budget and whether any aggregates are allowed.
6. Set raw-answer, code-state, log, backup, WAL, export and audit retention and approve restore/purge runbook.
7. Approve anonymous origin, CORS, proxy logging, rate limiting and incident response.
8. V2 Auth owner must implement session invalidation on privilege change and fresh 2FA; then approve expert grant/assignment governance.
9. Provide the exact Windows schema-3 artifact and clean-install scripts for compatibility testing.

Until these decisions and tests are complete, status remains **PRODUCTION INTEGRATION: NO-GO**.
