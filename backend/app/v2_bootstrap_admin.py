"""Створення локального адміністратора V2 без публічного admin-реєстрування.

Запуск із backend:
  python -m app.v2_bootstrap_admin --name "Local Admin" --email admin@example.test
Пароль вводиться приховано через getpass і не зберігається в репозиторії.

  - Якщо адміністратор уже існує, команда відмовляє (перевірка й створення — одна транзакція).
    Додатковий адміністратор створюється лише явним рішенням: --allow-additional-admin.
    Звичайний шлях призначення ролей — POST /v2/admin/users/{id}/role з журналом v2_role_changes.
  - У release існуюча V2_AUTH_DB не мігрує: лише перевірка схеми (міграція — явною командою
    python -m app.migrations --apply --confirm-verified-backup).
  - Факт створення пишеться в журнал (user.create_admin) лише з роллю та id, без email (S12).
"""
import argparse
import getpass

from . import audit
from .database import SessionLocal
from .v2_auth import AdminExists, admin_exists, create_user, init_auth_db


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create a local Dashboard V2 admin")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--allow-additional-admin", action="store_true",
                        help="створити ще одного адміністратора, хоча адміністратор уже існує")
    args = parser.parse_args(argv)
    init_auth_db()                       # development: міграція; release: лише перевірка схеми
    if not args.allow_additional_admin and admin_exists():
        raise SystemExit("Адміністратор уже існує. Призначайте ролі через /v2/admin/users/{id}/role "
                         "або явно вкажіть --allow-additional-admin")
    password = getpass.getpass("Новий пароль адміністратора (мінімум 10 символів): ")
    confirmation = getpass.getpass("Повторіть пароль: ")
    if len(password) < 10 or password != confirmation:
        raise SystemExit("Паролі мають збігатися та містити щонайменше 10 символів")
    try:
        user = create_user(args.name, args.email, password, role="admin",
                           require_no_admin=not args.allow_additional_admin)
    except AdminExists as error:
        raise SystemExit("Адміністратор уже існує; нового не створено") from error
    except ValueError as error:
        raise SystemExit(str(error)) from error
    with SessionLocal() as db:            # S12: факт створення адміністратора — у журнал (без email)
        audit.record(db, "admin", "user.create_admin", actor_user_id=user["id"])
        db.commit()
    print(f"Створено локального адміністратора (id {user['id']})")


if __name__ == "__main__":
    main()
