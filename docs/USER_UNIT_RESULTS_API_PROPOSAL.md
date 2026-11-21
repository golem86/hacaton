# API proposal: user-scoped unit aggregates

> **Статус (укр.):** реалізовано й злито в `main` (`48256d6`, зафіксований код `6629c74`), integrity schema 7, таблиця `user_units`; працює на робочому сервері. Опис для журі українською — [anonymity.md](anonymity.md), розділ 4.6.

**Status:** implemented and integrated into `feature/integration` (INTEGRITY_DB schema 7, table `user_units`). Decisions taken for the open questions are recorded below in «Implementation decisions»; they still need team (#5/#2) confirmation before release. The sections «Current gap», «Proposed read contract» and «Questions» are the original proposal kept for history; where they differ, «Implementation decisions», `docs/API_CONTRACT.md` and the code win.

## Implementation decisions (answers to the questions below)

1. **Membership source.** Table `user_units` in INTEGRITY_DB (schema 7): `user_id` (primary key; the V2_AUTH_DB user id, no foreign key because it is a separate database), `unit` → `units.name`, `assigned_at`; one unit per user, no link to `response_sets`. Only the server owner assigns or clears it, from `backend`: `python -m app.v2_unit_cli list-units`, `python -m app.v2_unit_cli set-unit --email <email> --unit "<name from units>" [--confirm]`, `python -m app.v2_unit_cli clear-unit --email <email> [--confirm]`. Without `--confirm` only a plan is printed and the database is not changed; the schema is checked, never migrated. Exit codes: `0` done or plan, `2` refused (unknown user, unit not in `units`, or no change), `1` error. No web route — neither the user nor the admin can choose a unit. Each change writes audit event `user.unit_change` (`actor_role` `server`, `actor_user_id` null, `details` `{}` — no email, id or unit name).
2. **k and complementary suppression.** `k = cycles.min_group_size` (≥ 5). Results are shown only if (a) the user's unit has ≥ k responses **and** (b) in the whole cycle every non-empty «category × unit» cell has ≥ k responses. Rule (b) is global on purpose: unit scores (seen by different users), category scores (`/results`, management) and the cycle total are all sums over cells of the same table, so any differencing between them (several users from different units colluding, a user moved between units, or one user plus management) yields only a sum of whole cells — each ≥ k people. An independent review reproduced recovery of one manager's C1–C7 scores with an earlier, weaker rule («unit ≥ k and rest of cycle ≥ k»); that is now a regression test. The response count is rounded down to a multiple of 5, empty and small units return identical bodies, no category breakdown and no client filters. Consequence: if the cycle has any small cell (e.g. 1–4 managers scattered over units), no unit results are shown for that cycle at all.
3. **Membership date.** Resolved at request time (current assignment). Reassignment is a server-owner action recorded in the audit log; thanks to rule 2(b) seeing several units of the same cycle reveals only whole-cell aggregates. Residual: k−1 colluding members of one unit can subtract their own answers (same as for any k-threshold aggregate).
4. **Status shape.** Role `user` only (`require_v2_role("user")`; `admin`/`data_officer` → `403`, no session or no 2FA → `401`). `404` unknown or draft cycle (identical), `409` open cycle (cycle list is public anyway), `422` missing or out-of-range `assessment_id`. `200` body: `assessment {id, name, status}`, `unit` (unit name as a string, or null), `methodology_version`, `min_group_size`, `privacy_status`, `responses`, `components[{code, name, score, status}]` (all components ordered by code, `score` 0–100 rounded to 0.1). `privacy_status` = `available` (`responses` rounded down to a multiple of 5; component `status` = `available`, or `insufficient_data` with `score` null when the unit has no answers for that component) | `suppressed` (`unit` = the user's unit name, `responses` null, every component `score` null and `status` `suppressed`; empty and small units look the same) | `no_unit` (`unit` null, otherwise as `suppressed`). Known gap: `Cache-Control: no-store` is not set for this route (same as the other `/v2/user/*` routes).
5. **Methodology.** `methodology_version: "unit-mean-0-100-v1"` — the same formula as `/api/assessments/{id}/results`: mean of `(answer − scale_min) / (scale_max − scale_min) × 100` over survey questions of the component.

Implementation: `backend/app/services/unit_results.py`, route in `backend/app/routes/v2_user.py`, CLI `backend/app/v2_unit_cli.py`, tests `backend/tests/test_v2_unit_results.py`; frontend `frontend/src/v2/UnitResults.tsx`, `frontend/src/api/v2User.ts`, tests `frontend/tests/unit-results.test.mjs`.

## Current gap

*Historical: state before the implementation; no longer current.*

The verified user session does not contain a server-validated unit association. The current user API exposes profile, available personal assessments, the signed-in user's own attempts/history/results/stats, and no organization or unit aggregates. The admin participation endpoint reports aggregate participation only; it does not return C1–C7 results and is not a user endpoint. The UI therefore shows a protected `BLOCKED` state and does not infer unit membership or reuse organization-wide analytics.

## Proposed read contract

*Original proposal; the implemented contract is in «Implementation decisions» above and in `docs/API_CONTRACT.md`.*

`GET /v2/user/unit-results?assessment_id={id}`

- Authentication: verified V2 `user` session after 2FA; normal session cookie and request security protections.
- Authorization: the server resolves the user's current/authorized unit from a trusted membership source. The client must not send `unit_id`, unit name, role, or category as an authority input.
- Cycle: only a closed assessment. An open cycle returns a non-data response (suggest `409`).
- Data: aggregate counts and approved C1–C7 component aggregates only. Never return individual responses, answer rows, access tokens, or identifying metadata.
- Privacy: enforce the approved minimum group size `k` server-side for every returned aggregate; apply complementary suppression so totals or overlapping slices cannot reconstruct hidden groups. Repeated/filterable queries must not permit differencing attacks.
- Missing membership, not-found cycle, insufficient sample, and suppressed outputs must use responses that do not disclose another unit's existence or size. Exact status semantics need #5 and #2 approval.
- Response should include assessment `{id,name,status}`, methodology version, privacy status, and each component's `score: number | null` plus explicit status (`available`, `suppressed`, `insufficient_data`). Include a count only when independently safe to disclose.
- No endpoint for cross-unit comparison is proposed in this scope.

## Questions for #5 / #2

*Answered in «Implementation decisions» (pending team confirmation).*

1. Which authoritative table/service establishes a user's unit, who can update it, and can a user belong to multiple units?
2. Which approved `k` and complementary suppression rules apply to components and any total counts?
3. Should the unit be fixed at assessment close, or resolved using membership as of another defined date?
4. Which response/status shape avoids leaking whether a cycle or unit exists while distinguishing access denial from unavailable aggregates?
5. Which methodology version and cycle comparability requirements govern these aggregates?

## Acceptance conditions before frontend integration

- Approved API contract and reviewed threat model.
- Backend tests for ownership, role checks, closed-cycle restriction, primary and complementary suppression, and query-differencing resistance.
- Synthetic-data regression evidence with no individual answers in responses or logs.
