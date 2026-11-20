# V2 Assessment Manager schema 3 — API contract addendum

Status: local integration candidate, 2026-11-20. This documents implemented source behavior; Windows runtime and production acceptance are pending.

## Authentication and roles

`POST /api/assessments` and `POST /api/assessments/{id}/activate` require a V2 `admin` session with completed 2FA. Cookie-authenticated write requests require the session CSRF token and an allowed Origin/Referer. `X-Role` is development-only and forbidden by release configuration. Public GETs and anonymous code submissions retain their existing contracts.

## Create assessment

`POST /api/assessments` returns 201 and a new `draft` assessment. JSON fields:

| Field | Rule |
| --- | --- |
| `name` | Required, nonblank, 1–50 characters |
| `description` | Optional, at most 2000 characters |
| `scope` | Optional, at most 200 characters |
| `start_date` | Required ISO date |
| `end_date` | Optional ISO date, no earlier than `start_date` |
| `categories` | Required unique list, 1–4 of `mgmt`, `npp`, `cadets`, `staff` |
| `min_group_size` | Strict integer from 5 to 1000 |
| `questionnaire_version` | Currently only `demo-v1` |

Example body: `{"name":"Synthetic 2026-II","start_date":"2026-11-20","categories":["npp","cadets"],"min_group_size":5,"questionnaire_version":"demo-v1"}`.

Response includes `id`, `name`, `start_date`, `status`, `min_group_size`, `description`, `scope`, `end_date`, `categories`, `questionnaire_version`. Invalid input returns 422; missing/insufficient session returns 401/403. Successful creation writes `assessment.create` to the audit trail in the same main-DB transaction.

## Activate assessment

`POST /api/assessments/{id}/activate` returns the assessment with `status=open`. Only `draft` may be activated; otherwise 409. Missing ID returns 404. Successful activation writes `assessment.activate` in the same transaction. Existing list/detail GETs include the extra schema-3 fields. Existing token issuance, submissions, close, participation and results routes retain their contracts.

## Persistence

Main SQLite schema version is `PRAGMA user_version=3`; `cycle_configs` carries description, scope, end date, category list, and questionnaire version. Existing schema-2 DBs require the separately gated migration and verified backup. Auth SQLite remains version 1 in this integration candidate. No official questionnaire content is included; `demo-v1` uses synthetic content only.
