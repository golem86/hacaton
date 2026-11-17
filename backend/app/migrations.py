"""
Безпечне оновлення структури бази (міграція) без втрати анкет і відповідей.

Навіщо: SQLAlchemy `create_all` лише ДОДАЄ відсутні таблиці, але не змінює наявні.
Тому база, створена попередньою версією бекенду, після оновлення коду лишилася б
без нових обмежень (зв'язок підрозділу з довідником, унікальність відповідей).

Версія схеми зберігається в самій базі: `PRAGMA user_version`.
  0 — попередня версія (підрозділ — довільний текст, без унікальності відповідей);
  1 — довідник units, response_sets.unit → units.name,
      answers унікальні за (response_set_id, question_id).
  2 — поточна: додано таблицю журналу дій audit_events. Зміна лише додає нову
      таблицю (наявні не змінюються), тому виконується через create_all без перебудови.

Що робить migrate() для старої бази:
  1. Робить резервну копію файлу бази (integrity.backup-<дата-час>.db).
  2. В ОДНІЙ транзакції: переносить усі наявні назви підрозділів у довідник units,
     перебудовує таблиці response_sets і answers з новими обмеженнями, копіює всі рядки.
  3. Перевіряє: кількість анкет і відповідей не змінилася, зв'язки цілі
     (PRAGMA foreign_key_check), файл бази цілий (PRAGMA integrity_check).
  4. Якщо хоч щось не так — відкат: база лишається точно такою, як була.
"""
import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable

from .database import Base
from .models import Answer, ResponseSet, Unit

SCHEMA_VERSION = 2


class MigrationError(RuntimeError):
    """Міграцію не виконано; база лишилась без змін."""


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _has_unit_fk(con: sqlite3.Connection) -> bool:
    return any(row[2] == "units" for row in con.execute("PRAGMA foreign_key_list(response_sets)"))


def _has_unique_answers(con: sqlite3.Connection) -> bool:
    for _, index_name, unique, *_ in con.execute("PRAGMA index_list(answers)"):
        columns = [r[2] for r in con.execute(f'PRAGMA index_info("{index_name}")')]
        if unique and sorted(columns) == ["question_id", "response_set_id"]:
            return True
    return False


def needs_migration(con: sqlite3.Connection) -> bool:
    tables = _tables(con)
    if "response_sets" not in tables:
        return False
    return not _has_unit_fk(con) or ("answers" in tables and not _has_unique_answers(con))


def _count(con: sqlite3.Connection, table: str) -> int:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def backup_database(con: sqlite3.Connection, db_file: Path) -> Path:
    """Копія через вбудований механізм SQLite backup (коректна навіть для відкритої бази)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = db_file.with_name(f"{db_file.stem}.backup-{stamp}{db_file.suffix}")
    with sqlite3.connect(target) as dst:
        con.backup(dst)
    return target


def _ddl(table, engine: Engine) -> str:
    return str(CreateTable(table).compile(dialect=engine.dialect))


def migrate(engine: Engine) -> dict:
    """
    Доводить базу до поточної схеми. Безпечно викликати щоразу під час запуску:
    якщо оновлювати нічого, нічого не змінюється. Повертає короткий звіт.
    """
    raw = engine.raw_connection()
    con: sqlite3.Connection = raw.driver_connection
    report: dict = {"action": "up_to_date", "backup": None}
    try:
        if not _tables(con):
            report["action"] = "created"
        elif needs_migration(con):
            report.update(_migrate_v0_to_v1(con, engine))
    finally:
        raw.close()

    # Доводимо відсутні таблиці (нові модулі) і записуємо версію схеми
    Base.metadata.create_all(engine)
    raw = engine.raw_connection()
    try:
        raw.driver_connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        raw.driver_connection.commit()
    finally:
        raw.close()
    return report


def _migrate_v0_to_v1(con: sqlite3.Connection, engine: Engine) -> dict:
    db_file = Path(engine.url.database) if engine.url.database not in (None, "", ":memory:") else None
    backup = backup_database(con, db_file) if db_file else None

    sets_before = _count(con, "response_sets")
    answers_before = _count(con, "answers") if "answers" in _tables(con) else 0

    # Дублікати відповідей не видаляємо мовчки — це рішення людини
    if answers_before:
        duplicates = con.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM answers GROUP BY response_set_id, question_id "
            "HAVING COUNT(*) > 1)").fetchone()[0]
        if duplicates:
            raise MigrationError(
                f"Знайдено {duplicates} дубльованих відповідей (анкета + питання). "
                f"Міграцію зупинено, база не змінена. Резервна копія: {backup}")

    old_isolation = con.isolation_level
    con.isolation_level = None          # керуємо транзакцією вручну
    con.execute("PRAGMA foreign_keys = OFF")        # стандартна процедура SQLite для перебудови таблиць
    con.execute("PRAGMA legacy_alter_table = ON")   # перейменування не переписує посилання інших таблиць
    try:
        con.execute("BEGIN")
        tables = _tables(con)
        con.execute("ALTER TABLE response_sets RENAME TO _legacy_response_sets")
        if "answers" in tables:
            con.execute("ALTER TABLE answers RENAME TO _legacy_answers")

        if "units" not in tables:
            con.execute(_ddl(Unit.__table__, engine))
        units_added = con.execute(
            "INSERT OR IGNORE INTO units (name) SELECT DISTINCT unit FROM _legacy_response_sets "
            "WHERE unit IS NOT NULL").rowcount

        con.execute(_ddl(ResponseSet.__table__, engine))
        con.execute("INSERT INTO response_sets (id, cycle_id, respondent_category, unit) "
                    "SELECT id, cycle_id, respondent_category, unit FROM _legacy_response_sets")
        con.execute(_ddl(Answer.__table__, engine))
        if "answers" in tables:
            con.execute("INSERT INTO answers (id, response_set_id, question_id, value) "
                        "SELECT id, response_set_id, question_id, value FROM _legacy_answers")
            con.execute("DROP TABLE _legacy_answers")
        con.execute("DROP TABLE _legacy_response_sets")

        # Перевірки перед збереженням
        problems = []
        if _count(con, "response_sets") != sets_before:
            problems.append("кількість анкет змінилась")
        if _count(con, "answers") != answers_before:
            problems.append("кількість відповідей змінилась")
        broken = con.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            problems.append(f"порушено зв'язків: {len(broken)}")
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            problems.append(f"integrity_check: {integrity}")
        if problems:
            raise MigrationError("Перевірка не пройдена: " + "; ".join(problems))

        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        con.execute("COMMIT")
    except Exception as exc:
        con.execute("ROLLBACK")
        if isinstance(exc, MigrationError):
            raise MigrationError(f"{exc}. Зміни відкочено, резервна копія: {backup}") from exc
        raise MigrationError(f"Помилка міграції: {exc}. Зміни відкочено, резервна копія: {backup}") from exc
    finally:
        con.execute("PRAGMA legacy_alter_table = OFF")
        con.execute("PRAGMA foreign_keys = ON")
        con.isolation_level = old_isolation

    return {"action": "migrated", "backup": str(backup) if backup else None,
            "response_sets": sets_before, "answers": answers_before, "units_added": units_added}


def check_schema(engine: Engine) -> None:
    """
    MIG-1 (release): лише перевірка, БД не змінюється.
    Сервер не стартує, якщо схема INTEGRITY_DB не відповідає поточній версії —
    тоді потрібна явна міграція (python -m app.migrations) після перевіреної резервної копії.
    """
    raw = engine.raw_connection()
    try:
        con: sqlite3.Connection = raw.driver_connection
        version = con.execute("PRAGMA user_version").fetchone()[0]
        tables = _tables(con)
        missing = {t.name for t in Base.metadata.sorted_tables} - tables
        if version != SCHEMA_VERSION or missing or needs_migration(con):
            raise RuntimeError(
                f"Схема INTEGRITY_DB не відповідає версії {SCHEMA_VERSION} (зараз {version}, "
                f"відсутні таблиці: {sorted(missing) or 'немає'}). Автоміграція в release вимкнена: "
                "зробіть перевірену резервну копію і виконайте python -m app.migrations --apply "
                "--confirm-verified-backup")
    finally:
        raw.close()


if __name__ == "__main__":
    # Явна міграція (MIG-1): лише з підтвердженням перевіреної резервної копії.
    import argparse

    from .database import engine as _engine
    from .v2_auth import migrate_auth_db

    parser = argparse.ArgumentParser(description="Явна міграція INTEGRITY_DB і V2_AUTH_DB")
    parser.add_argument("--apply", action="store_true", help="виконати міграцію")
    parser.add_argument("--confirm-verified-backup", action="store_true",
                        help="підтверджую: свіжу резервну копію зроблено і перевірено (integrity_check, кількість рядків)")
    args = parser.parse_args()
    if not (args.apply and args.confirm_verified_backup):
        raise SystemExit("Міграцію не виконано: потрібні --apply і --confirm-verified-backup")
    print("INTEGRITY_DB:", migrate(_engine))
    print("V2_AUTH_DB:", migrate_auth_db())
