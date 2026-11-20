"""
Налаштування режимів роботи backend (V2 Integration Contract).

APP_ENV:
  development — локальна розробка і тести (значення за замовчуванням);
  release     — будь-яке спільне чи production-середовище.

У release діють жорсткі правила, і сервер НЕ стартує, якщо конфігурація небезпечна
(див. validate_release_config):
  - X-Role не обробляється (INTEGRITY_DEMO_XROLE заборонено);
  - dev-mail з OTP вимкнено (V2_AUTH_DEV_MAIL заборонено);
  - cookie лише Secure з префіксом __Host- (HTTPS);
  - потрібен серверний секрет V2_SECRET_KEY (≥ 32 символи) для CSRF і HMAC одноразових кодів;
  - TRUSTED_PROXIES непорожній (IP клієнта для лімітів — лише через довірений reverse proxy);
  - V2_CATALOG_NOW заборонено (підміна часу — лише для тестів);
  - якщо задано V2_SMTP_HOST — потрібна справжня адреса V2_SMTP_FROM; V2_SMTP_TLS_MODE — starttls|implicit;
  - автоматичні міграції БД вимкнено (MIG-1);
  - V2_LM_URL (локальна LM, llama-server) — лише loopback: 127.0.0.1, ::1 або localhost.

Локальна LM для чернеток звітів (app/services/narrative.py):
  V2_LM_URL         — база OpenAI-сумісного llama-server, напр. http://127.0.0.1:8200; не задано → вимкнено;
  V2_LM_API_KEY     — необов'язковий Bearer-ключ до llama-server (--api-key);
  V2_LM_MODEL       — ім'я моделі в запиті (типово qwen3-8b);
  V2_LM_TIMEOUT_S   — таймаут одного запиту генерації, с (типово 300);
  V2_LM_MAX_TOKENS  — максимум токенів відповіді (типово 900).

Значення читаються з оточення під час кожного виклику, тож тести можуть
змінювати їх через monkeypatch.setenv без перезапуску застосунку.
"""
import os
import secrets
from email.utils import parseaddr
from urllib.parse import urlsplit

_DEV_SECRET = secrets.token_hex(32)   # лише для development: новий при кожному запуску
SMTP_TLS_MODES = ("starttls", "implicit")


def _flag(name: str) -> bool:
    return os.environ.get(name, "0") == "1"


def app_env() -> str:
    value = os.environ.get("APP_ENV", "development")
    if value not in {"development", "release"}:
        raise RuntimeError(f"APP_ENV має бути development або release, а не {value!r}")
    return value


def is_release() -> bool:
    return app_env() == "release"


def demo_xrole_enabled() -> bool:
    """Застарілий демо-заголовок X-Role. Лише development; у release заборонено."""
    return not is_release() and _flag("INTEGRITY_DEMO_XROLE")


def dev_mail_enabled() -> bool:
    """Локальна скринька листів з OTP. Лише development; у release заборонено."""
    return not is_release() and _flag("V2_AUTH_DEV_MAIL")


def secure_cookies() -> bool:
    """У release cookie завжди Secure; у development — за V2_AUTH_SECURE_COOKIE."""
    return is_release() or _flag("V2_AUTH_SECURE_COOKIE")


def auto_migrate() -> bool:
    """MIG-1: у release БД не змінюється автоматично під час старту."""
    return not is_release()


def secret_key() -> str:
    value = os.environ.get("V2_SECRET_KEY", "")
    if value:
        return value
    if is_release():
        raise RuntimeError("У release потрібен V2_SECRET_KEY")
    return _DEV_SECRET


def frontend_origins() -> set[str]:
    raw = os.environ.get("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return {origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()}


def trusted_proxies() -> set[str]:
    """IP довірених reverse proxy (напр. Caddy). Лише від них приймається X-Forwarded-For."""
    raw = os.environ.get("TRUSTED_PROXIES", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def smtp_tls_mode() -> str:
    """V2_SMTP_TLS_MODE: starttls (типово, порт 587) або implicit (TLS з першого байта, порт 465)."""
    value = os.environ.get("V2_SMTP_TLS_MODE", "").strip().lower() or "starttls"
    if value not in SMTP_TLS_MODES:
        raise RuntimeError("V2_SMTP_TLS_MODE має бути starttls або implicit")
    return value


def _smtp_sender_problem() -> str | None:
    """У release справжня адреса відправника: з @ і доменом, не localhost (лист з no-reply@localhost відкинуть)."""
    address = parseaddr(os.environ.get("V2_SMTP_FROM", "").strip())[1]
    local, _, domain = address.rpartition("@")
    domain = domain.lower().rstrip(".")
    if not local or not domain or "." not in domain or domain == "localhost" or domain.endswith(".localhost"):
        return "V2_SMTP_FROM має містити справжню адресу відправника (не no-reply@localhost), якщо задано V2_SMTP_HOST"
    return None


LM_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
LM_DEFAULT_MODEL = "qwen3-8b"
LM_DEFAULT_TIMEOUT_S = 300
LM_DEFAULT_MAX_TOKENS = 900


def _positive_int(name: str, default: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if not 1 <= value <= maximum:
        raise RuntimeError(f"{name} має бути цілим числом від 1 до {maximum}")
    return value


def lm_url() -> str | None:
    """База llama-server без кінцевого «/»; None — функцію чернеток вимкнено."""
    value = os.environ.get("V2_LM_URL", "").strip().rstrip("/")
    return value or None


def lm_api_key() -> str:
    return os.environ.get("V2_LM_API_KEY", "").strip()


def lm_model() -> str:
    return os.environ.get("V2_LM_MODEL", "").strip() or LM_DEFAULT_MODEL


def lm_timeout_s() -> int:
    return _positive_int("V2_LM_TIMEOUT_S", LM_DEFAULT_TIMEOUT_S, 3600)


def lm_max_tokens() -> int:
    return _positive_int("V2_LM_MAX_TOKENS", LM_DEFAULT_MAX_TOKENS, 8192)


def lm_url_problem(url: str | None, *, release: bool) -> str | None:
    """Опис проблеми з V2_LM_URL (без самої адреси) або None. У release — лише loopback."""
    if url is None:
        return None
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        parts.port                                    # некоректний порт → ValueError
    except ValueError:
        return "V2_LM_URL має бути адресою http(s)://host:port"
    if parts.scheme not in ("http", "https") or not host:
        return "V2_LM_URL має бути адресою http(s)://host:port"
    if parts.username or parts.password or parts.query or parts.fragment:
        return "V2_LM_URL не може містити облікових даних, query чи fragment (ключ — у V2_LM_API_KEY)"
    if release and host not in LM_LOOPBACK_HOSTS:
        return "V2_LM_URL у release має вказувати лише на loopback (127.0.0.1, ::1 або localhost)"
    return None


def check_lm_config() -> None:
    """Некоректні V2_LM_* — сервер не стартує (у будь-якому режимі)."""
    problem = lm_url_problem(lm_url(), release=is_release())
    if problem:
        raise RuntimeError(problem)
    lm_timeout_s()
    lm_max_tokens()


def validate_release_config() -> None:
    """Сервер не стартує в release з небезпечною конфігурацією."""
    if not is_release():
        return
    problems = []
    if _flag("INTEGRITY_DEMO_XROLE"):
        problems.append("INTEGRITY_DEMO_XROLE=1 заборонено в release (X-Role не є автентифікацією)")
    if _flag("V2_AUTH_DEV_MAIL"):
        problems.append("V2_AUTH_DEV_MAIL=1 заборонено в release (OTP не можна віддавати через dev-mail)")
    if os.environ.get("V2_AUTH_SECURE_COOKIE", "1") == "0":
        problems.append("V2_AUTH_SECURE_COOKIE=0 заборонено в release (потрібні Secure cookie через HTTPS)")
    if len(os.environ.get("V2_SECRET_KEY", "")) < 32:
        problems.append("V2_SECRET_KEY має містити щонайменше 32 символи")
    if not trusted_proxies():
        problems.append("TRUSTED_PROXIES має містити IP довіреного reverse proxy (без нього ліміти рахуються "
                        "за адресою проксі, а не клієнта)")
    if os.environ.get("V2_CATALOG_NOW"):
        problems.append("V2_CATALOG_NOW заборонено в release (підміна поточного часу каталогу тестувань)")
    if os.environ.get("V2_SMTP_HOST"):
        sender_problem = _smtp_sender_problem()
        if sender_problem:
            problems.append(sender_problem)
    if os.environ.get("V2_SMTP_TLS_MODE", "").strip().lower() not in ("",) + SMTP_TLS_MODES:
        problems.append("V2_SMTP_TLS_MODE має бути starttls або implicit")
    lm_problem = lm_url_problem(lm_url(), release=True)
    if lm_problem:
        problems.append(lm_problem)
    if problems:
        raise RuntimeError("Небезпечна release-конфігурація: " + "; ".join(problems))
