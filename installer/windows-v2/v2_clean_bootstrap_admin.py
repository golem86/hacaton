"""Clean install only: create an admin in an already verified fresh V2 auth DB.

This entry point deliberately does not import or call init_auth_db/migrate_auth_db.
"""
import argparse
import getpass

from app import audit
from app.database import SessionLocal
from app.v2_auth import check_auth_schema, create_user


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    parser.add_argument('--email', required=True)
    args = parser.parse_args()
    check_auth_schema()
    password = getpass.getpass('Новий пароль адміністратора (мінімум 10 символів): ')
    confirmation = getpass.getpass('Повторіть пароль: ')
    if len(password) < 10 or password != confirmation:
        raise SystemExit('Паролі мають збігатися та містити щонайменше 10 символів')
    try:
        create_user(args.name, args.email, password, role='admin')
    except ValueError:
        raise SystemExit('Створення адміністратора не вдалося') from None
    with SessionLocal() as db:
        audit.record(db, 'admin', 'user.create_admin')
        db.commit()
    print('Локального адміністратора створено; значення облікових даних не виводяться')


if __name__ == '__main__':
    main()
