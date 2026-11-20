"""
Зафіксована структура INTEGRITY_DB попередніх версій — для тестів міграції до поточної схеми.

DDL знято з бази, яку створювали моделі відповідних комітів (create_all):
  SCHEMA3_DDL — версія 3 (коміт 47e0ba8, стан сервера TLSFIX5): коди access_tokens.token відкритим текстом;
  SCHEMA4_DDL — версія 4 (feature/integration 881cbd0): + recommendation_actions (Recommendations Tracker).
Дані лише синтетичні.
"""
import sqlite3
from contextlib import closing

SCHEMA3_DDL = """
CREATE TABLE components (
	id INTEGER NOT NULL, code VARCHAR(10) NOT NULL, name VARCHAR(200) NOT NULL, weight FLOAT NOT NULL,
	PRIMARY KEY (id), UNIQUE (code)
);
CREATE TABLE cycles (
	id INTEGER NOT NULL, name VARCHAR(50) NOT NULL, start_date DATE NOT NULL, status VARCHAR(20) NOT NULL,
	min_group_size INTEGER NOT NULL, PRIMARY KEY (id)
);
CREATE TABLE units (
	id INTEGER NOT NULL, name VARCHAR(100) NOT NULL, PRIMARY KEY (id), UNIQUE (name)
);
CREATE TABLE questions (
	id INTEGER NOT NULL, component_id INTEGER NOT NULL, text TEXT NOT NULL, scale_min INTEGER NOT NULL,
	scale_max INTEGER NOT NULL, kind VARCHAR(20) NOT NULL, PRIMARY KEY (id),
	FOREIGN KEY(component_id) REFERENCES components (id)
);
CREATE TABLE cycle_configs (
	cycle_id INTEGER NOT NULL, description TEXT NOT NULL, scope VARCHAR(200) NOT NULL,
	categories_json TEXT NOT NULL, questionnaire_version VARCHAR(50) NOT NULL, end_date DATE,
	PRIMARY KEY (cycle_id), FOREIGN KEY(cycle_id) REFERENCES cycles (id)
);
CREATE TABLE response_sets (
	id INTEGER NOT NULL, cycle_id INTEGER NOT NULL, respondent_category VARCHAR(30) NOT NULL,
	unit VARCHAR(100) NOT NULL, PRIMARY KEY (id),
	FOREIGN KEY(cycle_id) REFERENCES cycles (id), FOREIGN KEY(unit) REFERENCES units (name)
);
CREATE TABLE access_tokens (
	id INTEGER NOT NULL, cycle_id INTEGER NOT NULL, token VARCHAR(64) NOT NULL, used BOOLEAN NOT NULL,
	PRIMARY KEY (id), FOREIGN KEY(cycle_id) REFERENCES cycles (id), UNIQUE (token)
);
CREATE TABLE objective_indicators (
	id INTEGER NOT NULL, cycle_id INTEGER NOT NULL, component_id INTEGER NOT NULL, name VARCHAR(200) NOT NULL,
	value FLOAT NOT NULL, entered_by_role VARCHAR(50) NOT NULL, confirmed_by_role VARCHAR(50),
	confirmed BOOLEAN NOT NULL, PRIMARY KEY (id),
	FOREIGN KEY(cycle_id) REFERENCES cycles (id), FOREIGN KEY(component_id) REFERENCES components (id)
);
CREATE TABLE recommendations (
	id INTEGER NOT NULL, cycle_id INTEGER NOT NULL, component_id INTEGER NOT NULL, text TEXT NOT NULL,
	basis TEXT NOT NULL, status VARCHAR(20) NOT NULL, owner_role VARCHAR(100), due_date DATE, PRIMARY KEY (id),
	FOREIGN KEY(cycle_id) REFERENCES cycles (id), FOREIGN KEY(component_id) REFERENCES components (id)
);
CREATE TABLE audit_events (
	id INTEGER NOT NULL, created_at DATETIME NOT NULL, actor_role VARCHAR(50) NOT NULL,
	action VARCHAR(50) NOT NULL, assessment_id INTEGER, details TEXT NOT NULL, PRIMARY KEY (id),
	FOREIGN KEY(assessment_id) REFERENCES cycles (id)
);
CREATE TABLE answers (
	id INTEGER NOT NULL, response_set_id INTEGER NOT NULL, question_id INTEGER NOT NULL, value INTEGER NOT NULL,
	PRIMARY KEY (id), UNIQUE (response_set_id, question_id),
	FOREIGN KEY(response_set_id) REFERENCES response_sets (id), FOREIGN KEY(question_id) REFERENCES questions (id)
);
CREATE TABLE access_token_policies (
	token_id INTEGER NOT NULL, category VARCHAR(30) NOT NULL, expires_at DATETIME NOT NULL,
	PRIMARY KEY (token_id), FOREIGN KEY(token_id) REFERENCES access_tokens (id)
);
"""

RECOMMENDATION_ACTIONS_DDL = """
CREATE TABLE recommendation_actions (
	id INTEGER NOT NULL, assessment_id INTEGER NOT NULL, recommendation_id VARCHAR(64) NOT NULL,
	rule_id VARCHAR(50) NOT NULL, component_code VARCHAR(10) NOT NULL, text TEXT NOT NULL,
	methodology_version VARCHAR(50) NOT NULL, status VARCHAR(20) NOT NULL, owner VARCHAR(120), due_date DATE,
	decision_reason TEXT NOT NULL, evidence_refs_json TEXT NOT NULL, verified_in_assessment_id INTEGER,
	history_json TEXT NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id),
	UNIQUE (assessment_id, recommendation_id),
	FOREIGN KEY(assessment_id) REFERENCES cycles (id), FOREIGN KEY(verified_in_assessment_id) REFERENCES cycles (id)
);
"""
SCHEMA4_DDL = SCHEMA3_DDL + RECOMMENDATION_ACTIONS_DDL

# Синтетичні відкриті коди старої схеми: (id, cycle_id, code, used)
LEGACY_CODES = [(1, 1, "legacy-open-code-unused-1", 0), (2, 1, "legacy-open-code-used-2", 1),
                (3, 1, "legacy-open-code-unused-3", 0), (4, 2, "legacy-closed-code-4", 0)]

_DATA = """
INSERT INTO components VALUES (1, 'C1', 'Компонент 1', 0.5), (2, 'C2', 'Компонент 2', 0.5);
INSERT INTO questions VALUES (1, 1, 'Питання 1', 1, 5, 'survey'), (2, 2, 'Питання 2', 1, 5, 'survey');
INSERT INTO units VALUES (1, 'Факультет 1'), (2, 'Факультет 2');
INSERT INTO cycles VALUES (1, 'Синтетичний відкритий', '2026-01-01', 'open', 5),
                          (2, 'Синтетичний закритий', '2025-01-01', 'closed', 5);
INSERT INTO cycle_configs VALUES (1, 'синтетичний', 'тест', '["cadets"]', 'demo-v1', NULL);
INSERT INTO response_sets VALUES (1, 1, 'cadets', 'Факультет 1'), (2, 2, 'npp', 'Факультет 2'),
                                 (3, 2, 'cadets', 'Факультет 1');
INSERT INTO answers VALUES (1, 1, 1, 4), (2, 1, 2, 5), (3, 2, 1, 3), (4, 2, 2, 2), (5, 3, 1, 1), (6, 3, 2, 5);
INSERT INTO access_token_policies VALUES (1, 'cadets', '2099-01-01 00:00:00.000000'),
                                         (2, 'cadets', '2099-01-01 00:00:00.000000');
INSERT INTO objective_indicators VALUES (1, 2, 1, 'Синтетичний показник', 50.0, 'data', 'auditor', 1);
INSERT INTO recommendations VALUES (1, 2, 1, 'Синтетична рекомендація', 'тест', 'done', 'Робоча група', NULL);
INSERT INTO audit_events VALUES (1, '2026-11-01 10:00:00.000000', 'admin', 'tokens.issue', 1, '{"count": 4}');
"""
_ACTION = """
INSERT INTO recommendation_actions VALUES (1, 2, 'abc123', 'low_score', 'C1', 'Синтетичний захід', 'demo',
    'accepted', 'Робоча група', '2099-01-01', 'тест', '[]', NULL, '[]',
    '2026-11-01 10:00:00.000000', '2026-11-01 10:00:00.000000');
"""


def make_legacy_db(path, version: int) -> None:
    """Синтетична БД версії 3 або 4 зі старою структурою (відкриті коди в access_tokens.token)."""
    assert version in (3, 4)
    with closing(sqlite3.connect(path)) as con:
        con.executescript((SCHEMA4_DDL if version == 4 else SCHEMA3_DDL) + _DATA)
        con.executemany("INSERT INTO access_tokens VALUES (?, ?, ?, ?)", LEGACY_CODES)
        if version == 4:
            con.executescript(_ACTION)
        con.execute(f"PRAGMA user_version = {version}")
        con.commit()


def table_rows(path) -> dict[str, list]:
    """Усі рядки всіх таблиць (крім access_tokens, де змінюється колонка) — для порівняння до/після."""
    with closing(sqlite3.connect(path)) as con:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: con.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
                for t in tables if t not in ("access_tokens", "audit_events")}
