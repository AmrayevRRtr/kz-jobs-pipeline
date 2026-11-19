from datetime import UTC, datetime

from kzjobs.config import Settings
from kzjobs.transform.normalize import normalize_vacancy
from kzjobs.transform.skills import SkillMatcher
from kzjobs.validate import validate
from tests.helpers import RATES, make_payload

M = SkillMatcher.from_csv(Settings().skills_csv)
NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


def run(**kw):
    row = normalize_vacancy(make_payload(**kw), M, RATES)
    return row, validate(row, NOW)


def salary(frm, to=None, cur="KZT"):
    return {"from": frm, "to": to, "currency": cur, "gross": False}


def test_clean_record_passes():
    _, res = run(salary=salary(600000, 900000))
    assert res.ok and not res.warnings


def test_errors_reject_the_record():
    assert "missing_title" in run(name="  ")[1].errors
    assert "published_in_future" in run(published="2027-01-01T10:00:00+0500")[1].errors
    assert "salary_range_inverted" in run(salary=salary(900000, 400000))[1].errors


def test_missing_id_and_date_are_errors():
    row = normalize_vacancy({"name": "X"}, M, RATES)
    res = validate(row, NOW)
    assert {"missing_id", "missing_published_at"} <= set(res.errors)


def test_outlier_salary_is_a_warning_and_is_excluded_from_kzt():
    row, res = run(salary=salary(800))
    assert res.ok and res.warnings == ["salary_outlier"]
    assert row["salary_flag"] == "outlier" and row["salary_from_kzt"] is None
    assert row["salary_from"] == 800


def test_unsupported_currency_is_a_warning():
    row, res = run(salary=salary(3000, None, "XYZ"))
    assert (
        res.warnings == ["salary_unsupported_currency"]
        and row["salary_flag"] == "unsupported_currency"
    )


def test_non_positive_salary_is_flagged():
    _, res = run(salary=salary(0, 500000))
    assert res.warnings == ["salary_non_positive"]


def test_no_salary_is_fine():
    row, res = run(salary=None)
    assert res.ok and not res.warnings and row["salary_flag"] is None
