# Questionnaire API adapter report

**Status: isolated executable prototype; not mounted in `app.main`, not a production API.** The test app is created only through `create_integration_test_app` and uses a temporary synthetic schema-3 copy.

## Implemented and tested

- Separate cycle-to-template/version binding. Binding is accepted only while a cycle is draft; the binding is frozen after activation.
- Submission checks open cycle, exact binding, allowed category, template/version/question/option validity, required answers, code cycle/category/unused/expiry state, and request size/schema.
- One SQLite `BEGIN IMMEDIATE` transaction rechecks cycle and token, inserts the separate official response set and answers, marks the existing access token used, and commits. Failure injection at answer insert confirms rollback leaves no partial set and the code unused.
- Competing close/submit uses the same SQLite write lock. Concurrent same-code submission accepts exactly one request.
- Numeric `response_sets`/`answers` are untouched. Official answer tables have no respondent/user/token ID, code, IP, user agent, exact timestamp, or FK to token; client success response does not expose the random response-set ID.
- Generic errors do not echo codes/answers. Anonymous submission rejects Cookie/Authorization. The prototype logs only fixed event names.

## Result

Targeted suite: **25 passed, 1 warning** (Starlette `TestClient`/httpx deprecation), command `..\audit-venv\Scripts\python.exe -m pytest backend/tests/test_questionnaire_integration_prototype.py -q` from `backend`, with local TestClient sockets permitted.

Full backend suite after final hardening: **409 passed, 1 warning** in 88.89 seconds (`python -m pytest -q` from `backend`). Frontend: **45 passed**; TypeScript + production build: **PASS**; browser E2E with temporary synthetic SQLite: **12 passed**. Frontend test output included a non-failing warning that WebSocket port 24678 was already in use; all assertions passed.

## Compatibility limits

The prototype uses actual `access_tokens`/`access_token_policies` and `cycles(id)` but stores its questionnaire binding separately. It does not change `cycle_configs.questionnaire_version`, numeric APIs, Dashboard, Analytics, or scoring. Version fixtures are prototype fixtures; this does not approve production questionnaire routing. There is intentionally no production aggregate/participation endpoint, no response retrieval route, no request-body logging, and no implementation of distributed rate limiting. A real reverse proxy/access logger configuration was not available for validation.
