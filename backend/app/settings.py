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
  - потрібен серверний секрет V2_SECRET_KEY (≥ 32 символи) для CSRF;
  - автоматичні міграції БД вимкнено (MIG-1).

Значення читаються з оточення під час кожного виклику, тож тести можуть
змінювати їх через monkeypatch.setenv без перезапуску застосунку.
"""
import os
import secrets

_DEV_SECRET = secrets.token_hex(32)   # лише для development: новий при кожному запуску


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
    if problems:
        raise RuntimeError("Небезпечна release-конфігурація: " + "; ".join(problems))
