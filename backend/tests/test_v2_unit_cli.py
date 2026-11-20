"""
Серверна команда app.v2_unit_cli: призначення підрозділу користувачу V2 власником сервера.
  - --list-units показує довідник units;
  - без --apply — лише план (dry run), БД не змінюється; з --apply — instance_meta "unit_member:<id>";
  - --clear знімає призначення; невідомий email чи підрозділ → 2; неправильні аргументи → 2; помилка → 1;
  - вивід без повного email; нових подій аудиту немає; БД не створюється й не мігрується.
Працює на тимчасових БД із conftest.py.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import v2_unit_cli
from app.database import SessionLocal
from app.models import AuditEvent, InstanceMeta, Unit
from app.unit_membership import get_user_unit_id, membership_key
from app.v2_auth import find_user_id
from v2_helpers import make_user

BACKEND = Path(__file__).resolve().parent.parent


def run_cli(capsys, *args: str) -> tuple[int, str]:
    code = v2_unit_cli.main(list(args))
    return code, capsys.readouterr().out


def units() -> list[tuple[int, str]]:
    with SessionLocal() as db:
        return [(u.id, u.name) for u in db.query(Unit).order_by(Unit.id)]


def unit_of(user_id: int) -> int | None:
    with SessionLocal() as db:
        return get_user_unit_id(db, user_id)


def audit_count() -> int:
    with SessionLocal() as db:
        return db.query(AuditEvent).count()


def test_list_units_shows_the_directory(capsys):
    code, out = run_cli(capsys, "--list-units")
    assert code == 0
    assert units(), "seed має створити підрозділи"
    for unit_id, name in units():
        assert f"{unit_id} — {name}" in out


def test_dry_run_changes_nothing(capsys):
    email = make_user()
    user_id = find_user_id(email)
    unit_id, unit_name = units()[0]
    code, out = run_cli(capsys, "--email", email, "--unit-id", str(unit_id))
    assert code == 0 and "ПЛАН" in out and "Лише план" in out
    assert f"id {user_id}" in out and "роль user" in out and unit_name in out
    assert email not in out
    assert unit_of(user_id) is None
    with SessionLocal() as db:
        assert db.get(InstanceMeta, membership_key(user_id)) is None


def test_apply_assigns_reassigns_and_clears(capsys):
    email = make_user("data_officer")
    user_id = find_user_id(email)
    (first_id, first_name), (second_id, second_name) = units()[:2]
    events_before = audit_count()

    code, out = run_cli(capsys, "--email", email.upper(), "--unit-id", str(first_id), "--apply")
    assert code == 0 and "ВИКОНАНО" in out and first_name in out and "роль data_officer" in out
    assert email not in out.lower()
    assert unit_of(user_id) == first_id

    code, out = run_cli(capsys, "--email", email, "--unit-id", str(first_id), "--apply")
    assert code == 0 and "Змін немає" in out and unit_of(user_id) == first_id

    code, out = run_cli(capsys, "--email", email, "--unit-id", str(second_id), "--apply")
    assert code == 0 and first_name in out and second_name in out
    assert unit_of(user_id) == second_id

    code, out = run_cli(capsys, "--email", email, "--clear")
    assert code == 0 and "Лише план" in out and unit_of(user_id) == second_id

    code, out = run_cli(capsys, "--email", email, "--clear", "--apply")
    assert code == 0 and "ВИКОНАНО" in out and "не призначено" in out
    assert unit_of(user_id) is None
    with SessionLocal() as db:
        assert db.get(InstanceMeta, membership_key(user_id)) is None

    code, out = run_cli(capsys, "--email", email, "--clear", "--apply")
    assert code == 0 and "Змін немає" in out
    assert audit_count() == events_before, "команда не пише нових подій аудиту"


def test_refuses_unknown_email_and_unknown_unit(capsys):
    email = make_user()
    user_id = find_user_id(email)
    unit_id = units()[0][0]
    code, out = run_cli(capsys, "--email", "nobody-here@example.test", "--unit-id", str(unit_id), "--apply")
    assert code == 2 and "ВІДМОВА" in out
    for bad in ("999999", "0", "-1", str(2 ** 70)):
        code, out = run_cli(capsys, "--email", email, "--unit-id", bad, "--apply")
        assert code == 2 and "Невідомий підрозділ" in out, bad
    assert unit_of(user_id) is None


def test_bad_arguments_are_refusals(capsys):
    email = make_user()
    for args in ([], ["--email", email], ["--unit-id", "1"], ["--email", email, "--unit-id", "1", "--clear"],
                 ["--list-units", "--email", email], ["--email", email, "--unit-id", "abc"]):
        with pytest.raises(SystemExit) as refused:
            v2_unit_cli.main(args)
        assert refused.value.code == 2, args
    capsys.readouterr()
    assert unit_of(find_user_id(email)) is None


def test_does_not_create_missing_auth_database(capsys, tmp_path, monkeypatch):
    missing = tmp_path / "absent.db"
    monkeypatch.setenv("V2_AUTH_DB", str(missing))
    code, out = run_cli(capsys, "--email", "a@example.test", "--unit-id", "1", "--apply")
    assert code == 1 and "ПОМИЛКА" in out and not missing.exists()


def test_module_runs_in_release_without_secret_key():
    email = make_user()
    user_id = find_user_id(email)
    unit_id, unit_name = units()[-1]
    env = {k: v for k, v in os.environ.items()
           if k not in {"V2_SECRET_KEY", "V2_AUTH_DEV_MAIL", "INTEGRITY_DEMO_XROLE", "PYTHONPATH"}}
    env.update({"APP_ENV": "release", "PYTHONIOENCODING": "utf-8"})

    def cli(environment, *args):
        return subprocess.run([sys.executable, "-B", "-X", "utf8", "-m", "app.v2_unit_cli", *args],
                              cwd=BACKEND, env=environment, capture_output=True, text=True, encoding="utf-8",
                              timeout=120)

    listed = cli(env, "--list-units")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert unit_name in listed.stdout
    applied = cli(env, "--email", email, "--unit-id", str(unit_id), "--apply")
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert email not in applied.stdout + applied.stderr
    assert unit_of(user_id) == unit_id
    without_db = {k: v for k, v in env.items() if k != "V2_AUTH_DB"}
    refused = cli(without_db, "--email", email, "--clear", "--apply")
    assert refused.returncode == 1 and "V2_AUTH_DB" in refused.stdout
    assert unit_of(user_id) == unit_id
