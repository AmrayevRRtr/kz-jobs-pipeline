"""End-to-end tests on a real PostgreSQL (migrations applied exactly as Flyway would)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kzjobs.db import connect
from kzjobs.pipeline import QualityGateError, run_all
from tests.helpers import make_payload

T1 = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)
T2 = T1 + timedelta(days=1)


def kzt(frm, to=None):
    return {"from": frm, "to": to, "currency": "KZT", "gross": False}


def rows(settings, sql, params=()):
    with connect(settings.database_url) as conn:
        return conn.execute(sql, params).fetchall()


def test_first_load_creates_current_versions(settings, fx_xml):
    report = run_all(settings, [make_payload(1, salary=kzt(600000)), make_payload(2)], fx_xml, T1)
    assert report["versions"]["new"] == 2
    versions = rows(settings, "SELECT vacancy_id, is_current, valid_to FROM core.vacancy_version")
    assert len(versions) == 2 and all(v["is_current"] and v["valid_to"] is None for v in versions)
    run = rows(settings, "SELECT status, finished_at FROM ops.pipeline_run")[0]
    assert run["status"] == "success" and run["finished_at"] is not None


def test_rerun_with_same_data_writes_nothing(settings, fx_xml):
    payloads = [make_payload(1, salary=kzt(600000))]
    run_all(settings, payloads, fx_xml, T1)
    second = run_all(settings, payloads, fx_xml, T2)
    assert second["versions"]["unchanged"] == 1 and second["versions"]["versions_written"] == 0
    assert rows(settings, "SELECT count(*) AS n FROM core.vacancy_version")[0]["n"] == 1


def test_change_closes_old_version_and_opens_new_one(settings, fx_xml):
    run_all(settings, [make_payload(1, salary=kzt(600000))], fx_xml, T1)
    report = run_all(settings, [make_payload(1, salary=kzt(750000))], fx_xml, T2)
    assert report["versions"]["changed"] == 1

    old, new = rows(settings, "SELECT * FROM core.vacancy_version ORDER BY valid_from")
    assert old["is_current"] is False and old["valid_to"] == T2 and old["salary_from"] == 600000
    assert new["is_current"] is True and new["valid_from"] == T2 and new["salary_from"] == 750000
    assert new["salary_mid_kzt"] == 750000


def test_only_one_current_version_is_allowed_by_the_database(settings, fx_xml):
    import psycopg

    run_all(settings, [make_payload(1)], fx_xml, T1)
    with pytest.raises(psycopg.errors.UniqueViolation), connect(settings.database_url) as conn:
        conn.execute(
            """INSERT INTO core.vacancy_version (vacancy_id, row_hash, title, published_at,
                   valid_from, run_id) VALUES (1, 'x', 't', now(), now(), 1)"""
        )


def test_invalid_records_are_rejected_with_reasons_and_valid_ones_load(settings, fx_xml):
    payloads = [make_payload(i) for i in range(1, 20)] + [make_payload(99, name="")]
    report = run_all(settings, payloads, fx_xml, T1)
    assert report["rejected"] == 1 and report["rejection_reasons"] == {"missing_title": 1}
    rej = rows(settings, "SELECT vacancy_id, reasons FROM ops.rejected_record")
    assert rej == [{"vacancy_id": 99, "reasons": ["missing_title"]}]
    assert rows(settings, "SELECT count(*) AS n FROM core.vacancy_version")[0]["n"] == 19


def test_quality_gate_stops_the_load_but_keeps_evidence(settings, fx_xml):
    payloads = [make_payload(i) for i in range(1, 6)] + [
        make_payload(i, name="") for i in range(50, 55)
    ]
    with pytest.raises(QualityGateError):
        run_all(settings, payloads, fx_xml, T1)
    assert rows(settings, "SELECT count(*) AS n FROM core.vacancy_version")[0]["n"] == 0
    assert rows(settings, "SELECT count(*) AS n FROM ops.rejected_record")[0]["n"] == 5
    assert rows(settings, "SELECT status FROM ops.pipeline_run")[0]["status"] == "failed"


def test_duplicates_inside_one_run_are_collapsed(settings, fx_xml):
    report = run_all(settings, [make_payload(1), make_payload(1), make_payload(2)], fx_xml, T1)
    assert report["duplicates_dropped"] == 1 and report["versions"]["new"] == 2


def test_raw_layer_keeps_original_payloads(settings, fx_xml):
    run_all(settings, [make_payload(1, name="Original title")], fx_xml, T1)
    raw = rows(settings, "SELECT payload FROM raw.hh_vacancy")
    assert raw[0]["payload"]["name"] == "Original title"
    assert rows(settings, "SELECT count(*) AS n FROM raw.nbk_rates_xml")[0]["n"] == 1


def test_salary_is_converted_with_stored_nbk_rate(settings, fx_xml):
    usd = {"from": 2000, "to": None, "currency": "USD", "gross": False}
    run_all(settings, [make_payload(1, salary=usd)], fx_xml, T1)
    assert (
        rows(settings, "SELECT salary_mid_kzt FROM core.vacancy_version")[0]["salary_mid_kzt"]
        == 1_000_000
    )


def test_fx_outage_falls_back_to_stored_rates(settings, fx_xml):
    run_all(settings, [make_payload(1)], fx_xml, T1)
    report = run_all(settings, [make_payload(1)], "<broken", T2)
    assert report["fx_date"] == "2026-11-17"
    stats = rows(settings, "SELECT stats FROM ops.pipeline_run ORDER BY run_id DESC LIMIT 1")[0][
        "stats"
    ]
    assert stats["fx"]["status"] == "fallback"


def test_stale_rates_stop_the_pipeline(settings, fx_xml):
    run_all(settings, [make_payload(1)], fx_xml, T1)
    with pytest.raises(RuntimeError, match="days old"):
        run_all(settings, [make_payload(1)], "<broken", T1 + timedelta(days=10))


def test_search_only_refresh_does_not_wipe_skills_from_details(settings, fx_xml):
    run_all(settings, [make_payload(1, skills=("Airflow", "Kafka"))], fx_xml, T1)
    run_all(settings, [make_payload(1, source="search")], fx_xml, T2)
    names = {
        r["name"]
        for r in rows(
            settings, "SELECT s.name FROM core.vacancy_skill v JOIN core.skill s USING (skill_id)"
        )
    }
    assert {"Airflow", "Kafka"} <= names


def test_marts_are_built(settings, fx_xml):
    payloads = [
        make_payload(i, salary=kzt(500000 + i * 10000), skills=("Python", "Airflow"))
        for i in range(1, 6)
    ]
    run_all(settings, payloads, fx_xml, T1)
    salary = rows(settings, "SELECT * FROM mart.salary_by_role")[0]
    assert salary["vacancies_with_salary"] == 5 and salary["median_kzt"] == 530000
    demand = {r["skill"]: r for r in rows(settings, "SELECT * FROM mart.skill_demand_weekly")}
    assert demand["Airflow"]["vacancies"] == 5 and float(demand["Airflow"]["share_pct"]) == 100.0
