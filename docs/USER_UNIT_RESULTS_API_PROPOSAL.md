# API proposal: user-scoped unit aggregates

**Status:** proposal only; not implemented or approved. No frontend request is made until #5 approves the contract and backend provides the endpoint.

## Current gap

The verified user session does not contain a server-validated unit association. The current user API exposes profile, available personal assessments, the signed-in user's own attempts/history/results/stats, and no organization or unit aggregates. The admin participation endpoint reports aggregate participation only; it does not return C1–C7 results and is not a user endpoint. The UI therefore shows a protected `BLOCKED` state and does not infer unit membership or reuse organization-wide analytics.

## Proposed read contract

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

1. Which authoritative table/service establishes a user's unit, who can update it, and can a user belong to multiple units?
2. Which approved `k` and complementary suppression rules apply to components and any total counts?
3. Should the unit be fixed at assessment close, or resolved using membership as of another defined date?
4. Which response/status shape avoids leaking whether a cycle or unit exists while distinguishing access denial from unavailable aggregates?
5. Which methodology version and cycle comparability requirements govern these aggregates?

## Acceptance conditions before frontend integration

- Approved API contract and reviewed threat model.
- Backend tests for ownership, role checks, closed-cycle restriction, primary and complementary suppression, and query-differencing resistance.
- Synthetic-data regression evidence with no individual answers in responses or logs.
