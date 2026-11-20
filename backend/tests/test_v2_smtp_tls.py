"""
SMTP STARTTLS: перевірка сертифіката й hostname (завдання №5 після SMTP E2E QA №4).

Сервер — локальний фейковий SMTP на 127.0.0.1, сертифікати генерує trustme в пам'яті.
Жодних справжніх SMTP-реквізитів: логін і пароль синтетичні, пошта нікуди не виходить.
Продакшн-контекст (smtp_tls_context) не послаблюється: у тестах до нього лише додається
довіра до тестового CA — CERT_REQUIRED і check_hostname лишаються як є.
"""
import base64
import re
import socket
import sqlite3
import ssl
import threading

import pytest
import trustme

from app import v2_auth
from app.v2_auth import MailDeliveryError, auth_db_path, deliver_mail, smtp_tls_context

from v2_helpers import PASSWORD, make_user, preauth_client

SYNTHETIC_USER = "synthetic-smtp-user"
SYNTHETIC_PASSWORD = "synthetic-smtp-password"


class FakeSMTPServer:
    """Мінімальний SMTP (EHLO, STARTTLS, AUTH PLAIN, MAIL/RCPT/DATA) для одного з'єднання за раз.
    implicit=True — TLS з першого байта (SMTPS, V2_SMTP_TLS_MODE=implicit)."""

    def __init__(self, cert: trustme.LeafCert | None, offer_starttls: bool = True, implicit: bool = False):
        self.offer_starttls = offer_starttls and not implicit
        self.implicit = implicit
        self.server_context = None
        if cert is not None:
            self.server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            cert.configure_cert(self.server_context)
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.messages: list[str] = []
        self.auth_before_tls = False
        self.auth_seen = False
        self.tls_established = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.listener.close()
        self._thread.join(timeout=5)

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            try:
                self._handle(conn)
            except (OSError, ssl.SSLError):
                pass   # клієнт відмовився від TLS — очікувано в негативних тестах
            finally:
                conn.close()

    def _handle(self, conn: socket.socket) -> None:
        tls = False
        if self.implicit:
            conn = self.server_context.wrap_socket(conn, server_side=True)
            tls = self.tls_established = True
        reader = conn.makefile("rb")

        def send(line: str) -> None:
            conn.sendall((line + "\r\n").encode())

        send("220 fake-smtp ready")
        while True:
            raw = reader.readline()
            if not raw:
                return
            line = raw.decode().rstrip("\r\n")
            verb = line.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                extensions = ["AUTH PLAIN"]
                if self.offer_starttls and not tls:
                    extensions.append("STARTTLS")
                lines = ["fake-smtp"] + extensions
                for item in lines[:-1]:
                    send(f"250-{item}")
                send(f"250 {lines[-1]}")
            elif verb == "STARTTLS" and self.offer_starttls and not tls:
                send("220 go ahead")
                conn = self.server_context.wrap_socket(conn, server_side=True)
                reader = conn.makefile("rb")
                tls = True
                self.tls_established = True
            elif verb == "AUTH":
                self.auth_seen = True
                if not tls:
                    self.auth_before_tls = True
                send("235 ok")
            elif verb in ("MAIL", "RCPT"):
                send("250 ok")
            elif verb == "DATA":
                send("354 end with .")
                body = []
                while True:
                    data_line = reader.readline().decode()
                    if data_line in (".\r\n", ".\n", ""):
                        break
                    body.append(data_line)
                self.messages.append("".join(body))
                send("250 queued")
            elif verb == "QUIT":
                send("221 bye")
                return
            else:
                send("502 not implemented")


@pytest.fixture(scope="module")
def ca() -> trustme.CA:
    return trustme.CA()


def trust_test_ca(monkeypatch, ca):
    """Справжній ssl.create_default_context() + довіра до тестового CA. Перевірки не вимикаються."""
    real_factory = ssl.create_default_context
    created: list[ssl.SSLContext] = []

    def factory(purpose=ssl.Purpose.SERVER_AUTH, *args, **kwargs):
        context = real_factory(purpose, *args, **kwargs)
        if purpose == ssl.Purpose.SERVER_AUTH:      # лише клієнтський контекст (як у deliver_mail)
            ca.configure_trust(context)
            created.append(context)
        return context

    monkeypatch.setattr(v2_auth.ssl, "create_default_context", factory)
    return created


@pytest.fixture
def trusted_ca(monkeypatch, ca):
    return trust_test_ca(monkeypatch, ca)


@pytest.fixture
def smtp_env(monkeypatch):
    def configure(server: FakeSMTPServer, host: str = "localhost") -> None:
        monkeypatch.setenv("V2_AUTH_DEV_MAIL", "0")
        monkeypatch.setenv("V2_SMTP_HOST", host)
        monkeypatch.setenv("V2_SMTP_PORT", str(server.port))
        monkeypatch.setenv("V2_SMTP_USER", SYNTHETIC_USER)
        monkeypatch.setenv("V2_SMTP_PASSWORD", SYNTHETIC_PASSWORD)
        monkeypatch.setenv("V2_SMTP_FROM", "no-reply@example.test")
    return configure


@pytest.fixture
def servers():
    started: list[FakeSMTPServer] = []

    def start(*args, **kwargs) -> FakeSMTPServer:
        server = FakeSMTPServer(*args, **kwargs)
        started.append(server)
        return server
    yield start
    for server in started:
        server.close()


def test_tls_context_verifies_certificate_and_hostname():
    context = smtp_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_valid_certificate_delivers_mail_over_tls(ca, trusted_ca, smtp_env, servers):
    server = servers(ca.issue_cert("localhost"))
    smtp_env(server)
    deliver_mail("user@example.test", "Тема", "Ваш код: 123456.")
    assert server.tls_established and server.auth_seen and not server.auth_before_tls
    assert len(server.messages) == 1
    # Контекст, переданий у starttls, — з увімкненими перевірками
    assert trusted_ca and all(c.verify_mode == ssl.CERT_REQUIRED and c.check_hostname for c in trusted_ca)


def test_untrusted_certificate_is_refused(smtp_env, servers):
    # Без trust_test_ca: діє продакшн-контекст лише із системними CA — самопідписаний CA недовірений
    untrusted_ca = trustme.CA()
    server = servers(untrusted_ca.issue_cert("localhost"))
    smtp_env(server)
    with pytest.raises(MailDeliveryError) as error:
        deliver_mail("user@example.test", "Тема", "Ваш код: 123456.")
    assert isinstance(error.value.__cause__, ssl.SSLCertVerificationError)
    assert not server.auth_seen and not server.messages


def test_certificate_from_other_trusted_ca_chain_is_refused(ca, trusted_ca, smtp_env, servers):
    other_ca = trustme.CA()                       # довіряємо лише `ca`, сертифікат підписано іншим CA
    server = servers(other_ca.issue_cert("localhost"))
    smtp_env(server)
    with pytest.raises(MailDeliveryError) as error:
        deliver_mail("user@example.test", "Тема", "Ваш код: 123456.")
    assert isinstance(error.value.__cause__, ssl.SSLCertVerificationError)
    assert not server.auth_seen and not server.messages


def test_hostname_mismatch_is_refused(ca, trusted_ca, smtp_env, servers):
    server = servers(ca.issue_cert("mail.example.test"))   # довірений CA, але інше ім'я
    smtp_env(server, host="localhost")
    with pytest.raises(MailDeliveryError) as error:
        deliver_mail("user@example.test", "Тема", "Ваш код: 123456.")
    cause = error.value.__cause__
    assert isinstance(cause, ssl.SSLCertVerificationError) and "hostname" in str(cause).lower()
    assert not server.auth_seen and not server.messages


def test_server_without_starttls_is_refused_without_sending_credentials(ca, trusted_ca, smtp_env, servers):
    server = servers(None, offer_starttls=False)
    smtp_env(server)
    with pytest.raises(MailDeliveryError):
        deliver_mail("user@example.test", "Тема", "Ваш код: 123456.")
    assert not server.auth_seen and not server.auth_before_tls and not server.messages


def _challenge_count() -> int:
    with sqlite3.connect(auth_db_path()) as con:
        return con.execute("SELECT COUNT(*) FROM v2_challenges").fetchone()[0]


def test_login_and_2fa_work_through_verified_smtp(ca, trusted_ca, smtp_env, servers):
    server = servers(ca.issue_cert("localhost"))
    smtp_env(server)
    email = make_user()
    client, preauth = preauth_client()
    response = client.post("/v2/auth/login", json={"email": email, "password": PASSWORD},
                           headers={"X-CSRF-Token": preauth})
    assert response.status_code == 200, response.text
    pending_csrf = response.json()["csrf_token"]
    assert server.tls_established and len(server.messages) == 1
    match = re.search(r"\b(\d{6})\b", server.messages[0])
    if match is None:                              # тіло листа може бути закодоване (UTF-8 → base64)
        payload = server.messages[0].split("\r\n\r\n", 1)[1].replace("\r\n", "")
        match = re.search(r"\b(\d{6})\b", base64.b64decode(payload).decode())
    response = client.post("/v2/auth/2fa/verify", json={"code": match.group(1)},
                           headers={"X-CSRF-Token": pending_csrf})
    assert response.status_code == 200, response.text
    assert client.get("/v2/auth/me").json()["requires_2fa"] is False


@pytest.mark.parametrize("case", ["untrusted", "hostname", "no_starttls"])
def test_login_fails_safely_when_smtp_tls_is_not_trusted(ca, smtp_env, servers, monkeypatch, case):
    if case == "untrusted":
        server = servers(trustme.CA().issue_cert("localhost"))
    elif case == "hostname":
        server = servers(ca.issue_cert("mail.example.test"))
    else:
        server = servers(None, offer_starttls=False)
    if case != "untrusted":
        trust_test_ca(monkeypatch, ca)
    smtp_env(server)
    email = make_user()
    before = _challenge_count()
    client, preauth = preauth_client()
    response = client.post("/v2/auth/login", json={"email": email, "password": PASSWORD},
                           headers={"X-CSRF-Token": preauth})
    assert response.status_code == 503
    assert "localhost" not in response.text and str(server.port) not in response.text
    assert _challenge_count() == before            # код не збережено, коли лист не надіслано
    assert client.get("/v2/auth/me").status_code == 401   # сесію не створено
    assert not server.auth_seen and not server.messages


def test_password_reset_response_is_unchanged_when_smtp_tls_fails(smtp_env, servers):
    server = servers(trustme.CA().issue_cert("localhost"))
    smtp_env(server)
    email = make_user()
    client, preauth = preauth_client()
    response = client.post("/v2/auth/password-reset/request", json={"email": email},
                           headers={"X-CSRF-Token": preauth})
    assert response.status_code == 200
    assert response.json() == {"status": "sent_if_account_exists"}


# --- A17: заголовки листа і неявний TLS (V2_SMTP_TLS_MODE=implicit) ------------------------------------------

def test_message_has_date_and_message_id_headers(ca, trusted_ca, smtp_env, servers):
    server = servers(ca.issue_cert("localhost"))
    smtp_env(server)
    deliver_mail("user@example.test", "Тема", "Ваш код: 123456.")
    headers = re.split(r"\r?\n\r?\n", server.messages[0], maxsplit=1)[0]
    assert re.search(r"^Date: \w{3}, \d{1,2} \w{3} \d{4} \d\d:\d\d:\d\d ([+-]0000|GMT)\r?$", headers, re.MULTILINE)
    assert re.search(r"^Message-ID: <[^@>]+@example\.test>\r?$", headers, re.MULTILINE)
    assert re.search(r"^From: no-reply@example\.test\r?$", headers, re.MULTILINE)


def test_implicit_tls_delivers_mail_with_verified_context(ca, trusted_ca, smtp_env, servers, monkeypatch):
    server = servers(ca.issue_cert("localhost"), implicit=True)
    smtp_env(server)
    monkeypatch.setenv("V2_SMTP_TLS_MODE", "implicit")
    deliver_mail("user@example.test", "Тема", "Ваш код: 123456.")
    assert server.tls_established and server.auth_seen and not server.auth_before_tls
    assert len(server.messages) == 1
    assert trusted_ca and all(c.verify_mode == ssl.CERT_REQUIRED and c.check_hostname for c in trusted_ca)


@pytest.mark.parametrize("case", ["untrusted", "hostname"])
def test_implicit_tls_refuses_untrusted_certificate(ca, smtp_env, servers, monkeypatch, case):
    if case == "untrusted":
        server = servers(trustme.CA().issue_cert("localhost"), implicit=True)
    else:
        trust_test_ca(monkeypatch, ca)
        server = servers(ca.issue_cert("mail.example.test"), implicit=True)
    smtp_env(server)
    monkeypatch.setenv("V2_SMTP_TLS_MODE", "implicit")
    with pytest.raises(MailDeliveryError) as error:
        deliver_mail("user@example.test", "Тема", "Ваш код: 123456.")
    assert isinstance(error.value.__cause__, ssl.SSLCertVerificationError)
    assert not server.auth_seen and not server.messages


def test_unknown_tls_mode_sends_nothing(ca, trusted_ca, smtp_env, servers, monkeypatch):
    server = servers(ca.issue_cert("localhost"))
    smtp_env(server)
    monkeypatch.setenv("V2_SMTP_TLS_MODE", "none")
    with pytest.raises(v2_auth.MailNotConfigured):
        deliver_mail("user@example.test", "Тема", "Ваш код: 123456.")
    assert not server.messages
