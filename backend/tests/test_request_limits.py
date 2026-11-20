"""
Обмеження вхідних даних (docs/V2_HARDENING_CONTRACT.md, розділ 3; аудит D2 і D8):
ліміт тіла (413 до читання всього тіла), 422 без `input`/`ctx`, цілі id лише 1..2^63-1.
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import ResponseSet
from app.request_limits import DEFAULT_MAX_BODY_BYTES, MAX_ID, BodySizeLimitMiddleware, max_body_bytes

client = TestClient(app)
ADMIN = {"X-Role": "admin"}
DATA_OFFICER = {"X-Role": "data_officer"}
OPEN_ID = 3


def responses_count() -> int:
    with SessionLocal() as db:
        return db.query(ResponseSet).count()


# --- D2: ліміт тіла --------------------------------------------------------------

def test_default_limit_is_64_kib(monkeypatch):
    monkeypatch.delenv("V2_MAX_BODY_BYTES", raising=False)
    assert max_body_bytes() == DEFAULT_MAX_BODY_BYTES == 65536


@pytest.mark.parametrize("bad", ["0", "-1", "64k", "1.5"])
def test_invalid_limit_setting_is_refused(monkeypatch, bad):
    monkeypatch.setenv("V2_MAX_BODY_BYTES", bad)
    with pytest.raises(RuntimeError, match="V2_MAX_BODY_BYTES"):
        max_body_bytes()


def test_anonymous_body_over_limit_is_rejected_with_413_and_nothing_saved():
    before = responses_count()
    big = json.dumps({"token": "x", "respondent_category": "cadets", "unit": "A" * (1024 * 1024),
                      "answers": [{"question_id": 1, "value": 3}]})
    response = client.post(f"/api/assessments/{OPEN_ID}/submissions", content=big,
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert len(response.content) < 200 and "AAAA" not in response.text      # тіло не віддзеркалюється
    assert response.headers["connection"] == "close"
    assert responses_count() == before


def test_limit_applies_before_authentication_and_routing():
    big = b"{" + b" " * (DEFAULT_MAX_BODY_BYTES + 1) + b"}"
    for path in ("/api/assessments", "/v2/auth/login", "/no-such-route"):
        response = client.post(path, content=big, headers={"Content-Type": "application/json"})
        assert response.status_code == 413, path


def test_limit_is_configurable(monkeypatch):
    monkeypatch.setenv("V2_MAX_BODY_BYTES", "100")
    response = client.post(f"/api/assessments/{OPEN_ID}/submissions", json={"token": "x" * 200})
    assert response.status_code == 413


def test_body_within_limit_reaches_application():
    response = client.post(f"/api/assessments/{OPEN_ID}/submissions", json={"token": "x"})
    assert response.status_code == 422          # дійшло до валідації анкети


def _run_middleware(chunks: list[bytes], headers=()):
    """Прямий ASGI-виклик: скільки частин тіла прочитано, що надіслано, чи викликано застосунок."""
    state = {"read": 0, "called": False, "app_body": None}
    sent = []

    async def receive():
        index = state["read"]
        state["read"] += 1
        return {"type": "http.request", "body": chunks[index], "more_body": index < len(chunks) - 1}

    async def send(message):
        sent.append(message)

    async def application(scope, receive_body, send_response):
        state["called"] = True
        message = await receive_body()
        state["app_body"] = message["body"]
        await send_response({"type": "http.response.start", "status": 204, "headers": []})
        await send_response({"type": "http.response.body", "body": b""})

    scope = {"type": "http", "method": "POST", "path": "/api/x", "headers": list(headers)}
    asyncio.run(BodySizeLimitMiddleware(application)(scope, receive, send))
    return state, sent


def test_chunked_body_is_cut_off_at_limit_without_reading_the_rest():
    """Без Content-Length (chunked): лічильник обриває читання щойно сума > ліміту — решта не читається."""
    chunk = b"x" * 1024
    state, sent = _run_middleware([chunk] * 30_000)          # ~30 МБ, як у аудиті
    assert sent[0]["status"] == 413
    assert state["called"] is False
    assert state["read"] == DEFAULT_MAX_BODY_BYTES // len(chunk) + 1


def test_declared_content_length_over_limit_is_rejected_without_reading():
    state, sent = _run_middleware([b"{}"], headers=[(b"content-length", str(10 * 1024 * 1024).encode())])
    assert sent[0]["status"] == 413 and state["read"] == 0 and state["called"] is False


def test_small_chunked_body_is_passed_to_application_whole():
    state, sent = _run_middleware([b'{"a":', b'1', b'}'])
    assert state["called"] is True and state["app_body"] == b'{"a":1}' and sent[0]["status"] == 204


# --- D2: 422 без input і ctx ---------------------------------------------------------

def test_validation_error_does_not_echo_input():
    secret_like = "A" * 5000
    response = client.post(f"/api/assessments/{OPEN_ID}/submissions",
                           json={"token": "synthetic", "respondent_category": "cadets", "unit": secret_like,
                                 "answers": [{"question_id": 1, "value": "4"}]})
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert errors and all(set(error) == {"loc", "msg", "type"} for error in errors)
    assert "AAAAAAAAAA" not in response.text and '"input"' not in response.text and '"ctx"' not in response.text
    assert len(response.content) < 2000


def test_invalid_json_error_does_not_echo_body():
    response = client.post(f"/api/assessments/{OPEN_ID}/submissions", content=b'{"token": "leak-me-' + b"z" * 500,
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert "leak-me" not in response.text and "zzzz" not in response.text


def test_long_unknown_keys_are_truncated_in_loc():
    long_key = "k" * 1000
    response = client.post("/api/assessments", headers=ADMIN, json={long_key: 1})
    assert response.status_code == 422
    assert long_key not in response.text


# --- D8: цілі id поза 1..2^63-1 → 422, а не 500 ------------------------------------

HUGE = "99999999999999999999"
ROUTES_WITH_IDS = [
    ("get", f"/api/assessments/{HUGE}", {}),
    ("get", f"/api/assessments/{HUGE}/questionnaires", {}),
    ("post", f"/api/assessments/{HUGE}/submissions", {}),
    ("post", f"/api/assessments/{HUGE}/activate", ADMIN),
    ("post", f"/api/assessments/{HUGE}/close", ADMIN),
    ("post", f"/api/assessments/{HUGE}/tokens", DATA_OFFICER),
    ("get", f"/api/assessments/{HUGE}/participation", ADMIN),
    ("get", f"/api/assessments/{HUGE}/results", ADMIN),
    ("get", f"/api/assessments/{HUGE}/index?methodology=team-results-demo-0.1", ADMIN),
    ("get", f"/api/assessments/{HUGE}/recommendations?methodology=team-results-demo-0.1", ADMIN),
    ("get", f"/api/analytics/comparisons?methodology=team-results-demo-0.1&assessment_id={HUGE}", ADMIN),
    ("get", f"/api/analytics/comparisons?methodology=team-results-demo-0.1&assessment_id=1"
            f"&comparison_assessment_id={HUGE}", ADMIN),
    ("get", f"/api/audit-events?assessment_id={HUGE}", ADMIN),
    ("get", f"/api/assessments/{HUGE}/tracker", ADMIN),
    ("post", f"/api/assessments/{HUGE}/tracker/decisions", ADMIN),
    ("post", f"/api/tracker/{HUGE}/transition", ADMIN),
]


@pytest.mark.parametrize("method, path, headers", ROUTES_WITH_IDS)
def test_huge_integer_ids_give_422_not_500(monkeypatch, method, path, headers):
    monkeypatch.setenv("INTEGRITY_ANALYTICS_DEMO", "1")
    response = TestClient(app, raise_server_exceptions=False).request(method, path, headers=headers, json={})
    assert response.status_code == 422, (path, response.status_code, response.text[:200])
    assert HUGE not in response.text


@pytest.mark.parametrize("value, status", [("0", 422), ("-1", 422), (str(MAX_ID + 1), 422), (str(MAX_ID), 404)])
def test_id_boundaries(value, status):
    assert client.get(f"/api/assessments/{value}").status_code == status
    assert client.get("/api/audit-events", params={"assessment_id": value}, headers=ADMIN).status_code == \
        (200 if status == 404 else 422)
