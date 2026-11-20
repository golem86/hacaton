"""
Безпечне оновлення структури бази (міграція) без втрати анкет і відповідей.

Навіщо: SQLAlchemy `create_all` лише ДОДАЄ відсутні таблиці, але не змінює наявні.
Тому база, створена попередньою версією бекенду, після оновлення коду лишилася б
без нових обмежень (зв'язок підрозділу з довідником, унікальність відповідей).

Версія схеми зберігається в самій базі: `PRAGMA user_version`.
  0 — попередня версія (підрозділ — довільний текст, без унікальності відповідей);
  1 — довідник units, response_sets.unit → units.name,
      answers унікальні за (response_set_id, question_id).
  2 — додано таблицю журналу дій audit_events. Зміна лише додає нову
      таблицю (наявні не змінюються), тому виконується через create_all без перебудови.
  3 — додано cycle_configs і access_token_policies (Assessment Manager).
  4 — додано recommendation_actions (Recommendations Tracker: рішення
      посадової особи, відповідальний, строк, статус, історія). Як і для версій 2–3:
      лише нова таблиця, тож резервна копія + create_all без перебудови наявних.
  5 — поточна: посилення за аудитом — access_tokens.token_hash замість відкритого коду,
      audit_events.actor_user_id, таблиця instance_meta (див. нижче «Крок до версії 5»).

Що робить migrate() для старої бази:
  1. Робить резервну копію файлу бази (integrity.backup-<дата-час>.db) і перевіряє її:
     PRAGMA integrity_check, версія схеми і кількість рядків кожної таблиці як в оригіналі.
  2. В ОДНІЙ транзакції: переносить усі наявні назви підрозділів у довідник units,
     перебудовує таблиці response_sets і answers з новими обмеженнями, копіює всі рядки.
  3. Перевіряє: кількість анкет і відповідей не змінилася, зв'язки цілі
     (PRAGMA foreign_key_check), файл бази цілий (PRAGMA integrity_check).
  4. Якщо хоч щось не так — відкат: база лишається точно такою, як була.

Крок до версії 5 (посилення за аудитом, docs/V2_HARDENING_CONTRACT.md, розділ 2) працює
з будь-якої версії 1..4 (версія 0 спершу доводиться до 1). Після перевіреної резервної копії
в ОДНІЙ транзакції BEGIN IMMEDIATE:
  - створюються відсутні таблиці поточних моделей (cycle_configs, access_token_policies,
    recommendation_actions, instance_meta) — так само, як раніше create_all для версій 2–4;
  - access_tokens перебудовується: token → token_hash, наявні коди хешуються (SHA-256) у Python;
  - audit_events отримує колонку actor_user_id INTEGER NULL;
  - перевіряються кількість рядків усіх таблиць, хеші кодів, колонки моделей,
    foreign_key_check та integrity_check; лише тоді user_version = 5, інакше ROLLBACK.
БД версії, новішої за підтримувану, не змінюється взагалі (ні запису, ні резервної копії).
УВАГА: резервна копія перед кроком до 5 — точна копія старої БД, тож містить відкриті коди
access_tokens.token. Її зберігають з тим самим обмеженим доступом, що й саму БД, і знищують
за процедурою після підтвердження успішної міграції.
"""
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateIndex, CreateTable

from .database import Base
from .models import AccessToken, Answer, ResponseSet, Unit, hash_access_code

SCHEMA_VERSION = 5
LEGACY_TOKEN_COLUMNS = {"id", "cycle_id", "token", "used"}   # access_tokens у версіях 1..4


class MigrationError(RuntimeError):
    """Міграцію не виконано; база лишилась без змін."""


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _user_tables(con: sqlite3.Connection) -> list[str]:
    return sorted(t for t in _tables(con) if not t.startswith("sqlite_"))


def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')]


def _version(con: sqlite3.Connection) -> int:
    return con.execute("PRAGMA user_version").fetchone()[0]


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
    return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def _row_counts(con: sqlite3.Connection) -> dict[str, int]:
    return {table: _count(con, table) for table in _user_tables(con)}


def schema_problems(con: sqlite3.Connection) -> list[str]:
    """Розбіжності структури БД з моделями (Base.metadata): відсутні таблиці, бракує чи зайві колонки."""
    problems = []
    tables = _tables(con)
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            problems.append(f"немає таблиці {table.name}")
            continue
        actual = set(_columns(con, table.name))
        expected = {column.name for column in table.columns}
        if expected - actual:
            problems.append(f"{table.name}: бракує колонок {sorted(expected - actual)}")
        if actual - expected:
            problems.append(f"{table.name}: зайві колонки {sorted(actual - expected)}")
    return problems


def _db_file(engine: Engine) -> Path | None:
    database = engine.url.database
    return Path(database) if database not in (None, "", ":memory:") else None


def verify_backup(con: sqlite3.Connection, backup: Path) -> None:
    """Копія придатна, лише якщо вона ціла, тієї ж версії і з тією ж кількістю рядків у кожній таблиці."""
    with closing(sqlite3.connect(f"{backup.resolve().as_uri()}?mode=ro", uri=True)) as copy:
        problems = []
        integrity = copy.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            problems.append(f"integrity_check: {integrity}")
        if _version(copy) != _version(con):
            problems.append("інша версія схеми")
        if _row_counts(copy) != _row_counts(con):
            problems.append("кількість рядків не збігається")
    if problems:
        raise MigrationError(f"Резервна копія {backup.name} не пройшла перевірку: {'; '.join(problems)}. "
                             "Міграцію не виконано, база не змінена")


def backup_database(con: sqlite3.Connection, db_file: Path) -> Path:
    """Копія через вбудований механізм SQLite backup (коректна навіть для відкритої бази) з перевіркою."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = db_file.with_name(f"{db_file.stem}.backup-{stamp}{db_file.suffix}")
    n = 1
    while target.exists():               # кілька копій за секунду не перезаписують одна одну
        target = db_file.with_name(f"{db_file.stem}.backup-{stamp}-{n}{db_file.suffix}")
        n += 1
    with closing(sqlite3.connect(target)) as dst:
        con.backup(dst)
    verify_backup(con, target)
    return target


def _ddl(table, engine: Engine) -> str:
    return str(CreateTable(table).compile(dialect=engine.dialect))


def migrate(engine: Engine) -> dict:
    """
    Доводить базу до поточної схеми. Безпечно викликати щоразу під час запуску:
    якщо оновлювати нічого, нічого не змінюється. Повертає короткий звіт.
    """
    db_file = _db_file(engine)
    raw = engine.raw_connection()
    con: sqlite3.Connection = raw.driver_connection
    report: dict = {"action": "up_to_date", "backup": None}
    try:
        version = _version(con)
        if version > SCHEMA_VERSION:
            raise MigrationError(
                f"INTEGRITY_DB schema version {version} is newer than supported {SCHEMA_VERSION}; "
                "migration refused without changes")
        if not _user_tables(con):
            report["action"] = "created"
        else:
            if needs_migration(con):
                report.update(_migrate_v0_to_v1(con, engine, db_file))
            if _version(con) < SCHEMA_VERSION or schema_problems(con):
                backup = report["backup"] or (str(backup_database(con, db_file)) if db_file else None)
                report.update(_upgrade_to_current(con, engine, backup))
    finally:
        raw.close()

    if report["action"] == "created":
        # Порожня база: усі таблиці поточних моделей і версія схеми
        Base.metadata.create_all(engine)
        raw = engine.raw_connection()
        try:
            raw.driver_connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            raw.driver_connection.commit()
        finally:
            raw.close()
    return report


def _migrate_v0_to_v1(con: sqlite3.Connection, engine: Engine, db_file: Path | None) -> dict:
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

        # Версія 1; решту ланцюжка (до SCHEMA_VERSION) виконує _upgrade_to_current
        con.execute("PRAGMA user_version = 1")
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


def _hash_access_tokens(con: sqlite3.Connection, engine: Engine) -> int:
    """
    access_tokens(id, cycle_id, token, used) → access_tokens(id, cycle_id, token_hash, used).
    Викликається лише всередині транзакції _upgrade_to_current. id зберігаються,
    тож access_token_policies.token_id і далі вказує на ті самі коди.
    """
    columns = set(_columns(con, "access_tokens"))
    if columns != LEGACY_TOKEN_COLUMNS:
        raise MigrationError(f"Невідома структура access_tokens: {sorted(columns)}")
    legacy = con.execute("SELECT id, cycle_id, token, used FROM access_tokens ORDER BY id").fetchall()
    if any(not isinstance(token, str) or not token for _, _, token, _ in legacy):
        raise MigrationError("access_tokens містить порожній або нетекстовий код")
    expected = [(row_id, cycle_id, hash_access_code(token), used) for row_id, cycle_id, token, used in legacy]

    con.execute("ALTER TABLE access_tokens RENAME TO _legacy_access_tokens")
    con.execute(_ddl(AccessToken.__table__, engine))
    con.executemany("INSERT INTO access_tokens (id, cycle_id, token_hash, used) VALUES (?, ?, ?, ?)", expected)
    con.execute("DROP TABLE _legacy_access_tokens")
    stored = con.execute("SELECT id, cycle_id, token_hash, used FROM access_tokens ORDER BY id").fetchall()
    if stored != expected:
        raise MigrationError("хеші кодів доступу після перебудови не збігаються з очікуваними")
    return len(expected)


def _upgrade_to_current(con: sqlite3.Connection, engine: Engine, backup: str | None) -> dict:
    """Крок 1..4 → SCHEMA_VERSION в одній транзакції BEGIN IMMEDIATE (див. опис модуля)."""
    before = _row_counts(con)
    old_isolation = con.isolation_level
    con.isolation_level = None                      # керуємо транзакцією вручну
    con.execute("PRAGMA foreign_keys = OFF")        # перебудова access_tokens (на неї посилаються політики)
    con.execute("PRAGMA legacy_alter_table = ON")   # перейменування не переписує посилання інших таблиць
    try:
        con.execute("BEGIN IMMEDIATE")
        existing = _tables(con)
        created = []
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                con.execute(_ddl(table, engine))
                for index in table.indexes:
                    con.execute(str(CreateIndex(index).compile(dialect=engine.dialect)))
                created.append(table.name)
        hashed = _hash_access_tokens(con, engine) if "token" in _columns(con, "access_tokens") else 0
        if "actor_user_id" not in _columns(con, "audit_events"):
            con.execute("ALTER TABLE audit_events ADD COLUMN actor_user_id INTEGER")

        # Перевірки перед збереженням
        problems = []
        after = _row_counts(con)
        changed = sorted(t for t, n in before.items() if after.get(t) != n)
        if changed:
            problems.append(f"змінилась кількість рядків: {changed}")
        if any(after.get(t) for t in created):
            problems.append("нові таблиці не порожні")
        problems += schema_problems(con)
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
        if con.in_transaction:
            con.execute("ROLLBACK")
        if isinstance(exc, MigrationError):
            raise MigrationError(f"{exc}. Зміни відкочено, резервна копія: {backup}") from exc
        raise MigrationError(f"Помилка міграції: {exc}. Зміни відкочено, резервна копія: {backup}") from exc
    finally:
        con.execute("PRAGMA legacy_alter_table = OFF")
        con.execute("PRAGMA foreign_keys = ON")
        con.isolation_level = old_isolation

    return {"action": "migrated", "backup": backup, "tables_created": created, "access_tokens_hashed": hashed}


def _open_existing(db_file: Path) -> sqlite3.Connection:
    """Відкриває НАЯВНИЙ файл БД; mode=rw не створює новий файл (на відміну від sqlite3.connect)."""
    return sqlite3.connect(f"{db_file.resolve().as_uri()}?mode=rw", uri=True)


def check_schema(engine: Engine) -> None:
    """
    MIG-1 (release): лише перевірка, БД не змінюється і не створюється.
    Сервер не стартує, якщо файлу INTEGRITY_DB немає або схема не відповідає поточній версії
    (версія, таблиці й колонки моделей) — тоді потрібна явна міграція
    (python -m app.migrations) після перевіреної резервної копії.
    """
    hint = ("Автоміграція в release вимкнена: зробіть перевірену резервну копію і виконайте "
            "python -m app.migrations --apply --confirm-verified-backup")
    db_file = _db_file(engine)
    if db_file is not None and not db_file.is_file():
        raise RuntimeError(f"Файл INTEGRITY_DB не знайдено ({db_file.name}); порожню БД не створено. {hint}")
    if db_file is not None:
        con = _open_existing(db_file)
        close = con.close
    else:
        raw = engine.raw_connection()
        con, close = raw.driver_connection, raw.close
    try:
        version = _version(con)
        problems = schema_problems(con)
        if version != SCHEMA_VERSION or problems or needs_migration(con):
            raise RuntimeError(
                f"Схема INTEGRITY_DB не відповідає версії {SCHEMA_VERSION} (зараз {version}, "
                f"розбіжності: {'; '.join(problems) or 'немає'}). {hint}")
    finally:
        close()


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
