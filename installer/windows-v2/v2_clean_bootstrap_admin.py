"""Clean install only: create the first admin in an already verified fresh V2 auth DB.

Runs ONCE from the installer directory (it is never deployed into app\\<release>):
  python -I -X utf8 v2_clean_bootstrap_admin.py --backend <app\\<release>\\backend> --name ... --email ...
The release backend is put on sys.path explicitly (-I: no script dir, no cwd, no PYTHON* variables).
This entry point deliberately does not import or call init_auth_db/migrate_auth_db: the schema is only checked.
"""
import argparse
import getpass
import os
import sys


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--email', required=True)
    args = parser.parse_args(argv)
    backend = os.path.abspath(args.backend)
    if not os.path.isfile(os.path.join(backend, 'app', 'v2_auth.py')):
        raise SystemExit('--backend має вказувати на каталог backend релізу (app\\v2_auth.py)')
    sys.path.insert(0, backend)
    from app import audit
    from app.database import SessionLocal
    from app.v2_auth import AdminExists, check_auth_schema, create_user

    check_auth_schema()
    password = getpass.getpass('Новий пароль адміністратора (мінімум 10 символів): ')
    confirmation = getpass.getpass('Повторіть пароль: ')
    if len(password) < 10 or password != confirmation:
        raise SystemExit('Паролі мають збігатися та містити щонайменше 10 символів')
    try:
        user = create_user(args.name, args.email, password, role='admin', require_no_admin=True)
    except AdminExists:
        raise SystemExit('Адміністратор уже існує; нового не створено') from None
    except ValueError:
        raise SystemExit('Створення адміністратора не вдалося') from None
    with SessionLocal() as db:
        audit.record(db, 'admin', 'user.create_admin', actor_user_id=user['id'])
        db.commit()
    print('Локального адміністратора створено; значення облікових даних не виводяться')


if __name__ == '__main__':
    main()
