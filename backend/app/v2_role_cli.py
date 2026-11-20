"""Серверна команда власника сервера: призначення й зняття ролей V2, зокрема ролі admin.

Роль адміністратора через веб не призначає й не знімає ніхто (POST /v2/admin/users/{id}/role → 403
admin_role_server_only). Лише власник сервера на самому сервері, з каталогу backend:

  python -m app.v2_role_cli set-role --email <email> --role admin|user|data_officer            # план
  python -m app.v2_role_cli set-role --email <email> --role admin|user|data_officer --confirm  # виконати

На сервері Windows — обгортка installer/windows-v2/ops/Set-V2UserRole.ps1 (-Email -Role [-Apply]).

  - Без --confirm — лише план (поточна роль → нова, скільки сесій буде завершено); БД не змінюється.
  - З --confirm — та сама транзакція BEGIN IMMEDIATE, що й веб-зміна: роль, видалення ВСІХ сесій цілі,
    гасіння відкритих кодів 2FA, запис у v2_role_changes з actor_user_id = 0 (SERVER_ACTOR_ID: «сервер»;
    колонка NOT NULL без FK/CHECK, id користувачів ≥ 1). Після коміту — подія основного журналу
    user.role_change з actor_role="server" і actor_user_id=None (без email).
  - Останнього адміністратора не знімає: лишається щонайменше один admin.
  - Не мігрує жодну БД — лише перевірка схеми (read-only). Не потребує V2_SECRET_KEY: зі змінних середовища
    читає лише INTEGRITY_DB і V2_AUTH_DB (у release обидві обов'язкові) та APP_ENV.
  - Email у виводі лише замаскований. Зупиняти backend не потрібно (SQLite-транзакція, busy_timeout).

Коди виходу: 0 — виконано або показано план; 2 — відмова (немає користувача, та сама роль, останній
адміністратор, неправильні аргументи); 1 — помилка (схема, зайнята БД, інше).
"""
from __future__ import annotations

import argparse
import os
import sys

from . import settings
from .v2_auth import ROLES, AuthDatabaseBusy, RoleChangeError, check_auth_schema, server_change_role, server_role_plan

EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2

_REFUSALS = {
    "not_found": "Користувача з такою адресою немає; нічого не змінено.",
    "unchanged": "Користувач уже має цю роль; нічого не змінено.",
    "last_admin": "Це останній адміністратор: зняти роль не можна, має лишитися щонайменше один admin. "
                  "Спочатку призначте роль admin іншому користувачу.",
    "invalid_role": "Невідома роль.",
    "conflict": "Роль змінилася під час виконання; повторіть команду.",
}


def _say(text: str) -> None:
    print(text, flush=True)


def _check_environment() -> None:
    """У release шляхи до БД задаються явно; схеми лише перевіряються, без міграцій і без створення файлів."""
    if settings.is_release():
        missing = [name for name in ("INTEGRITY_DB", "V2_AUTH_DB") if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"У release потрібні змінні середовища: {', '.join(missing)}")
    check_auth_schema()
    from .database import engine       # створення engine не відкриває і не створює файл
    from .migrations import check_schema
    check_schema(engine)


def _record_audit() -> None:
    from . import audit
    from .database import SessionLocal
    with SessionLocal() as db:
        audit.record(db, "server", "user.role_change", actor_user_id=None)
        db.commit()


def set_role(email: str, role: str, confirm: bool) -> int:
    try:
        _check_environment()
        plan = server_role_plan(email, role)
    except RoleChangeError as error:
        _say(f"ВІДМОВА  {_REFUSALS.get(error.code, error.code)}")
        return EXIT_REFUSED
    except AuthDatabaseBusy:
        _say("ПОМИЛКА  V2_AUTH_DB зайнята; повторіть команду пізніше.")
        return EXIT_ERROR
    except Exception as error:  # noqa: BLE001 — коротке повідомлення без трасування (шляхи, але не секрети)
        _say(f"ПОМИЛКА  {error}")
        return EXIT_ERROR
    _say(f"ПЛАН  користувач id {plan['user_id']} ({plan['email_masked']}): роль {plan['old_role']} → "
         f"{plan['new_role']}; буде завершено сесій: {plan['sessions']}; адміністраторів зараз: {plan['admins']}.")
    if not confirm:
        _say("Лише план, нічого не змінено. Щоб виконати, повторіть команду з --confirm.")
        return EXIT_OK
    try:
        result = server_change_role(email, role)
    except RoleChangeError as error:
        _say(f"ВІДМОВА  {_REFUSALS.get(error.code, error.code)}")
        return EXIT_REFUSED
    except AuthDatabaseBusy:
        _say("ПОМИЛКА  V2_AUTH_DB зайнята; нічого не змінено, повторіть команду пізніше.")
        return EXIT_ERROR
    except Exception as error:  # noqa: BLE001
        _say(f"ПОМИЛКА  {error}; транзакцію відкочено, нічого не змінено.")
        return EXIT_ERROR
    _say(f"ВИКОНАНО  користувач id {result['user_id']} ({result['email_masked']}): роль {result['old_role']} → "
         f"{result['new_role']}; завершено сесій: {result['sessions_revoked']}; запис у v2_role_changes (актор: сервер).")
    try:
        _record_audit()
    except Exception as error:  # noqa: BLE001 — роль уже змінено; бракує лише події основного журналу
        _say(f"ПОМИЛКА  роль змінено, але подію основного журналу не записано: {error}")
        return EXIT_ERROR
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.v2_role_cli",
                                     description="Призначення й зняття ролей V2 власником сервера")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("set-role", help="змінити роль користувача (без --confirm — лише план)")
    command.add_argument("--email", required=True)
    command.add_argument("--role", required=True, choices=ROLES)
    command.add_argument("--confirm", action="store_true", help="виконати зміну (без нього — лише план)")
    args = parser.parse_args(argv)           # неправильні аргументи → SystemExit(2), тобто «відмова»
    return set_role(args.email, args.role, args.confirm)


if __name__ == "__main__":
    sys.exit(main())
