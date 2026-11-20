# Expert role and permission matrix

**Proposal plus isolated test evidence. No production role or grant table is enabled.** In V2 today, persisted roles are `user` and `admin`; prototype `expert` status is a separate explicit server-side grant plus assignment.

## Actions

| Action | User | Admin | Explicitly granted expert | Authorized reviewer | Server-side checks / 2FA / CSRF | Audit |
| --- | --- | --- | --- | --- | --- | --- |
| View official self questionnaire | Allowed only if cycle open and published | Same | Same | Same | Public catalog/cycle state; no privileged identity required | None |
| Submit anonymous official self answers | Anonymous code holder | Same; admin identity is not accepted on anonymous request | Same | Same | No cookie/Auth; code cycle/category/expiry/unused; exact template/version/options; atomic commit | Do not log code, answer, IP or respondent identity |
| Create/revoke expert grant | No | Authorized admin actor only; self-grant denied | No | No | V2 session + current admin role + 2FA + CSRF/Origin; target must be a current V2 user | `grant`, `revoke`, actor, target, event time |
| Assign/revoke a specific expert assessment | No | Authorized admin actor only | No | No | Current admin session/2FA/CSRF; active explicit grant; exact cycle/template/version | `assign`, `assignment_revoke` |
| Read/update/finalize assigned assessment | No, unless separately granted and assigned | Not by admin role alone | Yes, own active assignment only | No | Re-check session, 2FA, enabled grant, active assignment, principal ownership on each request; mutation requires CSRF/Origin and expected revision | `answers_updated`, `finalized`; no answer values |
| Read all expert assessments/raw anonymous answers | No | No automatic privilege | No | No | Not supported | None |
| Review approved aggregates | No | Only if separate aggregate policy grants it | No | Potential future scoped role | Requires separately approved suppression API and scope | Allowlisted aggregate access event if approved |

`authorized reviewer` is **not currently justified**: no approved review use case/API exists, and aggregate access must be designed separately. Do not add this role until #5 defines scope, approval, 2FA, audit and retention.

## `user → admin` in current V2 auth

Current `user_for_session()` reads the user's current role from V2 auth DB while retaining the session row's `two_factor_verified` flag. A temporary-auth-DB regression test confirmed that a previously 2FA-verified `user` promoted to `admin` can use the same still-live session for admin actions. There is no production role-change route in this WIP, and production auth was not changed.

**Required policy before production role promotion:** transactionally change role and revoke every existing session; require fresh login and 2FA at the new privilege level; review/revoke prior expert grants/assignments unless re-approved; audit the promotion actor, target and time. Demotion should likewise revoke sessions and active assignments/grants as policy requires. This needs the V2 auth owner/#5; not implemented here.

## Verified prototype behavior

- `X-Role` never grants authority; admin self-grant is rejected.
- A non-admin cannot grant or revoke, even with `X-Role: admin`.
- Every expert request checks real V2 cookie session, 2FA, active grant, active assignment and principal ID. Grant revoke deactivates assignments; the next request is denied without needing session invalidation.
- CSRF and Origin are required on mutating admin/expert routes. Stale revisions, repeated finalize and mutation after finalize fail.
- Audit changes occur in the same transaction as grant/assignment/answer/finalization updates and include event time/action allowlist without answer content.
- Adapter tests use only a temporary `V2_AUTH_DB`; production auth and role tables are untouched.
