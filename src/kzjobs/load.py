"""Database loading: raw inserts, staging reload and the SCD2 merge into core."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from kzjobs.transform.skills import SkillEntry

STAGING_COLUMNS = (
    "vacancy_id", "row_hash", "title", "employer_id", "employer_name", "area_name", "role_name",
    "experience", "employment", "schedule", "salary_from", "salary_to", "salary_currency",
    "salary_gross", "salary_from_kzt", "salary_to_kzt", "salary_flag", "published_at",
    "archived", "url", "has_details",
)  # fmt: skip


def insert_raw_vacancies(conn: psycopg.Connection, run_id: int, payloads: list[dict]) -> int:
    rows = []
    for p in payloads:
        try:
            vid = int(p["id"])
        except (KeyError, TypeError, ValueError):
            vid = None
        rows.append((run_id, vid, Jsonb(p)))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO raw.hh_vacancy (run_id, vacancy_id, payload) VALUES (%s, %s, %s)", rows
        )
    return len(rows)


def read_raw_vacancies(conn: psycopg.Connection, run_id: int) -> tuple[list[dict], int]:
    """Return payloads of a run (last copy wins per vacancy id) and the number of duplicates."""
    cur = conn.execute(
        "SELECT vacancy_id, payload FROM raw.hh_vacancy WHERE run_id = %s ORDER BY id", (run_id,)
    )
    unique: dict[int, dict] = {}
    anonymous: list[dict] = []
    total = 0
    for row in cur:
        total += 1
        if row["vacancy_id"] is None:
            anonymous.append(row["payload"])
        else:
            unique[row["vacancy_id"]] = row["payload"]
    payloads = [*unique.values(), *anonymous]
    return payloads, total - len(payloads)


def insert_raw_fx(conn: psycopg.Connection, run_id: int, rate_date: date, xml: str) -> None:
    conn.execute(
        "INSERT INTO raw.nbk_rates_xml (run_id, rate_date, xml) VALUES (%s, %s, %s)",
        (run_id, rate_date, xml),
    )


def upsert_rates(
    conn: psycopg.Connection, run_id: int, rate_date: date, rates: dict[str, Decimal]
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO core.currency_rate (rate_date, currency, rate_kzt, run_id)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (rate_date, currency)
               DO UPDATE SET rate_kzt = EXCLUDED.rate_kzt, run_id = EXCLUDED.run_id""",
            [(rate_date, code, rate, run_id) for code, rate in rates.items()],
        )


def latest_rates(conn: psycopg.Connection) -> tuple[date | None, dict[str, Decimal]]:
    """Newest known rate per currency. KZT itself is always 1."""
    cur = conn.execute(
        """SELECT DISTINCT ON (currency) currency, rate_kzt, rate_date
           FROM core.currency_rate ORDER BY currency, rate_date DESC"""
    )
    rows = cur.fetchall()
    rates = {r["currency"]: r["rate_kzt"] for r in rows}
    if not rates:
        return None, {}
    rates["KZT"] = Decimal(1)
    return max(r["rate_date"] for r in rows), rates


def known_vacancy_ids(conn: psycopg.Connection) -> set[int]:
    return {
        r["vacancy_id"]
        for r in conn.execute("SELECT DISTINCT vacancy_id FROM core.vacancy_version")
    }


def sync_skill_dictionary(conn: psycopg.Connection, entries: list[SkillEntry]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO core.skill (name, category) VALUES (%s, %s)
               ON CONFLICT (name) DO UPDATE SET category = EXCLUDED.category""",
            [(e.name, e.category) for e in entries],
        )


def insert_rejected(conn: psycopg.Connection, run_id: int, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO ops.rejected_record (run_id, source, vacancy_id, reasons, payload)
               VALUES (%s, 'hh', %s, %s, %s)""",
            [(run_id, i["vacancy_id"], i["reasons"], Jsonb(i["payload"])) for i in items],
        )


def reload_staging(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> None:
    conn.execute("TRUNCATE staging.vacancy, staging.vacancy_skill")
    cols = ", ".join(STAGING_COLUMNS)
    placeholders = ", ".join(f"%({c})s" for c in STAGING_COLUMNS)
    with conn.cursor() as cur:
        cur.executemany(f"INSERT INTO staging.vacancy ({cols}) VALUES ({placeholders})", rows)
        cur.executemany(
            "INSERT INTO staging.vacancy_skill (vacancy_id, skill_name) VALUES (%s, %s)",
            [(r["vacancy_id"], s) for r in rows for s in r["skills"]],
        )


def merge_scd2(conn: psycopg.Connection, run_id: int, ts: datetime) -> dict[str, int]:
    """Apply the staged batch to ``core`` with Slowly Changing Dimension type 2 semantics."""
    staged = conn.execute("SELECT count(*) AS n FROM staging.vacancy").fetchone()["n"]
    brand_new = conn.execute(
        """SELECT count(*) AS n FROM staging.vacancy s
           WHERE NOT EXISTS (SELECT 1 FROM core.vacancy_version v WHERE v.vacancy_id = s.vacancy_id)"""
    ).fetchone()["n"]

    conn.execute(
        """INSERT INTO core.employer (employer_id, name)
           SELECT DISTINCT ON (employer_id) employer_id, COALESCE(employer_name, '(unknown)')
           FROM staging.vacancy WHERE employer_id IS NOT NULL
           ORDER BY employer_id
           ON CONFLICT (employer_id) DO UPDATE SET name = EXCLUDED.name, updated_at = now()"""
    )

    closed = conn.execute(
        """UPDATE core.vacancy_version v
           SET valid_to = %s, is_current = FALSE
           FROM staging.vacancy s
           WHERE v.vacancy_id = s.vacancy_id AND v.is_current AND v.row_hash <> s.row_hash""",
        (ts,),
    ).rowcount

    inserted = conn.execute(
        """INSERT INTO core.vacancy_version (
               vacancy_id, row_hash, title, employer_id, area_name, role_name, experience,
               employment, schedule, salary_from, salary_to, salary_currency, salary_gross,
               salary_from_kzt, salary_to_kzt, salary_flag, published_at, archived, url,
               valid_from, valid_to, is_current, run_id)
           SELECT s.vacancy_id, s.row_hash, s.title, s.employer_id, s.area_name, s.role_name,
                  s.experience, s.employment, s.schedule, s.salary_from, s.salary_to,
                  s.salary_currency, s.salary_gross, s.salary_from_kzt, s.salary_to_kzt,
                  s.salary_flag, s.published_at, s.archived, s.url, %s, NULL, TRUE, %s
           FROM staging.vacancy s
           WHERE NOT EXISTS (
               SELECT 1 FROM core.vacancy_version v
               WHERE v.vacancy_id = s.vacancy_id AND v.is_current)""",
        (ts, run_id),
    ).rowcount

    conn.execute(
        """DELETE FROM core.vacancy_skill
           WHERE vacancy_id IN (SELECT vacancy_id FROM staging.vacancy WHERE has_details)"""
    )
    conn.execute(
        """INSERT INTO core.vacancy_skill (vacancy_id, skill_id)
           SELECT ss.vacancy_id, k.skill_id
           FROM staging.vacancy_skill ss
           JOIN staging.vacancy sv ON sv.vacancy_id = ss.vacancy_id
           JOIN core.skill k ON k.name = ss.skill_name
           WHERE sv.has_details
              OR NOT EXISTS (SELECT 1 FROM core.vacancy_skill x WHERE x.vacancy_id = ss.vacancy_id)
           ON CONFLICT DO NOTHING"""
    )
    return {
        "staged": staged,
        "new": brand_new,
        "changed": closed,
        "unchanged": staged - inserted,
        "versions_written": inserted,
    }
