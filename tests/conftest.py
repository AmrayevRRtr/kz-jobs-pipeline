from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from kzjobs.config import Settings

MIGRATIONS = sorted((Path(__file__).resolve().parents[1] / "migrations").glob("V*.sql"))
SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"


@pytest.fixture(scope="session")
def db_url() -> str:
    """Integration tests need a real PostgreSQL: set TEST_DATABASE_URL, otherwise they are skipped."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    with psycopg.connect(url, autocommit=True) as conn:
        for schema in ("mart", "core", "staging", "raw", "ops"):
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        for migration in MIGRATIONS:
            conn.execute(migration.read_text(encoding="utf-8"))
    return url


@pytest.fixture
def settings(db_url: str) -> Settings:
    """Fresh data for every test: truncate all tables, keep the schema."""
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            """TRUNCATE ops.pipeline_run, ops.rejected_record, raw.hh_vacancy, raw.nbk_rates_xml,
                        core.currency_rate, core.employer, core.skill, core.vacancy_version,
                        core.vacancy_skill, staging.vacancy, staging.vacancy_skill
               RESTART IDENTITY CASCADE"""
        )
    return Settings(database_url=db_url)


@pytest.fixture(scope="session")
def fx_xml() -> str:
    return (SAMPLE_DIR / "nbk_rates.xml").read_text(encoding="utf-8")
