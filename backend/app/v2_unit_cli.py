"""Серверна команда власника сервера: призначення й зняття підрозділу користувача V2.

Підрозділ для екрана «Результати підрозділу» (GET /v2/user/unit-results) призначає лише власник сервера
на самому сервері; ні користувач, ні веб-адміністратор цього не роблять. З каталогу backend:

  python -m app.v2_unit_cli --list-units                                  # довідник підрозділів
  python -m app.v2_unit_cli --email <email> --unit-id <id>                # план (dry run)
  python -m app.v2_unit_cli --email <email> --unit-id <id> --apply        # призначити
  python -m app.v2_unit_cli --email <email> --clear [--apply]             # зняти призначення

  - Без --apply — лише план; жодна БД не змінюється.
  - Користувача шукає за email у V2_AUTH_DB (лише читання), підрозділ — у INTEGRITY_DB (таблиця units).
    Призначення зберігається в instance_meta INTEGRITY_DB (app.unit_membership).
  - Не мігрує жодну БД — лише перевірка схеми (read-only). Не потребує V2_SECRET_KEY: зі змінних середовища
    читає лише INTEGRITY_DB, V2_AUTH_DB (у release обов'язкові) та APP_ENV.
  - Вивід: id користувача, роль, назва підрозділу; email лише замаскований, без секретів.
  - Нових подій журналу аудиту не пише.

Коди виходу: 0 — виконано або показано план; 2 — відмова (невідомий email чи підрозділ, неправильні
аргументи); 1 — помилка (схема, зайнята БД, інше).
"""
from __future__ import annotations

import argparse
import os
import sys

from . import settings
from .v2_auth import AuthDatabaseBusy, check_auth_schema, find_user_by_email, mask_email

EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2
_MAX_ID = 2 ** 63 - 1


class _Refused(Exception):
    pass


def _say(text: str) -> None:
    print(text, flush=True)


def _check_environment(need_auth: bool) -> None:
    """У release шляхи до БД задаються явно; схеми лише перевіряються, без міграцій і без створення файлів."""
    names = ("INTEGRITY_DB", "V2_AUTH_DB") if need_auth else ("INTEGRITY_DB",)
    if settings.is_release():
        missing = [name for name in names if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"У release потрібні змінні середовища: {', '.join(missing)}")
    if need_auth:
        check_auth_schema()
    from .database import engine       # створення engine не відкриває і не створює файл
    from .migrations import check_schema
    check_schema(engine)


def _unit_label(unit) -> str:
    return f"«{unit.name}» (id {unit.id})" if unit is not None else "не призначено"


def list_units() -> int:
    try:
        _check_environment(need_auth=False)
        from .database import SessionLocal
        from .models import Unit
        with SessionLocal() as db:
            units = [(unit.id, unit.name) for unit in db.query(Unit).order_by(Unit.id)]
    except Exception as error:  # noqa: BLE001 — коротке повідомлення без трасування
        _say(f"ПОМИЛКА  {error}")
        return EXIT_ERROR
    if not units:
        _say("Довідник підрозділів порожній.")
        return EXIT_OK
    _say("Підрозділи (id — назва):")
    for unit_id, name in units:
        _say(f"  {unit_id} — {name}")
    return EXIT_OK


def assign_unit(email: str, unit_id: int | None, apply: bool) -> int:
    """unit_id=None — зняти призначення."""
    try:
        _check_environment(need_auth=True)
        user = find_user_by_email(email)
        if user is None:
            raise _Refused("Користувача з такою адресою немає; нічого не змінено.")
        from .database import SessionLocal
        from .models import Unit
        from .unit_membership import get_user_unit_id, set_user_unit_id
        with SessionLocal() as db:
            new_unit = None
            if unit_id is not None:
                new_unit = db.get(Unit, unit_id) if 0 < unit_id <= _MAX_ID else None
                if new_unit is None:
                    raise _Refused("Невідомий підрозділ; нічого не змінено. Перелік: --list-units.")
            current_id = get_user_unit_id(db, user["id"])
            current = db.get(Unit, current_id) if current_id is not None else None
            who = f"користувач id {user['id']} ({mask_email(user['email'])}), роль {user['role']}"
            _say(f"ПЛАН  {who}: підрозділ {_unit_label(current)} → {_unit_label(new_unit)}.")
            if current_id == unit_id:
                _say("Змін немає; нічого не змінено.")
                return EXIT_OK
            if not apply:
                _say("Лише план, нічого не змінено. Щоб виконати, повторіть команду з --apply.")
                return EXIT_OK
            set_user_unit_id(db, user["id"], unit_id)
            db.commit()
            _say(f"ВИКОНАНО  {who}: підрозділ {_unit_label(new_unit)}.")
            return EXIT_OK
    except _Refused as refusal:
        _say(f"ВІДМОВА  {refusal}")
        return EXIT_REFUSED
    except AuthDatabaseBusy:
        _say("ПОМИЛКА  V2_AUTH_DB зайнята; нічого не змінено, повторіть команду пізніше.")
        return EXIT_ERROR
    except Exception as error:  # noqa: BLE001 — коротке повідомлення без трасування (шляхи, але не секрети)
        _say(f"ПОМИЛКА  {error}; нічого не змінено.")
        return EXIT_ERROR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.v2_unit_cli",
                                     description="Призначення підрозділу користувачу V2 власником сервера")
    parser.add_argument("--list-units", action="store_true", help="показати довідник підрозділів")
    parser.add_argument("--email", help="email користувача V2")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--unit-id", type=int, help="id підрозділу з --list-units")
    target.add_argument("--clear", action="store_true", help="зняти призначення підрозділу")
    parser.add_argument("--apply", action="store_true", help="виконати зміну (без нього — лише план)")
    args = parser.parse_args(argv)           # неправильні аргументи → SystemExit(2), тобто «відмова»
    if args.list_units:
        if args.email or args.unit_id is not None or args.clear or args.apply:
            parser.error("--list-units не поєднується з іншими параметрами")
        return list_units()
    if not args.email:
        parser.error("потрібен --email (або --list-units)")
    if args.unit_id is None and not args.clear:
        parser.error("потрібен --unit-id <id> або --clear")
    return assign_unit(args.email, None if args.clear else args.unit_id, args.apply)


if __name__ == "__main__":
    sys.exit(main())
