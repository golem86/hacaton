"""Серверна команда власника сервера: призначення й зняття підрозділу користувача V2.

Підрозділ визначає, чиї узагальнені результати користувач бачить на екрані «Результати підрозділу»
(GET /v2/user/unit-results). Тому, як і роль admin чи data_officer, його не призначає ні сам
користувач, ні адміністратор у вебі — лише власник сервера на самому сервері, з каталогу backend:

  python -m app.v2_unit_cli set-unit --email <email> --unit "<назва з довідника units>"            # план
  python -m app.v2_unit_cli set-unit --email <email> --unit "<назва з довідника units>" --confirm  # виконати
  python -m app.v2_unit_cli clear-unit --email <email> [--confirm]
  python -m app.v2_unit_cli list-units

  - Без --confirm — лише план; БД не змінюється.
  - Підрозділ — лише з довідника units (зовнішній ключ user_units.unit → units.name).
  - Подія основного журналу user.unit_change з actor_role="server" — без email, id і назви підрозділу.
  - Не мігрує БД — лише перевірка схеми. Email у виводі лише замаскований.

Коди виходу: 0 — виконано або показано план; 2 — відмова (немає користувача чи підрозділу, без змін);
1 — помилка.
"""
from __future__ import annotations

import argparse
import os
import sys

from . import settings
from .v2_auth import check_auth_schema, find_user_by_email, mask_email

EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2


def _say(text: str) -> None:
    print(text, flush=True)


def _check_environment() -> None:
    if settings.is_release():
        missing = [name for name in ("INTEGRITY_DB", "V2_AUTH_DB") if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"У release потрібні змінні середовища: {', '.join(missing)}")
    check_auth_schema()
    from .database import engine
    from .migrations import check_schema
    check_schema(engine)


def _run(email: str, unit: str | None, confirm: bool) -> int:
    from . import audit
    from .database import SessionLocal
    from .models import Unit, UserUnit
    from .services.unit_results import assign_unit
    try:
        _check_environment()
        user = find_user_by_email(email)
        if user is None:
            _say("ВІДМОВА  Користувача з такою адресою немає; нічого не змінено.")
            return EXIT_REFUSED
        masked = mask_email(email)
        with SessionLocal() as db:
            if unit is not None and db.query(Unit).filter_by(name=unit).first() is None:
                _say("ВІДМОВА  Такого підрозділу немає в довіднику units; нічого не змінено. "
                     "Перелік: python -m app.v2_unit_cli list-units")
                return EXIT_REFUSED
            current = db.get(UserUnit, int(user["id"]))
            old = current.unit if current else "—"
            if (current.unit if current else None) == unit:
                _say("ВІДМОВА  Підрозділ не призначено; нічого не змінено." if unit is None
                     else "ВІДМОВА  Підрозділ уже такий; нічого не змінено.")
                return EXIT_REFUSED
            _say(f"ПЛАН  користувач id {user['id']} ({masked}): підрозділ {old} → {unit or '—'}.")
            if not confirm:
                _say("Лише план, нічого не змінено. Щоб виконати, повторіть команду з --confirm.")
                return EXIT_OK
            assign_unit(db, int(user["id"]), unit)
            audit.record(db, "server", "user.unit_change", actor_user_id=None)
            db.commit()
        _say(f"ВИКОНАНО  користувач id {user['id']} ({masked}): підрозділ {old} → {unit or '—'}.")
        return EXIT_OK
    except Exception as error:  # noqa: BLE001 — коротке повідомлення без трасування
        _say(f"ПОМИЛКА  {error}; нічого не змінено.")
        return EXIT_ERROR


def _list_units() -> int:
    from .database import SessionLocal
    from .models import Unit
    try:
        _check_environment()
        with SessionLocal() as db:
            for (name,) in db.query(Unit.name).order_by(Unit.name):
                _say(name)
        return EXIT_OK
    except Exception as error:  # noqa: BLE001
        _say(f"ПОМИЛКА  {error}")
        return EXIT_ERROR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.v2_unit_cli",
                                     description="Призначення підрозділу користувачу V2 власником сервера")
    commands = parser.add_subparsers(dest="command", required=True)
    set_cmd = commands.add_parser("set-unit", help="призначити підрозділ (без --confirm — лише план)")
    set_cmd.add_argument("--email", required=True)
    set_cmd.add_argument("--unit", required=True)
    set_cmd.add_argument("--confirm", action="store_true")
    clear_cmd = commands.add_parser("clear-unit", help="зняти підрозділ (без --confirm — лише план)")
    clear_cmd.add_argument("--email", required=True)
    clear_cmd.add_argument("--confirm", action="store_true")
    commands.add_parser("list-units", help="показати довідник підрозділів")
    args = parser.parse_args(argv)
    if args.command == "list-units":
        return _list_units()
    return _run(args.email, args.unit if args.command == "set-unit" else None, args.confirm)


if __name__ == "__main__":
    sys.exit(main())
