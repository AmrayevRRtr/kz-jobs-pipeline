"""Pipeline steps. Each step is a plain function so it can be run from the CLI, tests or Airflow."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, date, datetime

import httpx
from psycopg.types.json import Jsonb

from kzjobs import load
from kzjobs.config import Settings
from kzjobs.db import connect
from kzjobs.extract.hh import HHClient
from kzjobs.extract.nbk import NBKError, fetch_rates_xml, parse_rates
from kzjobs.transform.normalize import normalize_vacancy
from kzjobs.transform.skills import SkillMatcher
from kzjobs.validate import validate

log = logging.getLogger(__name__)

MAX_FX_AGE_DAYS = 5


class QualityGateError(RuntimeError):
    """Raised when too many records are rejected; the core layer is left untouched."""


def start_run(settings: Settings, source: str = "hh+nbk") -> int:
    with connect(settings.database_url) as conn:
        row = conn.execute(
            "INSERT INTO ops.pipeline_run (source) VALUES (%s) RETURNING run_id", (source,)
        ).fetchone()
        return row["run_id"]


def finish_run(
    settings: Settings, run_id: int, status: str | None = None, error: str | None = None
) -> str:
    """Close a run. If status is omitted it is inferred: a run that produced load stats succeeded."""
    with connect(settings.database_url) as conn:
        if status is None:
            row = conn.execute(
                "SELECT stats FROM ops.pipeline_run WHERE run_id = %s", (run_id,)
            ).fetchone()
            status = "success" if row and "versions" in row["stats"] else "failed"
        conn.execute(
            "UPDATE ops.pipeline_run SET status = %s, finished_at = now(), error = %s WHERE run_id = %s",
            (status, error, run_id),
        )
    return status


def _merge_stats(conn, run_id: int, patch: dict) -> None:
    conn.execute(
        "UPDATE ops.pipeline_run SET stats = stats || %s WHERE run_id = %s", (Jsonb(patch), run_id)
    )


def extract_fx(
    settings: Settings, run_id: int, on: date | None = None, xml: str | None = None
) -> dict:
    """Fetch (or accept) the NBK rates, keep the raw XML and upsert parsed rates."""
    on = on or datetime.now(UTC).date()
    try:
        xml = xml or fetch_rates_xml(settings, on)
        rate_date, rates = parse_rates(xml, fallback_date=on)
    except (NBKError, httpx.HTTPError) as exc:
        log.warning("NBK rates unavailable (%s); falling back to stored rates", exc)
        with connect(settings.database_url) as conn:
            _merge_stats(conn, run_id, {"fx": {"status": "fallback", "reason": str(exc)}})
        return {"status": "fallback"}

    with connect(settings.database_url) as conn:
        load.insert_raw_fx(conn, run_id, rate_date, xml)
        load.upsert_rates(conn, run_id, rate_date, rates)
        _merge_stats(
            conn,
            run_id,
            {"fx": {"status": "ok", "rate_date": rate_date.isoformat(), "currencies": len(rates)}},
        )
    return {"status": "ok", "rate_date": rate_date.isoformat(), "currencies": len(rates)}


def extract_hh(
    settings: Settings,
    run_id: int,
    payloads: list[dict] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Fetch vacancies from hh (or accept ready payloads, used by the offline demo) into raw."""
    if payloads is None:
        with connect(settings.database_url) as conn:
            known = load.known_vacancy_ids(conn)
        client = HHClient(settings, transport=transport)
        try:
            payloads = client.fetch(known)
        finally:
            client.close()
    with connect(settings.database_url) as conn:
        count = load.insert_raw_vacancies(conn, run_id, payloads)
        _merge_stats(conn, run_id, {"extracted": count})
    return {"extracted": count}


def transform_load(settings: Settings, run_id: int, now: datetime | None = None) -> dict:
    """raw -> validated staging -> SCD2 merge into core. Returns (and stores) the quality report."""
    now = now or datetime.now(UTC)
    matcher = SkillMatcher.from_csv(settings.skills_csv)

    with connect(settings.database_url) as conn:
        fx_date, rates = load.latest_rates(conn)
        if not rates:
            raise RuntimeError("no exchange rates available: run extract_fx first")
        fx_age = (now.date() - fx_date).days
        if fx_age > MAX_FX_AGE_DAYS:
            raise RuntimeError(f"exchange rates are {fx_age} days old (limit {MAX_FX_AGE_DAYS})")

        payloads, duplicates = load.read_raw_vacancies(conn, run_id)
        valid_rows: list[dict] = []
        rejected: list[dict] = []
        warnings: Counter[str] = Counter()
        for payload in payloads:
            row = normalize_vacancy(payload, matcher, rates)
            result = validate(row, now)
            if result.errors:
                rejected.append(
                    {"vacancy_id": row["vacancy_id"], "reasons": result.errors, "payload": payload}
                )
                continue
            warnings.update(result.warnings)
            valid_rows.append(row)

        total = len(payloads)
        rejected_pct = round(100.0 * len(rejected) / total, 2) if total else 0.0
        report = {
            "unique_records": total,
            "duplicates_dropped": duplicates,
            "valid": len(valid_rows),
            "rejected": len(rejected),
            "rejected_pct": rejected_pct,
            "rejection_reasons": dict(Counter(r for item in rejected for r in item["reasons"])),
            "warnings": dict(warnings),
            "salary_coverage_pct": _pct(
                sum(1 for r in valid_rows if r["salary_from_kzt"] or r["salary_to_kzt"]),
                len(valid_rows),
            ),
            "skills_coverage_pct": _pct(sum(1 for r in valid_rows if r["skills"]), len(valid_rows)),
            "fx_date": fx_date.isoformat(),
            "fx_age_days": fx_age,
        }

        load.insert_rejected(conn, run_id, rejected)
        _merge_stats(conn, run_id, {"quality": report})
        conn.commit()  # keep the rejected rows even if the gate below stops the run

        if rejected_pct > settings.reject_threshold_pct:
            raise QualityGateError(
                f"{rejected_pct}% rejected exceeds the {settings.reject_threshold_pct}% threshold; core not updated"
            )

        load.sync_skill_dictionary(conn, matcher.entries)
        load.reload_staging(conn, valid_rows)
        versions = load.merge_scd2(conn, run_id, now)
        _merge_stats(conn, run_id, {"versions": versions})
    return {**report, "versions": versions}


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def refresh_marts(settings: Settings) -> None:
    with connect(settings.database_url) as conn:
        conn.execute("REFRESH MATERIALIZED VIEW mart.skill_demand_weekly")
        conn.execute("REFRESH MATERIALIZED VIEW mart.salary_by_role")


def run_all(
    settings: Settings,
    hh_payloads: list[dict] | None = None,
    fx_xml: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Run the whole pipeline in-process (CLI, demo, tests). Airflow calls the steps separately."""
    now = now or datetime.now(UTC)
    run_id = start_run(settings)
    try:
        extract_fx(settings, run_id, on=now.date(), xml=fx_xml)
        extract_hh(settings, run_id, payloads=hh_payloads)
        report = transform_load(settings, run_id, now=now)
        refresh_marts(settings)
    except Exception as exc:
        finish_run(settings, run_id, "failed", error=str(exc))
        raise
    finish_run(settings, run_id, "success")
    return {"run_id": run_id, **report}
