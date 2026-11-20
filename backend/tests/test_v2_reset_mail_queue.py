"""
Запит коду скидання пароля не розкриває існування акаунта часом відповіді (app/v2_mail_queue.py):
маршрут лише ставить завдання у фонову чергу, а пошук акаунта, ліміти й лист (повільний SMTP) — у воркері.
Пошта фейкова: deliver_mail підміняється функцією із затримкою 0,5 с, нікуди нічого не надсилається.
"""
import logging
import sqlite3
import statistics
import threading
import time
from contextlib import closing

import pytest

from app import v2_auth, v2_mail_queue
from app.v2_auth import MailDeliveryError, auth_db_path, find_user_id, latest_dev_mail

from v2_helpers import PASSWORD, make_user, new_email, preauth_client, wait_mail_queue

SMTP_DELAY = 0.5
OK_BODY = {"status": "sent_if_account_exists"}


def reset_post(email: str, ip: str):
    """Лише POST вимірюється: CSRF-токен отримано заздалегідь."""
    client, preauth = preauth_client(client=(ip, 40000))
    started = time.perf_counter()
    response = client.post("/v2/auth/password-reset/request", json={"email": email},
                           headers={"X-CSRF-Token": preauth})
    return response, time.perf_counter() - started


def reset_codes(user_id: int) -> int:
    with closing(sqlite3.connect(auth_db_path())) as db:
        return db.execute("SELECT COUNT(*) FROM v2_challenges WHERE user_id = ? AND purpose = 'password_reset'",
                          (user_id,)).fetchone()[0]


@pytest.fixture
def slow_smtp(monkeypatch):
    """Фейковий повільний SMTP: затримка 0,5 с, запам'ятовує лише адресатів."""
    sent: list[str] = []

    def deliver(recipient: str, subject: str, body: str) -> None:
        time.sleep(SMTP_DELAY)
        sent.append(recipient)
    monkeypatch.setattr(v2_auth, "deliver_mail", deliver)
    return sent


def test_reset_response_time_does_not_depend_on_account_existence(slow_smtp):
    known_times, unknown_times, known_emails = [], [], []
    for i in range(4):                       # чергуємо, щоб фонова робота воркера впливала на обидві групи
        email = make_user()
        known_emails.append(email)
        known, known_time = reset_post(email, f"198.18.20.{i + 1}")
        unknown, unknown_time = reset_post(new_email(), f"198.18.21.{i + 1}")
        assert (known.status_code, known.json()) == (unknown.status_code, unknown.json()) == (200, OK_BODY)
        assert known.headers.get("content-length") == unknown.headers.get("content-length")
        known_times.append(known_time)
        unknown_times.append(unknown_time)
    # Обидві відповіді швидкі: SMTP (0,5 с) не на шляху запиту, а медіани не відрізняються.
    # Синхронний лист дав би для наявного email щонайменше SMTP_DELAY.
    assert max(known_times + unknown_times) < SMTP_DELAY, (known_times, unknown_times)
    assert abs(statistics.median(known_times) - statistics.median(unknown_times)) < 0.1
    # Лист для наявних акаунтів таки надсилається — у фоні.
    wait_mail_queue()
    assert sorted(slow_smtp) == sorted(known_emails)
    assert all(reset_codes(find_user_id(email)) == 1 for email in known_emails)


def test_background_mail_is_sent_only_for_existing_account(slow_smtp):
    email = make_user()
    reset_post(email, "198.18.22.1")
    reset_post(new_email(), "198.18.22.1")
    assert slow_smtp == []                   # відповідь отримано раніше, ніж лист
    wait_mail_queue()
    assert slow_smtp == [email]
    assert reset_codes(find_user_id(email)) == 1


def test_email_ip_limit_still_applies_in_background():
    email = make_user()
    bodies = {reset_post(email, "198.18.23.1")[0].text for _ in range(5)}
    wait_mail_queue()
    assert bodies == {'{"status":"sent_if_account_exists"}'}
    assert reset_codes(find_user_id(email)) == 3          # 3 за 15 хв на (email, IP)
    reset_post(email, "198.18.23.2")                      # інший IP — новий код
    wait_mail_queue()
    assert reset_codes(find_user_id(email)) == 4


def test_queue_overflow_drops_job_without_changing_response(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="app.v2_mail")
    small = v2_mail_queue.MailQueue(maxsize=1)
    monkeypatch.setattr(v2_mail_queue, "mail_queue", small)
    release, started = threading.Event(), threading.Event()

    def blocker() -> None:
        started.set()
        release.wait(10)
    assert small.submit(blocker) and started.wait(5)       # воркер зайнятий
    assert small.submit(lambda: None)                      # черга (1 місце) заповнена
    email = make_user()
    full, _ = reset_post(email, "198.18.24.1")
    unknown, _ = reset_post(new_email(), "198.18.24.1")
    release.set()
    assert small.wait_idle(timeout=10)
    assert (full.status_code, full.json()) == (unknown.status_code, unknown.json()) == (200, OK_BODY)
    assert reset_codes(find_user_id(email)) == 0          # завдання відкинуто
    assert "переповнена" in caplog.text and email not in caplog.text


def test_smtp_error_is_logged_without_details(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="app.v2_mail")
    email = make_user()

    def broken(recipient: str, subject: str, body: str) -> None:
        raise MailDeliveryError(f"smtp.example.test refused {recipient}")
    monkeypatch.setattr(v2_auth, "deliver_mail", broken)
    response, _ = reset_post(email, "198.18.25.1")
    wait_mail_queue()
    assert (response.status_code, response.json()) == (200, OK_BODY)
    assert reset_codes(find_user_id(email)) == 0          # код не збережено без листа
    assert "MailDeliveryError" in caplog.text
    assert email not in caplog.text and "smtp.example.test" not in caplog.text


def test_login_2fa_mail_is_still_sent_synchronously():
    """Лист 2FA надсилається під час входу після перевірки пароля (не через чергу) — як раніше."""
    email = make_user()
    client, preauth = preauth_client()
    response = client.post("/v2/auth/login", json={"email": email, "password": PASSWORD},
                           headers={"X-CSRF-Token": preauth})
    assert response.status_code == 200 and response.json()["requires_2fa"] is True
    mail = latest_dev_mail(email)                          # без очікування черги
    assert mail is not None and "код підтвердження" in mail["subject"]
