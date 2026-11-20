"""E2E-only server backed by a disposable synthetic integrity-schema-5 copy.

Never import this module from app.main or deploy it. It refuses to start unless
an explicitly named disposable DB inside the OS temp directory is configured.
Коди доступу зберігаються лише як SHA-256 (access_tokens.token_hash, schema 5).
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI

from app.models import hash_access_code

from .official_expert import CATALOG
from .questionnaire_integration import (
    SYNTHETIC_SOURCE_SUFFIX, IntegrationStore, apply_questionnaire_migration, create_integration_test_app,
    create_synthetic_schema5_copy, create_synthetic_schema5_source,
)

# Синтетичні коди лише для E2E-стенду: у БД потрапляє тільки їхній хеш.
E2E_CYCLES = {
    1: ("appendix-v-form-1", "e2e-only-form1-2.1", "synthetic-working-group"),
    2: ("appendix-v-form-2", "e2e-only-form2-2.1", "synthetic-ambiguous-review"),
}
E2E_VERSION = "2.1.0"


def _prepare(db_path: Path) -> IntegrationStore:
    source = db_path.with_name(f"official-e2e{SYNTHETIC_SOURCE_SUFFIX}")
    if db_path.exists() or source.exists():
        raise RuntimeError("E2E synthetic database paths must be new")
    create_synthetic_schema5_source(source)
    create_synthetic_schema5_copy(source, db_path)
    apply_questionnaire_migration(db_path, allow_test_migration=True)
    store = IntegrationStore(db_path)
    for template_id, _code, _category in E2E_CYCLES.values():
        form = 1 if template_id.endswith("1") else 2
        catalog = CATALOG[(template_id, E2E_VERSION)]
        questions = [{
            "id": question_id,
            "section": "synthetic-section",
            "text": "Synthetic question fixture",
            "source_duplicate": form == 1 and index in {4, 5},
            "options": [{"id": option_id, "text": "Synthetic descriptive choice"}
                        for option_id in sorted(option_ids)],
        } for index, (question_id, option_ids) in enumerate(catalog.items(), start=1)]
        store.seed_template(template_id, E2E_VERSION, form, questions)
    now = datetime.now(timezone.utc)
    with sqlite3.connect(db_path) as con:
        con.execute("UPDATE cycle_configs SET categories_json=? WHERE cycle_id=1",
                    (json.dumps([E2E_CYCLES[1][2]]),))
        con.execute("INSERT INTO cycles(id,name,start_date,status,min_group_size) "
                    "VALUES (2,'Synthetic official form 2','2026-02-01','draft',5)")
        con.execute("INSERT INTO cycle_configs(cycle_id,description,scope,categories_json,questionnaire_version) "
                    "VALUES (2,'Synthetic E2E','test',?, 'demo-v1')", (json.dumps([E2E_CYCLES[2][2]]),))
        for cycle_id, (_template_id, code, category) in E2E_CYCLES.items():
            token_id = con.execute("INSERT INTO access_tokens(cycle_id,token_hash,used) VALUES (?,?,0)",
                                   (cycle_id, hash_access_code(code))).lastrowid
            expiry = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
            con.execute("INSERT INTO access_token_policies(token_id,category,expires_at) VALUES (?,?,?)",
                        (token_id, category, expiry))
    for cycle_id, (template_id, _code, _category) in E2E_CYCLES.items():
        store.bind_cycle(cycle_id, template_id, E2E_VERSION)
        store.activate_cycle(cycle_id)
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
        code = E2E_CYCLES.get(cycle_id, (None, "", None))[1]
        with sqlite3.connect(db_path) as con:
            binding = con.execute("SELECT template_id,version FROM cycle_questionnaires WHERE cycle_id=?",
                                  (cycle_id,)).fetchone()
            response = con.execute("SELECT template_id,version,category FROM official_response_sets "
                                   "WHERE cycle_id=?", (cycle_id,)).fetchone()
            count = con.execute("SELECT COUNT(*) FROM official_response_sets WHERE cycle_id=?",
                                (cycle_id,)).fetchone()[0]
            answer_count = con.execute("SELECT COUNT(*) FROM official_answers a JOIN official_response_sets s "
                                       "USING(response_set_id) WHERE s.cycle_id=?", (cycle_id,)).fetchone()[0]
            used = con.execute("SELECT used FROM access_tokens WHERE cycle_id=? AND token_hash=?",
                               (cycle_id, hash_access_code(code))).fetchone()
            plaintext = con.execute("SELECT COUNT(*) FROM access_tokens WHERE token_hash=?", (code,)).fetchone()[0]
            numeric_count = con.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
            schema_version = con.execute("PRAGMA user_version").fetchone()[0]
            response_columns = {r[1] for r in con.execute("PRAGMA table_info(official_response_sets)")}
        return {
            "schema_version": schema_version,
            "binding": list(binding) if binding else None,
            "response": list(response) if response else None,
            "response_sets": count,
            "official_answers": answer_count,
            "code_used": bool(used and used[0]),
            "plaintext_codes_stored": plaintext,
            "numeric_answers": numeric_count,
            "respondent_link_columns": sorted({"user_id", "respondent_id", "token", "token_hash"} & response_columns),
        }

    return app


app = create_e2e_app()
