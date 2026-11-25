from decimal import Decimal

from kzjobs.config import Settings
from kzjobs.transform.normalize import compute_hash, normalize_vacancy, strip_html
from kzjobs.transform.skills import SkillMatcher
from tests.helpers import RATES, make_payload

M = SkillMatcher.from_csv(Settings().skills_csv)


def test_strip_html():
    assert strip_html("<p>Hello&nbsp;<b>world</b></p><ul><li>a</li></ul>") == "Hello world a"
    assert strip_html(None) == ""


def test_salary_is_converted_to_kzt_and_rur_is_mapped():
    usd = normalize_vacancy(
        make_payload(salary={"from": 2000, "to": 3000, "currency": "USD", "gross": True}), M, RATES
    )
    assert usd["salary_from_kzt"] == Decimal("1000000.00")
    assert usd["salary_to_kzt"] == Decimal("1500000.00")
    rur = normalize_vacancy(
        make_payload(salary={"from": 100000, "to": None, "currency": "RUR", "gross": False}),
        M,
        RATES,
    )
    assert rur["salary_currency"] == "RUB" and rur["salary_from_kzt"] == Decimal("550000.00")


def test_missing_optional_fields_do_not_crash():
    row = normalize_vacancy(
        {"id": "7", "name": "X", "published_at": "2026-11-16T10:00:00+0500"}, M, RATES
    )
    assert row["vacancy_id"] == 7 and row["salary_currency"] is None and row["skills"] == []


def test_hash_ignores_fx_and_skills_but_tracks_business_fields():
    base = normalize_vacancy(
        make_payload(salary={"from": 500000, "to": None, "currency": "KZT", "gross": False}),
        M,
        RATES,
    )
    other_rates = {**RATES, "KZT": Decimal(1)}
    same = normalize_vacancy(
        make_payload(
            salary={"from": 500000, "to": None, "currency": "KZT", "gross": False},
            skills=("Docker",),
        ),
        M,
        other_rates,
    )
    assert base["row_hash"] == same["row_hash"]
    raised = normalize_vacancy(
        make_payload(salary={"from": 600000, "to": None, "currency": "KZT", "gross": False}),
        M,
        RATES,
    )
    assert raised["row_hash"] != base["row_hash"]
    archived = normalize_vacancy(
        make_payload(
            archived=True, salary={"from": 500000, "to": None, "currency": "KZT", "gross": False}
        ),
        M,
        RATES,
    )
    assert archived["row_hash"] != base["row_hash"]


def test_compute_hash_is_deterministic():
    row = normalize_vacancy(make_payload(), M, RATES)
    assert compute_hash(row) == compute_hash(dict(row))


def test_skills_come_from_key_skills_and_description():
    row = normalize_vacancy(make_payload(skills=("Airflow", "Kafka")), M, RATES)
    assert {"Airflow", "Kafka"} <= set(row["skills"])


def test_salary_range_field_is_used_and_non_monthly_is_ignored():
    payload = make_payload()
    payload["salary_range"] = {
        "from": 300000,
        "to": 500000,
        "currency": "KZT",
        "gross": False,
        "mode": {"id": "MONTH"},
    }
    row = normalize_vacancy(payload, M, RATES)
    assert row["salary_from"] == Decimal(300000) and row["salary_to_kzt"] == Decimal("500000.00")

    payload["salary_range"]["mode"] = {"id": "HOUR"}
    assert normalize_vacancy(payload, M, RATES)["salary_from"] is None
