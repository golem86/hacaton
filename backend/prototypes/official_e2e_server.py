"""E2E-only server backed by a disposable synthetic schema-3 copy.

Never import this module from app.main or deploy it. It refuses to start unless
an explicitly named disposable DB inside the OS temp directory is configured.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException

from .official_expert import CATALOG
from .questionnaire_integration import (
    IntegrationStore, apply_questionnaire_migration, create_integration_test_app,
    create_synthetic_schema3_copy, create_synthetic_schema3_source,
)


def _prepare(db_path: Path) -> IntegrationStore:
    source = db_path.with_name("official-e2e.schema3-synthetic.sqlite")
    if db_path.exists() or source.exists():
        raise RuntimeError("E2E synthetic database paths must be new")
    create_synthetic_schema3_source(source)
    create_synthetic_schema3_copy(source, db_path)
    apply_questionnaire_migration(db_path, allow_test_migration=True)
    store = IntegrationStore(db_path)
    templates = ("appendix-v-form-1", "appendix-v-form-2")
    for template_id in templates:
        form = 1 if template_id.endswith("1") else 2
        version = "2.1.0"
        catalog = CATALOG[(template_id, version)]
        questions = [{
            "id": question_id,
            "section": "synthetic-section",
            "text": "Synthetic question fixture",
            "source_duplicate": form == 1 and index in {4, 5},
            "options": [{"id": option_id, "text": "Synthetic descriptive choice"}
                        for option_id in sorted(option_ids)],
        } for index, (question_id, option_ids) in enumerate(catalog.items(), start=1)]
        store.seed_template(template_id, version, form, questions)
    now = datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE cycle_configs SET categories_json=? WHERE cycle_id=1",
                    (json.dumps(["synthetic-working-group"]),))
        con.execute("INSERT INTO cycles(id,name,start_date,status,min_group_size) "
                    "VALUES (2,'Synthetic official form 2','2026-02-01','draft',5)")
        con.execute("INSERT INTO cycle_configs(cycle_id,description,scope,categories_json,questionnaire_version) "
                    "VALUES (2,'Synthetic E2E','test',?, 'demo-v1')",
                    (json.dumps(["synthetic-ambiguous-review"]),))
        for cycle_id, code, category in (
            (1, "e2e-only-form1-2.1", "synthetic-working-group"),
            (2, "e2e-only-form2-2.1", "synthetic-ambiguous-review"),
        ):
            token_id = con.execute("INSERT INTO access_tokens(cycle_id,token,used) VALUES (?,?,0)",
                                   (cycle_id, code)).lastrowid
            expiry = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
            con.execute("INSERT INTO access_token_policies(token_id,category,expires_at) VALUES (?,?,?)",
                        (token_id, category, expiry))
    store.bind_cycle(1, templates[0], "2.1.0")
    store.bind_cycle(2, templates[1], "2.1.0")
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE cycles SET status='open' WHERE id IN (1,2)")
    return store


def create_e2e_app() -> FastAPI:
    configured = os.environ.get("QUESTIONNAIRE_E2E_DB")
    if not configured:
        raise RuntimeError("QUESTIONNAIRE_E2E_DB must be set for the E2E-only server")
    db_path = Path(configured).resolve()
    store = _prepare(db_path)
    app, store = create_integration_test_app(db_path, store)

    @app.get("/_e2e/health")
    def health():
        return {"ready": True, "scope": "synthetic-only"}

    @app.get("/_e2e/verify/{cycle_id}")
    def verify(cycle_id: int):
        # Fresh connection: the browser E2E verifies durable rows as after restart.
        with sqlite3.connect(db_path) as con:
            binding = con.execute("SELECT template_id,version FROM cycle_questionnaires WHERE cycle_id=?",
                                  (cycle_id,)).fetchone()
            response = con.execute("SELECT template_id,version,category FROM official_response_sets "
                                   "WHERE cycle_id=?", (cycle_id,)).fetchone()
            count = con.execute("SELECT COUNT(*) FROM official_response_sets WHERE cycle_id=?",
                                (cycle_id,)).fetchone()[0]
            answer_count = con.execute("SELECT COUNT(*) FROM official_answers a JOIN official_response_sets s "
                                       "USING(response_set_id) WHERE s.cycle_id=?", (cycle_id,)).fetchone()[0]
            code = con.execute("SELECT used FROM access_tokens WHERE cycle_id=? AND token LIKE 'e2e-only-%'",
                               (cycle_id,)).fetchone()
            numeric_count = con.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
            response_columns = {r[1] for r in con.execute("PRAGMA table_info(official_response_sets)")}
        return {
            "binding": list(binding) if binding else None,
            "response": list(response) if response else None,
            "response_sets": count,
            "official_answers": answer_count,
            "code_used": bool(code and code[0]),
            "numeric_answers": numeric_count,
            "respondent_link_columns": sorted({"user_id", "respondent_id", "token"} & response_columns),
        }

    return app


app = create_e2e_app()
