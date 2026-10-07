from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from src.db.session import make_engine, create_schema

ROOT = Path(__file__).resolve().parents[1]


def test_sqlite_schema_has_normalized_action_platform_tables(tmp_path):
    url = f"sqlite:///{(tmp_path / 'schema.db').as_posix()}"
    engine = make_engine(url)
    create_schema(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"fields", "field_observations", "intelligence_results", "balers", "buyers",
            "dispatch_runs", "dispatch_routes", "dispatch_stops", "buyer_allocations",
            "collection_jobs", "verification_cases", "verification_observations",
            "certificates", "audit_events"}.issubset(tables)
    engine.dispose()


def test_sqlite_connection_enforces_foreign_keys(tmp_path):
    url = f"sqlite:///{(tmp_path / 'fk.db').as_posix()}"
    engine = make_engine(url)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    engine.dispose()


def test_alembic_initial_migration_builds_a_blank_database(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    engine = make_engine(url)
    names = set(inspect(engine).get_table_names())
    assert "alembic_version" in names
    assert "fields" in names and "certificates" in names and "audit_events" in names
    engine.dispose()
