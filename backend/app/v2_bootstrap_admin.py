"""Створення локального адміністратора V2 без публічного admin-регистрування.

Запуск із backend:
  python -m app.v2_bootstrap_admin --name "Local Admin" --email admin@example.test
Пароль вводиться приховано через getpass і не зберігається в репозиторії.
"""
import argparse
import getpass

from . import audit
from .database import SessionLocal
from .v2_auth import create_user, init_auth_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or promote a local Dashboard V2 admin")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    password = getpass.getpass("Новий пароль адміністратора (мінімум 10 символів): ")
    confirmation = getpass.getpass("Повторіть пароль: ")
    if len(password) < 10 or password != confirmation:
        raise SystemExit("Паролі мають збігатися та містити щонайменше 10 символів")
    init_auth_db()
    try:
        user = create_user(args.name, args.email, password, role="admin")
    except ValueError as error:
        raise SystemExit(str(error)) from error
    with SessionLocal() as db:            # S12: факт створення адміністратора — у журнал (без email)
        audit.record(db, "admin", "user.create_admin")
        db.commit()
    print(f"Створено локального адміністратора: {user['email']}")


if __name__ == "__main__":
    main()
