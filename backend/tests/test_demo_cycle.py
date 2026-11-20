"""
Генератор синтетичного демо-циклу (app/demo_cycle.py).

Кожен тест працює з КОПІЄЮ спільної тестової БД (seed із conftest.py), тож інші тести не бачать нових циклів.
"""
import json
import re
import sqlite3
from contextlib import closing
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import demo_cycle
from app.database import DB_PATH, get_db
from app.main import app
from app.models import (AccessToken, AccessTokenPolicy, Answer, AuditEvent, Cycle, CycleConfig, InstanceMeta,
                        Question, ResponseSet)
from app.services import narrative

TODAY = date(2026, 11, 20)
NAME = "Демо тест"


def _copy_db(target):
    with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    engine = create_engine(f"sqlite:///{target}", hide_parameters=True)
    return engine


def _counts(engine) -> dict:
    with closing(sqlite3.connect(engine.url.database)) as con:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                            "AND name NOT LIKE 'sqlite_%'")]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


@pytest.fixture
def engine(tmp_path):
    eng = _copy_db(tmp_path / "demo.db")
    yield eng
    eng.dispose()


def _run(engine, *, responses=150, seed=2026, name=NAME, confirm=True):
    lines = []
    code = demo_cycle.run(engine, responses=responses, seed=seed, name=name, confirm=confirm,
                          today=TODAY, out=lines.append)
    return code, lines


def _cycle(engine, name=NAME) -> Cycle | None:
    with Session(engine) as db:
        return db.query(Cycle).filter_by(name=name).one_or_none()


def _results(engine, cycle_id):
    def override():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = override
    try:
        response = TestClient(app).get(f"/api/assessments/{cycle_id}/results", headers={"X-Role": "admin"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


# --- План ---------------------------------------------------------------------------------------------

def test_plan_changes_nothing(engine):
    before = _counts(engine)
    code, lines = _run(engine, confirm=False)
    assert code == demo_cycle.EXIT_OK
    assert _counts(engine) == before
    text = "\n".join(lines)
    assert "Лише план" in text and "mgmt 4, npp 43, cadets 100, staff 3" in text
    assert "приховані порогом k категорії: mgmt, staff" in text


def test_category_counts_have_hidden_small_groups():
    counts = demo_cycle.category_counts(150)
    assert sum(counts.values()) == 150
    assert counts["cadets"] > counts["npp"] > counts["mgmt"] >= counts["staff"]
    assert counts["mgmt"] < 5 and counts["staff"] < 5 and counts["mgmt"] + counts["staff"] >= 5


# --- Генерація ----------------------------------------------------------------------------------------

def test_generate_creates_closed_cycle_with_valid_answers(engine):
    before = _counts(engine)
    code, lines = _run(engine)
    assert code == demo_cycle.EXIT_OK, lines
    with Session(engine) as db:
        cycle = db.query(Cycle).filter_by(name=NAME).one()
        assert cycle.status == "closed" and cycle.min_group_size == 5
        config = db.get(CycleConfig, cycle.id)
        assert config.description == "Демонстраційні синтетичні дані"
        assert json.loads(config.categories_json) == ["mgmt", "npp", "cadets", "staff"]
        assert cycle.start_date < config.end_date < TODAY
        questions = {q.id: q for q in db.query(Question).filter_by(kind="survey")}
        sets = db.query(ResponseSet).filter_by(cycle_id=cycle.id).all()
        assert len(sets) == 150
        for rs in sets:
            assert sorted(a.question_id for a in rs.answers) == sorted(questions)
            for a in rs.answers:
                assert questions[a.question_id].scale_min <= a.value <= questions[a.question_id].scale_max
        tokens = db.query(AccessToken).filter_by(cycle_id=cycle.id).all()
        assert sum(t.used for t in tokens) == 150 and sum(not t.used for t in tokens) == 30
        assert all(re.fullmatch(r"[0-9a-f]{64}", t.token_hash) for t in tokens)
        policies = db.query(AccessTokenPolicy).filter(AccessTokenPolicy.token_id.in_([t.id for t in tokens])).all()
        assert len(policies) == len(tokens)
        assert {p.category for p in policies} == {"mgmt", "npp", "cadets", "staff"}
        assert all(p.expires_at.date() < TODAY for p in policies)
        events = db.query(AuditEvent).filter_by(action="demo.cycle_generated").all()
        assert len(events) == 1
        assert (events[0].actor_role, events[0].assessment_id, events[0].actor_user_id) == ("server", cycle.id, None)
        assert json.loads(events[0].details) == {"count": 150}
        answers = db.query(Answer).join(ResponseSet).filter(ResponseSet.cycle_id == cycle.id).count()
    after = _counts(engine)
    assert after["cycles"] == before["cycles"] + 1
    assert after["response_sets"] == before["response_sets"] + 150
    assert after["answers"] == before["answers"] + answers
    assert after["audit_events"] == before["audit_events"] + 1


def test_same_seed_gives_same_aggregates(tmp_path):
    first, second, other = (_copy_db(tmp_path / f"{n}.db") for n in ("a", "b", "c"))
    try:
        assert _run(first)[0] == _run(second)[0] == _run(other, seed=7)[0] == 0
        res_a = _results(first, _cycle(first).id)
        res_b = _results(second, _cycle(second).id)
        res_c = _results(other, _cycle(other).id)
        assert res_a == res_b
        assert res_a["components"] != res_c["components"]
    finally:
        for eng in (first, second, other):
            eng.dispose()


def test_plan_averages_match_written_results(engine):
    _, plan_lines = _run(engine, confirm=False)
    assert _run(engine)[0] == 0
    results = _results(engine, _cycle(engine).id)
    scores = ", ".join(f"{c['code']} {c['score']}" for c in results["components"])
    assert any(scores in line for line in plan_lines)


# --- Відмови ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "real"])
def test_refuses_without_synthetic_marker(engine, value):
    with Session(engine) as db:
        marker = db.get(InstanceMeta, "dataset")
        if value is None:
            db.delete(marker)
        else:
            marker.value = value
        db.commit()
    before = _counts(engine)
    for confirm in (False, True):
        code, lines = _run(engine, confirm=confirm)
        assert code == demo_cycle.EXIT_REFUSED
        assert "синтетична" in lines[-1]
    assert _counts(engine) == before


def test_repeated_name_is_refused_without_changes(engine):
    assert _run(engine)[0] == 0
    before = _counts(engine)
    code, lines = _run(engine, seed=99)
    assert code == demo_cycle.EXIT_REFUSED and "уже є" in lines[-1]
    assert _counts(engine) == before


@pytest.mark.parametrize("kwargs", [{"responses": 10}, {"responses": 5000}, {"name": "   "}, {"name": "x" * 51}])
def test_bad_arguments_are_refused(engine, kwargs):
    before = _counts(engine)
    assert _run(engine, **kwargs)[0] == demo_cycle.EXIT_REFUSED
    assert _counts(engine) == before


def test_outdated_schema_is_error_without_migration(engine):
    with closing(sqlite3.connect(engine.url.database)) as con:
        con.execute("PRAGMA user_version = 5")
        con.commit()
    before = _counts(engine)
    code, lines = _run(engine)
    assert code == demo_cycle.EXIT_ERROR and "Схема" in lines[-1]
    assert _counts(engine) == before
    with closing(sqlite3.connect(engine.url.database)) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 5


def test_release_needs_only_integrity_db(engine, monkeypatch):
    monkeypatch.setenv("APP_ENV", "release")
    monkeypatch.delenv("V2_SECRET_KEY", raising=False)
    assert _run(engine, confirm=False)[0] == demo_cycle.EXIT_OK          # секрет не потрібен
    monkeypatch.delenv("INTEGRITY_DB")
    code, lines = _run(engine, confirm=False)
    assert code == demo_cycle.EXIT_ERROR and "INTEGRITY_DB" in lines[-1]


def test_cli_main_plan_on_shared_db():
    before = _counts(create_engine(f"sqlite:///{DB_PATH}"))
    assert demo_cycle.main(["--responses", "40", "--seed", "1"]) == 0
    assert _counts(create_engine(f"sqlite:///{DB_PATH}")) == before
    with pytest.raises(SystemExit) as exc:
        demo_cycle.main(["--responses", "abc"])
    assert exc.value.code == 2


# --- Результати й факти для LM ---------------------------------------------------------------------------

def test_results_show_main_groups_and_suppress_small(engine):
    assert _run(engine)[0] == 0
    results = _results(engine, _cycle(engine).id)
    assert results["responses_total"] == 150 and results["min_group_size"] == 5
    assert results["suppressed"] is True
    assert {c["category"]: c["responses"] for c in results["categories"]} == {"cadets": 100, "npp": 43}
    for comp in results["components"]:
        assert comp["score"] is not None
        assert {cell["category"] for cell in comp["by_category"]} == {"cadets", "npp"}
    scores = {c["code"]: c["score"] for c in results["components"]}
    assert min(scores, key=scores.get) == "C6"
    by_cat = {c["code"]: {x["category"]: x["score"] for x in c["by_category"]} for c in results["components"]}
    assert by_cat["C6"]["cadets"] < by_cat["C6"]["npp"]


def test_narrative_facts_have_expected_strong_and_weak(engine):
    assert _run(engine)[0] == 0
    cycle_id = _cycle(engine).id
    with Session(engine) as db:
        base_id = db.query(Cycle).filter_by(name="2026-I").one().id
        facts = narrative.collect_facts(db, "summary", cycle_id)
        compare = narrative.collect_facts(db, "compare", cycle_id, base_id)
        narrative.build_messages(facts)
        narrative.build_messages(compare)
    assert facts["weakest"][0] == "C6"
    assert set(facts["strongest"]) == {"C5", "C2"}
    assert facts["participation"] == {"tokens_issued": 180, "responses_total": 150, "participation_percent": 83.3}
    assert facts["hidden_groups_note"].startswith("Частину малих груп")
    assert {c["category"] for c in facts["categories"]} == {"Курсанти", "Науково-педагогічні працівники"}
    assert compare["target"]["cycle"]["id"] == cycle_id and compare["category_changes"]
    assert all(change["change"] is not None for change in compare["component_changes"])


def test_no_open_codes_in_db_or_output(engine):
    code, lines = _run(engine)
    assert code == 0
    output = "\n".join(lines)
    assert not re.search(r"[0-9a-f]{16,}", output)
    with closing(sqlite3.connect(engine.url.database)) as con:
        cycle_id = con.execute("SELECT id FROM cycles WHERE name = ?", (NAME,)).fetchone()[0]
        hashes = [r[0] for r in con.execute("SELECT token_hash FROM access_tokens WHERE cycle_id = ?", (cycle_id,))]
        assert len(hashes) == 180 and len(set(hashes)) == 180
        assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes)
        # Коди доступу (32 hex) ніде не лежать у відкритому вигляді: жодне текстове поле не є кодом
        for table, in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            for row in con.execute(f'SELECT * FROM "{table}"'):
                for value in row:
                    assert not (isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value))


def test_no_small_groups_plan_has_only_large_cells():
    from collections import Counter
    from datetime import date
    questions = [demo_cycle.QuestionSpec(i, f"C{i}", 1, 5) for i in range(1, 8)]
    units = ["Кафедра загальних дисциплін", "Факультет 1", "Факультет 2"]
    plan = demo_cycle.build_plan(name="T", seed=7, total=150, questions=questions, units=units,
                                 today=date(2026, 11, 20), unit_safe=True)
    cells = Counter((category, unit) for category, unit, _ in plan.responses)
    assert len(plan.responses) == 150
    assert all(n > demo_cycle.MIN_GROUP_SIZE for n in cells.values())
    assert {c for c, _ in cells} == set(demo_cycle.CATEGORIES)
    assert plan.hidden_categories == []


def test_no_small_groups_refuses_too_few_responses():
    from datetime import date
    import pytest
    questions = [demo_cycle.QuestionSpec(1, "C1", 1, 5)]
    with pytest.raises(demo_cycle.DemoRefused):
        demo_cycle.build_plan(name="T", seed=1, total=40, questions=questions,
                              units=["A", "B", "C"], today=date(2026, 11, 20), unit_safe=True)
